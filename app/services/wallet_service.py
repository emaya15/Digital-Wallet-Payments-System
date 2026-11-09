"""Wallet creation, locking, KYC limits and freeze checks."""
from decimal import Decimal
from typing import Dict, Iterable

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    KYC_LIMITS,
    LIMIT_COUNTED_STATUSES,
    OUTGOING_LIMIT_TYPES,
    AccountType,
    Role,
)
from app.models.ledger import LedgerAccount
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.utils.refs import new_wallet_number
from app.utils.time import local_day_bounds, month_bounds, today_local


def create_wallet(db: Session, user: User) -> Wallet:
    wallet = Wallet(
        user_id=user.id,
        wallet_number=new_wallet_number(),
        balance=Decimal("0.00"),
        kyc_level="None",
        is_frozen=False,
    )
    db.add(wallet)
    db.flush()
    account_type = AccountType.MERCHANT_WALLET if user.role == Role.MERCHANT else AccountType.USER_WALLET
    db.add(
        LedgerAccount(
            name=f"{account_type}:{wallet.wallet_number}",
            account_type=account_type,
            wallet_id=wallet.id,
        )
    )
    db.flush()
    return wallet


def get_wallet_for_user(db: Session, user_id: int) -> Wallet:
    wallet = db.execute(select(Wallet).where(Wallet.user_id == user_id)).scalar_one_or_none()
    if wallet is None:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return wallet


def lock_wallets(db: Session, wallet_ids: Iterable[int]) -> Dict[int, Wallet]:
    """Lock wallets in ASCENDING id order (deadlock avoidance) and return them by id.

    ``populate_existing`` guarantees the returned objects carry the freshly read,
    locked balances even if the session already had them cached.
    """
    ids = sorted(set(wallet_ids))
    if not ids:
        return {}
    rows = (
        db.execute(
            select(Wallet)
            .where(Wallet.id.in_(ids))
            .order_by(Wallet.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )
    found = {wallet.id: wallet for wallet in rows}
    if len(found) != len(ids):
        raise HTTPException(status_code=404, detail="Wallet not found")
    return found


def lock_wallets_for_users(db: Session, user_ids: Iterable[int]) -> Dict[int, Wallet]:
    """Lock the wallets that belong to ``user_ids``; result is keyed by USER id."""
    ids = sorted(set(user_ids))
    wallet_rows = db.execute(select(Wallet.id, Wallet.user_id).where(Wallet.user_id.in_(ids))).all()
    if len(wallet_rows) != len(ids):
        raise HTTPException(status_code=404, detail="Wallet not found")
    locked = lock_wallets(db, [row.id for row in wallet_rows])
    return {wallet.user_id: wallet for wallet in locked.values()}


def limits_for(wallet: Wallet) -> Dict[str, Decimal]:
    return KYC_LIMITS.get(wallet.kyc_level, KYC_LIMITS["None"])


def ensure_not_frozen(wallet: Wallet, who: str = "Your") -> None:
    if wallet.is_frozen:
        reason = f": {wallet.freeze_reason}" if wallet.freeze_reason else ""
        raise HTTPException(status_code=423, detail=f"{who} wallet is frozen{reason}")


def outgoing_total(db: Session, wallet_id: int, start, end) -> Decimal:
    total = db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.sender_wallet_id == wallet_id,
            Transaction.type.in_(OUTGOING_LIMIT_TYPES),
            Transaction.status.in_(LIMIT_COUNTED_STATUSES),
            Transaction.created_at >= start,
            Transaction.created_at < end,
        )
    ).scalar_one()
    return Decimal(str(total))


def spent_today_and_month(db: Session, wallet_id: int):
    today = today_local()
    day_start, day_end = local_day_bounds(today)
    month_start, month_end = month_bounds(today.year, today.month)
    return (
        outgoing_total(db, wallet_id, day_start, day_end),
        outgoing_total(db, wallet_id, month_start, month_end),
    )


def enforce_limits(db: Session, wallet: Wallet, amount: Decimal) -> None:
    """Reject the debit if it would exceed the KYC daily / monthly outgoing limits."""
    limits = limits_for(wallet)
    daily, monthly = spent_today_and_month(db, wallet.id)
    if daily + amount > limits["daily_limit"]:
        raise HTTPException(
            status_code=400,
            detail=f"Daily transaction limit of ₹{limits['daily_limit']} exceeded for {wallet.kyc_level} KYC",
        )
    if monthly + amount > limits["monthly_limit"]:
        raise HTTPException(
            status_code=400,
            detail=f"Monthly transaction limit of ₹{limits['monthly_limit']} exceeded for {wallet.kyc_level} KYC",
        )


def enforce_balance_cap(wallet: Wallet, amount: Decimal, who: str = "Your") -> None:
    cap = limits_for(wallet)["max_balance"]
    if wallet.balance + amount > cap:
        raise HTTPException(
            status_code=400,
            detail=f"{who} wallet balance limit of ₹{cap} for {wallet.kyc_level} KYC would be exceeded",
        )
