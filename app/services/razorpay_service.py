"""Razorpay (test mode) wallet top-ups.

Security model
--------------
* The browser's confirmation is never trusted on its own: the checkout
  signature is verified (HMAC SHA256) AND the payment is fetched from the
  Razorpay API and must be *captured*, belong to our order and match the amount.
* The webhook (signature verified over the raw body) is the authoritative path.
* Crediting is idempotent: the order row is locked and flips to ``Paid`` exactly
  once; payment ids are unique; webhook events are de-duplicated by event id.
"""
import hashlib
import json
import logging
import time
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import ADD_MONEY_MAX, ADD_MONEY_MIN
from app.database import SessionLocal
from app.models.razorpay import RazorpayOrder, WebhookEvent
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.razorpay import RazorpayConfirmOut, RazorpayConfirmRequest, RazorpayOrderOut, RazorpayOrderRequest
from app.services.add_money_service import credit_wallet_from_bank
from app.services.events import commit_and_dispatch
from app.services.serializers import build_transaction_out
from app.services.wallet_service import enforce_balance_cap, ensure_not_frozen, lock_wallets, lock_wallets_for_users
from app.utils.money import to_paise
from app.utils.signatures import verify_razorpay_payment_signature, verify_webhook_signature

logger = logging.getLogger(__name__)


def get_client():
    """Return a Razorpay SDK client (patched in tests)."""
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(status_code=503, detail="Razorpay is not configured on this server")
    import razorpay

    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


def create_order(db: Session, user: User, payload: RazorpayOrderRequest) -> RazorpayOrderOut:
    if payload.amount < ADD_MONEY_MIN or payload.amount > ADD_MONEY_MAX:
        raise HTTPException(status_code=422, detail=f"Amount must be between ₹{ADD_MONEY_MIN} and ₹{ADD_MONEY_MAX}")
    wallet = lock_wallets_for_users(db, [user.id])[user.id]
    ensure_not_frozen(wallet)
    enforce_balance_cap(wallet, payload.amount)
    paise = to_paise(payload.amount)
    client = get_client()
    try:
        order = client.order.create(
            {
                "amount": paise,
                "currency": "INR",
                "receipt": f"wallet_{user.id}_{int(time.time())}",
                "notes": {"user_id": str(user.id), "wallet_id": str(wallet.id)},
            }
        )
    except Exception:
        logger.exception("Razorpay order creation failed")
        raise HTTPException(status_code=502, detail="Could not create the Razorpay order. Please try again.")
    record = RazorpayOrder(
        user_id=user.id,
        wallet_id=wallet.id,
        razorpay_order_id=order["id"],
        amount=payload.amount,
        amount_paise=paise,
        currency="INR",
        status="Created",
    )
    db.add(record)
    db.flush()
    return RazorpayOrderOut(
        razorpay_order_id=record.razorpay_order_id,
        amount=record.amount,
        amount_paise=paise,
        currency="INR",
        key_id=settings.razorpay_key_id,
    )


