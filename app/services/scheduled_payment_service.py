"""Recurring (monthly) transfers executed through the normal transfer service."""
import logging
from datetime import time
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import OTP_REQUIRED_ABOVE, OtpPurpose, TxnStatus, TxnType
from app.models.scheduled_payment import ScheduledPayment, ScheduledPaymentExecution
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.scheduled_payment import (
    ExecutionOut,
    ScheduledPaymentCreate,
    ScheduledPaymentOut,
    ScheduledPaymentUpdate,
)
from app.services import otp_service, pin_service, transfer_service
from app.services.events import commit_and_dispatch, discard_after_commit, hook_count, notify, truncate_hooks
from app.services.serializers import party_for_user
from app.services.wallet_service import ensure_not_frozen, lock_wallets_for_users
from app.utils.time import add_months, local_datetime_to_utc, today_local, utcnow

logger = logging.getLogger(__name__)

RUN_AT = time(9, 0)  # IST


def _run_datetime(day):
    return local_datetime_to_utc(day, RUN_AT)


def _next_future_occurrence(payment: ScheduledPayment, now):
    """First monthly occurrence (09:00 IST) strictly after ``now``."""
    index = 0
    while True:
        day = add_months(payment.start_date, index, anchor_day=payment.anchor_day)
        run_at = _run_datetime(day)
        if run_at > now:
            return day, run_at
        index += 1


def _apply_next_run(payment: ScheduledPayment, now) -> None:
    day, run_at = _next_future_occurrence(payment, now)
    if payment.end_date is not None and day > payment.end_date:
        payment.status = "Completed"
        payment.next_run_at = None
    else:
        payment.next_run_at = run_at


def _out(db: Session, payments: List[ScheduledPayment], with_executions: bool = False) -> List[ScheduledPaymentOut]:
    if not payments:
        return []
    receivers: Dict[int, User] = {
        u.id: u
        for u in db.execute(select(User).where(User.id.in_({p.receiver_user_id for p in payments}))).scalars().all()
    }
    outs = []
    for p in payments:
        executions = None
        if with_executions:
            rows = db.execute(
                select(ScheduledPaymentExecution, Transaction.transaction_ref)
                .outerjoin(Transaction, Transaction.id == ScheduledPaymentExecution.transaction_id)
                .where(ScheduledPaymentExecution.scheduled_payment_id == p.id)
                .order_by(ScheduledPaymentExecution.id.desc())
                .limit(50)
            ).all()
            executions = [
                ExecutionOut(
                    id=e.id,
                    executed_at=e.executed_at,
                    status=e.status,
                    transaction_ref=ref,
                    failure_reason=e.failure_reason,
                )
                for e, ref in rows
            ]
        outs.append(
            ScheduledPaymentOut(
                id=p.id,
                receiver=party_for_user(receivers[p.receiver_user_id]),
                amount=p.amount,
                note=p.note,
                frequency=p.frequency,
                start_date=p.start_date,
                end_date=p.end_date,
                next_run_at=p.next_run_at,
                status=p.status,
                last_run_at=p.last_run_at,
                run_count=p.run_count,
                created_at=p.created_at,
                executions=executions,
            )
        )
    return outs


def create_payment(db: Session, user: User, payload: ScheduledPaymentCreate) -> ScheduledPaymentOut:
    receiver = transfer_service.find_active_user_by_phone(db, payload.receiver_phone)
    if receiver.id == user.id:
        raise HTTPException(status_code=400, detail="You cannot schedule a payment to yourself")
    if payload.start_date < today_local():
        raise HTTPException(status_code=422, detail="start_date cannot be in the past")
    wallet = lock_wallets_for_users(db, [user.id])[user.id]
    ensure_not_frozen(wallet)
    pin_service.verify_pin(db, wallet, payload.pin)
    if payload.amount > OTP_REQUIRED_ABOVE:
        # The OTP given now authorises the whole recurring instruction.
        otp_service.require_otp(db, user, OtpPurpose.SCHEDULED_PAYMENT, payload.otp_code)
    payment = ScheduledPayment(
        user_id=user.id,
        receiver_user_id=receiver.id,
        amount=payload.amount,
        note=payload.note,
        frequency=payload.frequency,
        anchor_day=payload.start_date.day,
        start_date=payload.start_date,
        end_date=payload.end_date,
        next_run_at=_run_datetime(payload.start_date),
        status="Active",
        run_count=0,
    )
    db.add(payment)
    db.flush()
    return _out(db, [payment])[0]


def list_payments(db: Session, user: User, skip: int, limit: int, status: Optional[str]):
    conditions = [ScheduledPayment.user_id == user.id]
    if status:
        conditions.append(ScheduledPayment.status == status)
    total = db.execute(select(func.count(ScheduledPayment.id)).where(*conditions)).scalar_one()
    rows = db.execute(
        select(ScheduledPayment).where(*conditions).order_by(ScheduledPayment.id.desc()).offset(skip).limit(limit)
    ).scalars().all()
    return total, _out(db, list(rows))


