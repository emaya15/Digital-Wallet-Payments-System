"""Money requests: ask another user to pay you."""
import logging
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.constants import (
    MAX_PENDING_REQUESTS_PER_PAYER,
    MONEY_REQUEST_EXPIRY_HOURS,
    TxnType,
)
from app.models.money_request import MoneyRequest
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.money_request import MoneyRequestCreate, MoneyRequestOut, MoneyRequestPage, MoneyRequestPay
from app.services import transfer_service
from app.services.events import commit_and_dispatch, notify
from app.services.serializers import build_transaction_out, party_for_user
from app.services.wallet_service import lock_wallets_for_users
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


def effective_status(request: MoneyRequest) -> str:
    if request.status == "Pending" and request.expires_at < utcnow():
        return "Expired"
    return request.status


def _build_out(db: Session, requests: List[MoneyRequest], viewer_id: int) -> List[MoneyRequestOut]:
    if not requests:
        return []
    user_ids = {r.requester_id for r in requests} | {r.payer_id for r in requests}
    users: Dict[int, User] = {u.id: u for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()}
    txn_ids = {r.transaction_id for r in requests if r.transaction_id}
    refs: Dict[int, str] = {}
    if txn_ids:
        refs = dict(db.execute(select(Transaction.id, Transaction.transaction_ref).where(Transaction.id.in_(txn_ids))).all())
    return [
        MoneyRequestOut(
            id=r.id,
            direction="sent" if r.requester_id == viewer_id else "received",
            requester=party_for_user(users[r.requester_id]),
            payer=party_for_user(users[r.payer_id]),
            amount=r.amount,
            note=r.note,
            status=effective_status(r),
            expires_at=r.expires_at,
            transaction_ref=refs.get(r.transaction_id),
            responded_at=r.responded_at,
            created_at=r.created_at,
        )
        for r in requests
    ]


def create_request(db: Session, requester: User, payload: MoneyRequestCreate) -> MoneyRequestOut:
    payer = transfer_service.find_active_user_by_phone(db, payload.payer_phone, "Payer")
    if payer.id == requester.id:
        raise HTTPException(status_code=400, detail="You cannot request money from yourself")
    lock_wallets_for_users(db, [requester.id])  # serialises concurrent requests by the same user
    pending = db.execute(
        select(func.count(MoneyRequest.id)).where(
            MoneyRequest.requester_id == requester.id,
            MoneyRequest.payer_id == payer.id,
            MoneyRequest.status == "Pending",
            MoneyRequest.expires_at >= utcnow(),
        )
    ).scalar_one()
    if pending >= MAX_PENDING_REQUESTS_PER_PAYER:
        raise HTTPException(
            status_code=400,
            detail=f"You already have {MAX_PENDING_REQUESTS_PER_PAYER} pending requests to this person",
        )
    request = MoneyRequest(
        requester_id=requester.id,
        payer_id=payer.id,
        amount=payload.amount,
        note=payload.note,
        status="Pending",
        expires_at=utcnow() + timedelta(hours=MONEY_REQUEST_EXPIRY_HOURS),
    )
    db.add(request)
    db.flush()
    notify(
        db,
        payer,
        "money_request_received",
        "Money request received",
        f"{requester.name} requested ₹{request.amount}" + (f" for: {request.note}" if request.note else "") + f". Request #{request.id} expires in {MONEY_REQUEST_EXPIRY_HOURS} hours.",
        ws_event="money_request",
        ws_data={"request_id": request.id, "amount": str(request.amount)},
    )
    return _build_out(db, [request], requester.id)[0]


