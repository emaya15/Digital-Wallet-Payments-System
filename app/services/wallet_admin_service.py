"""Wallet read model plus admin freeze / unfreeze."""
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.wallet import AdminWalletOut, LimitsOut, WalletOut
from app.services.events import notify
from app.services.pin_service import get_pin_row
from app.services.wallet_service import limits_for, lock_wallets, spent_today_and_month
from app.utils.time import utcnow
from app.utils.validators import mask_phone


def wallet_out(db: Session, wallet: Wallet) -> WalletOut:
    limits = limits_for(wallet)
    spent_day, spent_month = spent_today_and_month(db, wallet.id)
    pin = get_pin_row(db, wallet.id)
    return WalletOut(
        wallet_id=wallet.id,
        wallet_number=wallet.wallet_number,
        balance=wallet.balance,
        kyc_level=wallet.kyc_level,
        is_frozen=wallet.is_frozen,
        freeze_reason=wallet.freeze_reason if wallet.is_frozen else None,
        pin_set=pin is not None,
        pin_locked_until=pin.locked_until if pin and pin.locked_until and pin.locked_until > utcnow() else None,
        limits=LimitsOut(
            max_balance=limits["max_balance"],
            daily_limit=limits["daily_limit"],
            monthly_limit=limits["monthly_limit"],
            spent_today=spent_day,
            spent_this_month=spent_month,
            remaining_today=max(limits["daily_limit"] - spent_day, 0),
            remaining_this_month=max(limits["monthly_limit"] - spent_month, 0),
        ),
    )


def admin_wallet_out(wallet: Wallet, user: User) -> AdminWalletOut:
    return AdminWalletOut(
        wallet_id=wallet.id,
        wallet_number=wallet.wallet_number,
        user_id=user.id,
        user_name=user.name,
        user_phone=mask_phone(user.phone),
        role=user.role,
        balance=wallet.balance,
        kyc_level=wallet.kyc_level,
        is_frozen=wallet.is_frozen,
        freeze_reason=wallet.freeze_reason,
        frozen_at=wallet.frozen_at,
    )


def list_wallets(db: Session, frozen: Optional[bool], skip: int, limit: int) -> List[AdminWalletOut]:
    stmt = select(Wallet, User).join(User, User.id == Wallet.user_id).order_by(Wallet.id).offset(skip).limit(limit)
    if frozen is not None:
        stmt = stmt.where(Wallet.is_frozen == frozen)
    return [admin_wallet_out(w, u) for w, u in db.execute(stmt).all()]


def freeze_wallet(db: Session, admin: User, wallet_id: int, reason: str) -> AdminWalletOut:
    if not reason or not reason.strip():
        raise HTTPException(status_code=422, detail="A freeze reason is mandatory")
    try:
        wallet = lock_wallets(db, [wallet_id])[wallet_id]
    except HTTPException:
        raise HTTPException(status_code=404, detail="Wallet not found")
    if wallet.is_frozen:
        raise HTTPException(status_code=409, detail="Wallet is already frozen")
    wallet.is_frozen = True
    wallet.freeze_reason = reason.strip()
    wallet.frozen_by = admin.id
    wallet.frozen_at = utcnow()
    owner = db.get(User, wallet.user_id)
    db.flush()
    notify(
        db,
        owner,
        "wallet_frozen",
        "Your wallet has been frozen",
        f"Your wallet was frozen by an administrator. Reason: {wallet.freeze_reason}",
        ws_event="wallet_frozen",
    )
    return admin_wallet_out(wallet, owner)


def unfreeze_wallet(db: Session, admin: User, wallet_id: int) -> AdminWalletOut:
    try:
        wallet = lock_wallets(db, [wallet_id])[wallet_id]
    except HTTPException:
        raise HTTPException(status_code=404, detail="Wallet not found")
    if not wallet.is_frozen:
        raise HTTPException(status_code=409, detail="Wallet is not frozen")
    wallet.is_frozen = False
    wallet.freeze_reason = None
    wallet.frozen_by = None
    wallet.frozen_at = None
    owner = db.get(User, wallet.user_id)
    db.flush()
    notify(db, owner, "wallet_unfrozen", "Your wallet has been unfrozen", "Your wallet is active again.", ws_event="wallet_unfrozen")
    return admin_wallet_out(wallet, owner)