def credit_order(db: Session, order_pk: int, payment_id: str) -> Tuple[Transaction, bool]:
    """Credit the wallet for a verified, captured payment. Returns (transaction, newly_credited)."""
    order = db.execute(
        select(RazorpayOrder)
        .where(RazorpayOrder.id == order_pk)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if order.status == "Paid":
        return db.get(Transaction, order.transaction_id), False
    wallet = lock_wallets(db, [order.wallet_id])[order.wallet_id]
    user = db.get(User, order.user_id)
    # The customer's money has already been captured by Razorpay, so it is credited
    # even if the wallet was frozen or is near its cap in the meantime.
    txn = credit_wallet_from_bank(
        db, user, wallet, order.amount, "Razorpay", f"Razorpay payment {payment_id}", enforce_cap=False
    )
    order.status = "Paid"
    order.razorpay_payment_id = payment_id
    order.transaction_id = txn.id
    db.flush()
    return txn, True


def _verified_captured_payment(order: RazorpayOrder, payment_id: str) -> dict:
    client = get_client()
    try:
        payment = client.payment.fetch(payment_id)
    except Exception:
        logger.exception("Could not fetch Razorpay payment %s", payment_id)
        raise HTTPException(status_code=502, detail="Could not verify the payment with Razorpay. Please retry shortly.")
    if payment.get("order_id") != order.razorpay_order_id or int(payment.get("amount", 0)) != order.amount_paise:
        raise HTTPException(status_code=400, detail="Payment does not match the order")
    if payment.get("status") == "authorized":
        try:
            client.payment.capture(payment_id, order.amount_paise)
            payment = client.payment.fetch(payment_id)
        except Exception:
            logger.exception("Could not capture Razorpay payment %s", payment_id)
            raise HTTPException(status_code=502, detail="Could not capture the payment with Razorpay")
    if payment.get("status") != "captured":
        raise HTTPException(
            status_code=409,
            detail="Payment is not captured yet. The wallet is credited once Razorpay confirms it.",
        )
    return payment


def confirm_payment(db: Session, user: User, payload: RazorpayConfirmRequest) -> Tuple[dict, int]:
    order = db.execute(
        select(RazorpayOrder).where(
            RazorpayOrder.razorpay_order_id == payload.razorpay_order_id, RazorpayOrder.user_id == user.id
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail="Razorpay order not found")
    if not verify_razorpay_payment_signature(
        payload.razorpay_order_id, payload.razorpay_payment_id, payload.razorpay_signature, settings.razorpay_key_secret
    ):
        raise HTTPException(status_code=400, detail="Invalid payment signature")
    if order.status == "Paid" and order.razorpay_payment_id != payload.razorpay_payment_id:
        raise HTTPException(status_code=409, detail="This order was already paid with a different payment")

    if order.status != "Paid":
        db.rollback()  # do not hold locks while calling the Razorpay API
        order = db.execute(
            select(RazorpayOrder).where(RazorpayOrder.id == order.id)
        ).scalar_one()
        _verified_captured_payment(order, payload.razorpay_payment_id)

    txn, credited = credit_order(db, order.id, payload.razorpay_payment_id)
    out = RazorpayConfirmOut(
        status="Paid",
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        credited=credited,
        transaction=build_transaction_out(db, txn, viewer_wallet_id=order.wallet_id, message="Wallet credited"),
    )
    return out.model_dump(mode="json"), (201 if credited else 200)


# ---------------------------------------------------------------- webhook


def _process_event(db: Session, event_type: str, payload: dict) -> str:
    entity = (payload.get("payload", {}).get("payment", {}) or {}).get("entity", {}) or {}
    order_id = entity.get("order_id")
    payment_id = entity.get("id")
    if not order_id or not payment_id:
        return "ignored"
    order = db.execute(select(RazorpayOrder).where(RazorpayOrder.razorpay_order_id == order_id)).scalar_one_or_none()
    if order is None:
        return "ignored"
    if event_type in ("payment.captured", "order.paid"):
        if entity.get("status") != "captured" or int(entity.get("amount", 0)) != order.amount_paise:
            return "ignored"
        _txn, credited = credit_order(db, order.id, payment_id)
        return "credited" if credited else "already_credited"
    if event_type == "payment.failed":
        locked = db.execute(
            select(RazorpayOrder).where(RazorpayOrder.id == order.id).with_for_update().execution_options(populate_existing=True)
        ).scalar_one()
        if locked.status == "Created":
            locked.status = "Failed"
            return "marked_failed"
        return "ignored"
    return "ignored"


def handle_webhook(raw_body: bytes, signature: Optional[str], event_id_header: Optional[str]) -> dict:
    """Verify the signature, de-duplicate by event id and apply the event (own DB session)."""
    if not settings.razorpay_webhook_secret:
        raise HTTPException(status_code=503, detail="Razorpay webhook secret is not configured")
    if not verify_webhook_signature(raw_body, signature or "", settings.razorpay_webhook_secret):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Webhook body is not valid JSON")
    event_type = str(payload.get("event", ""))
    event_id = event_id_header or hashlib.sha256(raw_body).hexdigest()

    db = SessionLocal()
    try:
        event = WebhookEvent(event_id=event_id, event_type=event_type, payload=payload, processed=False)
        db.add(event)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return {"status": "duplicate", "event_id": event_id}
        result = _process_event(db, event_type, payload)
        event.processed = True
        commit_and_dispatch(db)
        return {"status": result, "event_id": event_id}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