def list_requests(
    db: Session, user: User, direction: str, status: Optional[str], skip: int, limit: int
) -> MoneyRequestPage:
    conditions = []
    if direction == "sent":
        conditions.append(MoneyRequest.requester_id == user.id)
    elif direction == "received":
        conditions.append(MoneyRequest.payer_id == user.id)
    else:
        conditions.append(or_(MoneyRequest.requester_id == user.id, MoneyRequest.payer_id == user.id))
    now = utcnow()
    if status == "Pending":
        conditions += [MoneyRequest.status == "Pending", MoneyRequest.expires_at >= now]
    elif status == "Expired":
        conditions.append(
            or_(MoneyRequest.status == "Expired", and_(MoneyRequest.status == "Pending", MoneyRequest.expires_at < now))
        )
    elif status:
        conditions.append(MoneyRequest.status == status)
    total = db.execute(select(func.count(MoneyRequest.id)).where(*conditions)).scalar_one()
    rows = db.execute(
        select(MoneyRequest).where(*conditions).order_by(MoneyRequest.id.desc()).offset(skip).limit(limit)
    ).scalars().all()
    return MoneyRequestPage(total=total, skip=skip, limit=limit, items=_build_out(db, list(rows), user.id))


def _locked_request(db: Session, request_id: int) -> MoneyRequest:
    request = db.execute(
        select(MoneyRequest)
        .where(MoneyRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=404, detail="Money request not found")
    return request


def _ensure_open(request: MoneyRequest) -> None:
    if request.status != "Pending":
        raise HTTPException(status_code=409, detail=f"Money request is already {request.status}")
    if request.expires_at < utcnow():
        raise HTTPException(status_code=409, detail="Money request has expired")


def pay_request(db: Session, payer: User, request_id: int, payload: MoneyRequestPay) -> Tuple[dict, int]:
    request = _locked_request(db, request_id)
    if request.payer_id != payer.id:
        raise HTTPException(status_code=403, detail="Only the person who was asked to pay can pay this request")
    _ensure_open(request)
    requester = db.get(User, request.requester_id)
    if not requester.is_active:
        raise HTTPException(status_code=400, detail="Requester account is not active")
    txn = transfer_service.perform_transfer(
        db,
        payer,
        requester,
        request.amount,
        txn_type=TxnType.MONEY_REQUEST_PAYMENT,
        description=request.note or f"Money request #{request.id}",
        pin=payload.pin,
        otp_code=payload.otp_code,
    )
    request.status = "Paid"
    request.transaction_id = txn.id
    request.responded_at = utcnow()
    db.flush()
    message = "Payment placed on hold for review" if txn.status == "On Hold" else "Money request paid"
    out = build_transaction_out(db, txn, viewer_wallet_id=txn.sender_wallet_id, message=message)
    return out.model_dump(mode="json"), 200


def decline_request(db: Session, payer: User, request_id: int) -> MoneyRequestOut:
    request = _locked_request(db, request_id)
    if request.payer_id != payer.id:
        raise HTTPException(status_code=403, detail="Only the person who was asked to pay can decline this request")
    _ensure_open(request)
    request.status = "Declined"
    request.responded_at = utcnow()
    db.flush()
    requester = db.get(User, request.requester_id)
    notify(
        db,
        requester,
        "money_request_declined",
        "Money request declined",
        f"{payer.name} declined your request #{request.id} for ₹{request.amount}.",
        ws_event="money_request_declined",
        ws_data={"request_id": request.id},
    )
    return _build_out(db, [request], payer.id)[0]


def cancel_request(db: Session, requester: User, request_id: int) -> MoneyRequestOut:
    request = _locked_request(db, request_id)
    if request.requester_id != requester.id:
        raise HTTPException(status_code=403, detail="Only the person who created this request can cancel it")
    _ensure_open(request)
    request.status = "Cancelled"
    request.responded_at = utcnow()
    db.flush()
    return _build_out(db, [request], requester.id)[0]


def expire_old_requests(db: Session) -> int:
    """Hourly job: flip Pending requests past their 48 hour deadline to Expired."""
    result = db.execute(
        update(MoneyRequest)
        .where(MoneyRequest.status == "Pending", MoneyRequest.expires_at < utcnow())
        .values(status="Expired", responded_at=utcnow())
    )
    commit_and_dispatch(db)
    return result.rowcount or 0
