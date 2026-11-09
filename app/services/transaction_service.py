"""Transaction history: filtering, sorting and pagination."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.constants import ALL_TXN_STATUSES, ALL_TXN_TYPES, Role, TxnStatus
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import TransactionOut, TransactionPage
from app.services.serializers import build_transaction_out, build_transaction_outs
from app.services.wallet_service import get_wallet_for_user
from app.utils.time import local_date_start_utc


def _visibility_clause(wallet_id: int):
    """A user sees what they sent, and what they received - except held / rejected incoming transfers."""
    return or_(
        Transaction.sender_wallet_id == wallet_id,
        and_(
            Transaction.receiver_wallet_id == wallet_id,
            Transaction.status.notin_([TxnStatus.ON_HOLD, TxnStatus.REJECTED]),
        ),
    )


def list_transactions(
    db: Session,
    user: User,
    *,
    type_: Optional[str],
    status: Optional[str],
    min_amount: Optional[Decimal],
    max_amount: Optional[Decimal],
    from_date: Optional[date],
    to_date: Optional[date],
    sort_by: str,
    order: str,
    skip: int,
    limit: int,
) -> TransactionPage:
    if type_ is not None and type_ not in ALL_TXN_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid type. Allowed: {ALL_TXN_TYPES}")
    if status is not None and status not in ALL_TXN_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Allowed: {ALL_TXN_STATUSES}")
    if sort_by not in ("date", "amount"):
        raise HTTPException(status_code=422, detail="sort_by must be 'date' or 'amount'")
    if order not in ("asc", "desc"):
        raise HTTPException(status_code=422, detail="order must be 'asc' or 'desc'")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise HTTPException(status_code=422, detail="min_amount cannot be greater than max_amount")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date cannot be after to_date")

    is_admin = user.role == Role.ADMIN
    wallet_id = None
    conditions = []
    if not is_admin:
        wallet_id = get_wallet_for_user(db, user.id).id
        conditions.append(_visibility_clause(wallet_id))
    if type_:
        conditions.append(Transaction.type == type_)
    if status:
        conditions.append(Transaction.status == status)
    if min_amount is not None:
        conditions.append(Transaction.amount >= min_amount)
    if max_amount is not None:
        conditions.append(Transaction.amount <= max_amount)
    if from_date:
        conditions.append(Transaction.created_at >= local_date_start_utc(from_date))
    if to_date:
        conditions.append(Transaction.created_at < local_date_start_utc(to_date + timedelta(days=1)))

    total = db.execute(select(func.count(Transaction.id)).where(*conditions)).scalar_one()
    sort_column = Transaction.created_at if sort_by == "date" else Transaction.amount
    primary = sort_column.asc() if order == "asc" else sort_column.desc()
    tiebreak = Transaction.id.asc() if order == "asc" else Transaction.id.desc()
    rows = db.execute(
        select(Transaction).where(*conditions).order_by(primary, tiebreak).offset(skip).limit(limit)
    ).scalars().all()
    items = build_transaction_outs(db, list(rows), viewer_wallet_id=wallet_id, admin=is_admin)
    return TransactionPage(total=total, skip=skip, limit=limit, items=items)


def get_transaction(db: Session, user: User, transaction_ref: str) -> TransactionOut:
    txn = db.execute(select(Transaction).where(Transaction.transaction_ref == transaction_ref)).scalar_one_or_none()
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if user.role == Role.ADMIN:
        return build_transaction_out(db, txn, admin=True, with_ledger=True)
    wallet_id = get_wallet_for_user(db, user.id).id
    is_sender = txn.sender_wallet_id == wallet_id
    is_visible_receiver = txn.receiver_wallet_id == wallet_id and txn.status not in (TxnStatus.ON_HOLD, TxnStatus.REJECTED)
    if not (is_sender or is_visible_receiver):
        raise HTTPException(status_code=404, detail="Transaction not found")
    return build_transaction_out(db, txn, viewer_wallet_id=wallet_id)
