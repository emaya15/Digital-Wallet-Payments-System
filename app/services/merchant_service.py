"""Merchant QR, QR payments (1% fee, 2% cashback), refunds, cashback payout."""
import base64
import logging
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Optional, Tuple
from urllib.parse import quote

import qrcode
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    CASHBACK_DELAY_HOURS,
    CASHBACK_MAX,
    CASHBACK_RATE,
    PLATFORM_FEE_RATE,
    REFUND_WINDOW_DAYS,
    AccountType,
    Role,
    TxnStatus,
    TxnType,
)
from app.models.cashback import Cashback
from app.models.merchant_payment import MerchantPayment
from app.models.refund import Refund
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.merchant import (
    MerchantPaymentItem,
    MerchantPaymentOut,
    MerchantPaymentPage,
    MerchantPaymentRequest,
    MerchantQrOut,
    RefundOut,
    RefundRequest,
)
from app.services import pin_service
from app.services.events import commit_and_dispatch, discard_after_commit, notify
from app.services.ledger_service import credit, debit, post_entries, system_account, wallet_account
from app.services.serializers import build_transaction_out
from app.services.wallet_service import (
    enforce_limits,
    ensure_not_frozen,
    lock_wallets,
    lock_wallets_for_users,
)
from app.utils.money import money, percent_of
from app.utils.time import local_date_start_utc, utcnow
from app.utils.validators import mask_phone

logger = logging.getLogger(__name__)


def merchant_qr(merchant: User) -> MerchantQrOut:
    if not merchant.merchant_code:
        raise HTTPException(status_code=400, detail="Merchant code is not available for this account")
    payload = f"digitalwallet://pay?merchant_code={merchant.merchant_code}&name={quote(merchant.business_name or '')}"
    image = qrcode.make(payload)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return MerchantQrOut(
        merchant_code=merchant.merchant_code,
        business_name=merchant.business_name or "",
        qr_payload=payload,
        qr_png_base64=base64.b64encode(buffer.getvalue()).decode("ascii"),
    )


def pay_merchant(db: Session, payer: User, payload: MerchantPaymentRequest) -> Tuple[dict, int]:
    merchant = db.execute(
        select(User).where(User.merchant_code == payload.merchant_code, User.role == Role.MERCHANT)
    ).scalar_one_or_none()
    if merchant is None:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if not merchant.is_active:
        raise HTTPException(status_code=400, detail="Merchant account is not active")
    if merchant.id == payer.id:
        raise HTTPException(status_code=400, detail="You cannot pay your own merchant account")

    amount = payload.amount
    wallets = lock_wallets_for_users(db, [payer.id, merchant.id])
    payer_wallet, merchant_wallet = wallets[payer.id], wallets[merchant.id]
    ensure_not_frozen(payer_wallet, "Your")
    ensure_not_frozen(merchant_wallet, "Merchant's")
    pin_service.verify_pin(db, payer_wallet, payload.pin)
    enforce_limits(db, payer_wallet, amount)
    if payer_wallet.balance < amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    fee = percent_of(amount, PLATFORM_FEE_RATE)
    net = amount - fee
    txn = Transaction(
        type=TxnType.MERCHANT_PAYMENT,
        status=TxnStatus.SUCCESS,
        amount=amount,
        fee=fee,
        sender_wallet_id=payer_wallet.id,
        receiver_wallet_id=merchant_wallet.id,
        description=payload.note or f"Payment to {merchant.business_name}",
    )
    db.add(txn)
    db.flush()
    legs = [
        debit(wallet_account(db, payer_wallet.id), amount),
        credit(wallet_account(db, merchant_wallet.id), net),
    ]
    if fee > 0:
        legs.append(credit(system_account(db, AccountType.FEES), fee))
    post_entries(db, txn, legs)
    txn.sender_balance_after = payer_wallet.balance
    txn.receiver_balance_after = merchant_wallet.balance

    cashback_amount = min(percent_of(amount, CASHBACK_RATE), CASHBACK_MAX)
    payment = MerchantPayment(
        transaction_id=txn.id,
        payer_user_id=payer.id,
        merchant_user_id=merchant.id,
        merchant_code=merchant.merchant_code,
        amount=amount,
        fee=fee,
        net_amount=net,
        cashback_amount=cashback_amount,
    )
    db.add(payment)
    db.flush()
    credit_at = utcnow() + timedelta(hours=CASHBACK_DELAY_HOURS)
    if cashback_amount > 0:
        db.add(
            Cashback(
                merchant_payment_id=payment.id,
                user_id=payer.id,
                wallet_id=payer_wallet.id,
                amount=cashback_amount,
                status="Pending",
                credit_at=credit_at,
            )
        )
    db.flush()

    notify(
        db,
        payer,
        "merchant_payment",
        "Merchant payment successful",
        f"You paid ₹{amount} to {merchant.business_name} ({txn.transaction_ref}). Cashback of ₹{cashback_amount} will be credited within {CASHBACK_DELAY_HOURS} hours.",
        ws_event="payment_sent",
        ws_data={"transaction_ref": txn.transaction_ref, "amount": str(amount), "balance": str(payer_wallet.balance)},
    )
    notify(
        db,
        merchant,
        "merchant_payment_received",
        "Payment received",
        f"{payer.name} paid you ₹{amount} ({txn.transaction_ref}). Fee ₹{fee}, net ₹{net}.",
        ws_event="merchant_payment",
        ws_data={
            "transaction_ref": txn.transaction_ref,
            "amount": str(amount),
            "fee": str(fee),
            "net_amount": str(net),
            "balance": str(merchant_wallet.balance),
        },
    )

    base = build_transaction_out(db, txn, viewer_wallet_id=payer_wallet.id, message="Payment successful")
    out = MerchantPaymentOut(
        **base.model_dump(),
        merchant_code=merchant.merchant_code,
        business_name=merchant.business_name,
        net_amount=net,
        cashback_amount=cashback_amount,
        cashback_credit_at=credit_at if cashback_amount > 0 else None,
    )
    return out.model_dump(mode="json"), 201