def _get_owned(db: Session, user: User, payment_id: int, lock: bool = False) -> ScheduledPayment:
    stmt = select(ScheduledPayment).where(ScheduledPayment.id == payment_id, ScheduledPayment.user_id == user.id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    payment = db.execute(stmt).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Scheduled payment not found")
    return payment


def get_payment(db: Session, user: User, payment_id: int) -> ScheduledPaymentOut:
    payment = _get_owned(db, user, payment_id)
    return _out(db, [payment], with_executions=True)[0]


def update_payment(db: Session, user: User, payment_id: int, payload: ScheduledPaymentUpdate) -> ScheduledPaymentOut:
    payment = _get_owned(db, user, payment_id, lock=True)
    if payment.status in ("Cancelled", "Completed"):
        raise HTTPException(status_code=409, detail=f"A {payment.status.lower()} scheduled payment cannot be changed")
    wallet = lock_wallets_for_users(db, [user.id])[user.id]
    pin_service.verify_pin(db, wallet, payload.pin)

    new_amount = payload.amount if payload.amount is not None else payment.amount
    if new_amount > OTP_REQUIRED_ABOVE and new_amount != payment.amount:
        otp_service.require_otp(db, user, OtpPurpose.SCHEDULED_PAYMENT, payload.otp_code)
    if payload.end_date is not None and payload.end_date < payment.start_date:
        raise HTTPException(status_code=422, detail="end_date cannot be before start_date")

    payment.amount = new_amount
    if payload.note is not None:
        payment.note = payload.note
    if payload.end_date is not None:
        payment.end_date = payload.end_date
    now = utcnow()
    if payload.status == "Paused":
        payment.status = "Paused"
    elif payload.status == "Active" and payment.status == "Paused":
        payment.status = "Active"
        _apply_next_run(payment, now)  # never fire for missed months while paused
    elif payment.status == "Active" and payment.end_date is not None:
        _apply_next_run(payment, now) if payment.next_run_at is None else None
    db.flush()
    return _out(db, [payment])[0]


def cancel_payment(db: Session, user: User, payment_id: int) -> None:
    payment = _get_owned(db, user, payment_id, lock=True)
    if payment.status == "Cancelled":
        raise HTTPException(status_code=409, detail="Scheduled payment is already cancelled")
    payment.status = "Cancelled"
    payment.next_run_at = None
    db.flush()


# ------------------------------------------------------------------ job


def _execute_one(db: Session, payment_id: int) -> str:
    now = utcnow()
    payment = db.execute(
        select(ScheduledPayment)
        .where(ScheduledPayment.id == payment_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if payment is None or payment.status != "Active" or payment.next_run_at is None or payment.next_run_at > now:
        return "skipped"

    sender = db.get(User, payment.user_id)
    receiver = db.get(User, payment.receiver_user_id)
    hooks_before = hook_count(db)
    status, transaction_id, reason = "Failed", None, None
    try:
        with db.begin_nested():  # a failed transfer must not undo the execution record
            txn = transfer_service.perform_transfer(
                db,
                sender,
                receiver,
                payment.amount,
                txn_type=TxnType.SCHEDULED_PAYMENT,
                description=payment.note or "Scheduled payment",
                require_pin=False,
                require_otp=False,
            )
        status = "On Hold" if txn.status == TxnStatus.ON_HOLD else "Success"
        transaction_id = txn.id
    except HTTPException as exc:
        truncate_hooks(db, hooks_before)
        reason = str(exc.detail)[:255]
        notify(
            db,
            sender,
            "scheduled_payment_failed",
            "Scheduled payment failed",
            f"Your scheduled payment of ₹{payment.amount} to {receiver.name} could not be completed: {reason}",
            ws_event="scheduled_payment_failed",
            ws_data={"scheduled_payment_id": payment.id},
        )

    db.add(
        ScheduledPaymentExecution(
            scheduled_payment_id=payment.id,
            executed_at=now,
            status=status,
            transaction_id=transaction_id,
            failure_reason=reason,
        )
    )
    payment.run_count += 1
    payment.last_run_at = now
    _apply_next_run(payment, now)  # advancing in the same DB transaction prevents double execution
    db.flush()
    return status.lower().replace(" ", "_")


def execute_due_payments(db: Session, batch: int = 100) -> Dict[str, int]:
    ids = db.execute(
        select(ScheduledPayment.id)
        .where(ScheduledPayment.status == "Active", ScheduledPayment.next_run_at <= utcnow())
        .order_by(ScheduledPayment.id)
        .limit(batch)
    ).scalars().all()
    db.rollback()
    counts: Dict[str, int] = {}
    for payment_id in ids:
        try:
            outcome = _execute_one(db, payment_id)
            commit_and_dispatch(db)
            counts[outcome] = counts.get(outcome, 0) + 1
        except Exception:
            db.rollback()
            discard_after_commit(db)
            logger.exception("Scheduled payment %s could not be executed", payment_id)
    return counts
