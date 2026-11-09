"""Transaction PIN: hashed, rejects simple PINs, locks payments after 3 wrong attempts."""
import math
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_secret, verify_secret
from app.constants import OtpPurpose, PIN_LOCK_MINUTES, PIN_MAX_ATTEMPTS
from app.models.pin import TransactionPin
from app.models.user import User
from app.models.wallet import Wallet
from app.services import otp_service
from app.services.events import notify
from app.services.wallet_service import lock_wallets
from app.utils.time import utcnow
from app.utils.validators import is_simple_pin


def get_pin_row(db: Session, wallet_id: int, lock: bool = False) -> Optional[TransactionPin]:
    stmt = select(TransactionPin).where(TransactionPin.wallet_id == wallet_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return db.execute(stmt).scalar_one_or_none()


def _reject_simple(pin: str) -> None:
    if is_simple_pin(pin):
        raise HTTPException(
            status_code=422,
            detail="PIN is too simple. Avoid repeated or sequential digits such as 1111 or 1234.",
        )


def set_pin(db: Session, user: User, wallet: Wallet, pin: str, confirm_pin: str) -> None:
    lock_wallets(db, [wallet.id])
    if pin != confirm_pin:
        raise HTTPException(status_code=400, detail="PIN and confirm_pin do not match")
    _reject_simple(pin)
    if get_pin_row(db, wallet.id, lock=True) is not None:
        raise HTTPException(status_code=409, detail="A transaction PIN is already set. Use the change PIN API.")
    db.add(
        TransactionPin(
            user_id=user.id,
            wallet_id=wallet.id,
            pin_hash=hash_secret(pin),
            failed_attempts=0,
            last_changed_at=utcnow(),
        )
    )
    db.flush()


def verify_pin(db: Session, wallet: Wallet, pin: str) -> None:
    """Verify the PIN of ``wallet`` (caller already holds the wallet lock).

    Wrong attempts are committed straight away, otherwise the surrounding
    request rollback would erase the attempt counter and lockout.
    """
    row = get_pin_row(db, wallet.id, lock=True)
    if row is None:
        raise HTTPException(status_code=400, detail="Transaction PIN is not set. Please set a PIN first.")
    now = utcnow()
    if row.locked_until is not None:
        if row.locked_until > now:
            minutes = max(1, math.ceil((row.locked_until - now).total_seconds() / 60))
            raise HTTPException(
                status_code=423,
                detail=f"Payments are locked for {minutes} more minute(s) after too many incorrect PIN attempts",
            )
        row.locked_until = None
        row.failed_attempts = 0
    if verify_secret(pin, row.pin_hash):
        if row.failed_attempts:
            row.failed_attempts = 0
            db.flush()
        return
    row.failed_attempts += 1
    if row.failed_attempts >= PIN_MAX_ATTEMPTS:
        row.locked_until = now + timedelta(minutes=PIN_LOCK_MINUTES)
        db.commit()
        raise HTTPException(
            status_code=423,
            detail=f"Too many incorrect PIN attempts. Payments are locked for {PIN_LOCK_MINUTES} minutes.",
        )
    remaining = PIN_MAX_ATTEMPTS - row.failed_attempts
    db.commit()
    raise HTTPException(status_code=403, detail=f"Incorrect PIN. {remaining} attempt(s) remaining.")


def change_pin(db: Session, user: User, wallet: Wallet, old_pin: str, new_pin: str) -> None:
    lock_wallets(db, [wallet.id])
    verify_pin(db, wallet, old_pin)
    if old_pin == new_pin:
        raise HTTPException(status_code=400, detail="New PIN must be different from the old PIN")
    _reject_simple(new_pin)
    row = get_pin_row(db, wallet.id, lock=True)
    row.pin_hash = hash_secret(new_pin)
    row.last_changed_at = utcnow()
    row.failed_attempts = 0
    row.locked_until = None
    db.flush()
    notify(db, user, "pin_changed", "Transaction PIN changed", "Your wallet transaction PIN was changed.")


def reset_pin(db: Session, user: User, wallet: Wallet, otp_code: str, new_pin: str) -> None:
    lock_wallets(db, [wallet.id])
    row = get_pin_row(db, wallet.id, lock=True)
    if row is None:
        raise HTTPException(status_code=400, detail="Transaction PIN is not set. Use the set PIN API instead.")
    _reject_simple(new_pin)
    otp_service.require_otp(db, user, OtpPurpose.PIN_RESET, otp_code)
    row = get_pin_row(db, wallet.id, lock=True)
    row.pin_hash = hash_secret(new_pin)
    row.last_changed_at = utcnow()
    row.failed_attempts = 0
    row.locked_until = None
    db.flush()
    notify(db, user, "pin_reset", "Transaction PIN reset", "Your wallet transaction PIN was reset using an OTP.")