def refund_payment(db: Session, merchant: User, transaction_ref: str, payload: RefundRequest) -> Tuple[dict, int]:
    txn = db.execute(
        select(Transaction).where(
            Transaction.transaction_ref == transaction_ref, Transaction.type == TxnType.MERCHANT_PAYMENT
        )
    ).scalar_one_or_none()
    if txn is None:
        raise HTTPException(status_code=404, detail="Merchant payment not found")
    payment = db.execute(
        select(MerchantPayment)
        .where(MerchantPayment.transaction_id == txn.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if payment.merchant_user_id != merchant.id:
        raise HTTPException(status_code=403, detail="Only the receiving merchant can refund this payment")
    if txn.status != TxnStatus.SUCCESS:
        raise HTTPException(status_code=400, detail="Only successful payments can be refunded")
    if utcnow() - txn.created_at > timedelta(days=REFUND_WINDOW_DAYS):
        raise HTTPException(status_code=400, detail=f"Refunds are only allowed within {REFUND_WINDOW_DAYS} days of payment")

    remaining = payment.amount - payment.refunded_amount
    if remaining <= 0:
        raise HTTPException(status_code=400, detail="This payment has already been fully refunded")
    amount = payload.amount if payload.amount is not None else remaining
    if amount > remaining:
        raise HTTPException(status_code=400, detail=f"Refund amount exceeds the refundable balance of ₹{remaining}")

    fee_left = payment.fee - payment.fee_refunded
    if amount == remaining:
        fee_part = fee_left  # last refund returns the exact remaining fee (no rounding drift)
    else:
        fee_part = min(money(payment.fee * amount / payment.amount), fee_left)
    merchant_debit = amount - fee_part

    wallets = lock_wallets_for_users(db, [merchant.id, payment.payer_user_id])
    merchant_wallet, payer_wallet = wallets[merchant.id], wallets[payment.payer_user_id]
    ensure_not_frozen(merchant_wallet, "Your")
    ensure_not_frozen(payer_wallet, "Customer's")
    if merchant_wallet.balance < merchant_debit:
        raise HTTPException(status_code=400, detail="Insufficient merchant wallet balance to issue this refund")

    refund_txn = Transaction(
        type=TxnType.REFUND,
        status=TxnStatus.SUCCESS,
        amount=amount,
        sender_wallet_id=merchant_wallet.id,
        receiver_wallet_id=payer_wallet.id,
        parent_transaction_id=txn.id,
        description=payload.reason or f"Refund for {txn.transaction_ref}",
    )
    db.add(refund_txn)
    db.flush()
    legs = [credit(wallet_account(db, payer_wallet.id), amount)]
    if merchant_debit > 0:
        legs.append(debit(wallet_account(db, merchant_wallet.id), merchant_debit))
    if fee_part > 0:
        legs.append(debit(system_account(db, AccountType.FEES), fee_part))
    post_entries(db, refund_txn, legs)
    refund_txn.sender_balance_after = merchant_wallet.balance
    refund_txn.receiver_balance_after = payer_wallet.balance

    payment.refunded_amount = payment.refunded_amount + amount
    payment.fee_refunded = payment.fee_refunded + fee_part
    db.add(
        Refund(
            transaction_id=refund_txn.id,
            merchant_payment_id=payment.id,
            amount=amount,
            fee_refunded=fee_part,
            reason=payload.reason,
            refunded_by=merchant.id,
        )
    )
    if payment.refunded_amount >= payment.amount:  # fully refunded before cashback was paid out
        cashback = db.execute(
            select(Cashback).where(Cashback.merchant_payment_id == payment.id, Cashback.status == "Pending").with_for_update()
        ).scalar_one_or_none()
        if cashback is not None:
            cashback.status = "Cancelled"
    db.flush()

    payer_user = db.get(User, payment.payer_user_id)
    notify(
        db,
        payer_user,
        "refund_received",
        "Refund received",
        f"{merchant.business_name} refunded ₹{amount} for {txn.transaction_ref} ({refund_txn.transaction_ref}).",
        ws_event="payment_received",
        ws_data={"transaction_ref": refund_txn.transaction_ref, "amount": str(amount), "balance": str(payer_wallet.balance)},
    )
    notify(
        db,
        merchant,
        "refund_issued",
        "Refund issued",
        f"You refunded ₹{amount} on {txn.transaction_ref} ({refund_txn.transaction_ref}).",
        ws_event="merchant_payment",
        ws_data={"transaction_ref": refund_txn.transaction_ref, "refund": str(amount), "balance": str(merchant_wallet.balance)},
    )
    out = RefundOut(
        refund_transaction_ref=refund_txn.transaction_ref,
        original_transaction_ref=txn.transaction_ref,
        amount=amount,
        fee_refunded=fee_part,
        total_refunded=payment.refunded_amount,
        remaining_refundable=payment.amount - payment.refunded_amount,
        status=refund_txn.status,
        created_at=refund_txn.created_at,
    )
    return out.model_dump(mode="json"), 201


def list_merchant_payments(
    db: Session,
    merchant: User,
    skip: int,
    limit: int,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> MerchantPaymentPage:
    conditions = [MerchantPayment.merchant_user_id == merchant.id]
    if from_date:
        conditions.append(MerchantPayment.created_at >= local_date_start_utc(from_date))
    if to_date:
        conditions.append(MerchantPayment.created_at < local_date_start_utc(to_date + timedelta(days=1)))
    total = db.execute(select(func.count(MerchantPayment.id)).where(*conditions)).scalar_one()
    rows = db.execute(
        select(MerchantPayment, Transaction, User)
        .join(Transaction, Transaction.id == MerchantPayment.transaction_id)
        .join(User, User.id == MerchantPayment.payer_user_id)
        .where(*conditions)
        .order_by(MerchantPayment.id.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    items = [
        MerchantPaymentItem(
            transaction_ref=txn.transaction_ref,
            payer_name=payer.name,
            payer_phone=mask_phone(payer.phone),
            amount=mp.amount,
            fee=mp.fee,
            net_amount=mp.net_amount,
            refunded_amount=mp.refunded_amount,
            status=txn.status,
            created_at=mp.created_at,
        )
        for mp, txn, payer in rows
    ]
    return MerchantPaymentPage(total=total, skip=skip, limit=limit, items=items)


# ------------------------------------------------------------------ cashback job


def _credit_one_cashback(db: Session, cashback_id: int) -> bool:
    cashback = db.execute(
        select(Cashback)
        .where(Cashback.id == cashback_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if cashback is None or cashback.status != "Pending" or cashback.credit_at > utcnow():
        return False
    wallet = lock_wallets(db, [cashback.wallet_id])[cashback.wallet_id]
    if wallet.is_frozen:
        return False  # stays Pending; retried on the next run once unfrozen
    txn = Transaction(
        type=TxnType.CASHBACK,
        status=TxnStatus.SUCCESS,
        amount=cashback.amount,
        receiver_wallet_id=wallet.id,
        description="Cashback on merchant payment",
    )
    db.add(txn)
    db.flush()
    pool = system_account(db, AccountType.CASHBACK_POOL)
    post_entries(db, txn, [debit(pool, cashback.amount), credit(wallet_account(db, wallet.id), cashback.amount)])
    txn.receiver_balance_after = wallet.balance
    cashback.status = "Credited"
    cashback.credited_at = utcnow()
    cashback.transaction_id = txn.id
    db.flush()
    owner = db.get(User, cashback.user_id)
    notify(
        db,
        owner,
        "cashback_credited",
        "Cashback credited",
        f"₹{cashback.amount} cashback has been credited to your wallet ({txn.transaction_ref}).",
        ws_event="payment_received",
        ws_data={"transaction_ref": txn.transaction_ref, "amount": str(cashback.amount), "balance": str(wallet.balance)},
    )
    return True


def process_due_cashbacks(db: Session, batch: int = 200) -> int:
    """Credit every cashback whose 24h delay has elapsed. Idempotent and safe to run concurrently."""
    ids = db.execute(
        select(Cashback.id)
        .where(Cashback.status == "Pending", Cashback.credit_at <= utcnow())
        .order_by(Cashback.id)
        .limit(batch)
    ).scalars().all()
    db.rollback()
    credited = 0
    for cashback_id in ids:
        try:
            if _credit_one_cashback(db, cashback_id):
                credited += 1
            commit_and_dispatch(db)
        except Exception:
            db.rollback()
            discard_after_commit(db)
            logger.exception("Cashback %s could not be credited", cashback_id)
    return credited


__all__ = [
    "merchant_qr",
    "pay_merchant",
    "refund_payment",
    "list_merchant_payments",
    "process_due_cashbacks",
]
