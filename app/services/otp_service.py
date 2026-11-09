"""One-time passwords: six digits, hashed at rest, 5 minute expiry, 3 attempts, single use."""
import hmac
import math
import secrets
from datetime import timedelta
from hashlib import sha256
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import OTP_MAX_ATTEMPTS, OTP_PURPOSES, OTP_RESEND_SECONDS, OTP_TTL_MINUTES
from app.models.otp import OTP
from app.models.user import User
from app.services.events import add_after_commit
from app.utils.email import send_email
from app.utils.time import utcnow


def _hash(user_id: int, purpose: str, code: str) -> str:
    message = f"{user_id}:{purpose}:{code}".encode("utf-8")
    return hmac.new(settings.jwt_secret_key.encode("utf-8"), message, sha256).hexdigest()


def send_otp(db: Session, user: User, purpose: str) -> str:
    """Create and e-mail a new OTP; returns the plain code (callers decide whether to expose it)."""
    if purpose not in OTP_PURPOSES:
        raise HTTPException(status_code=422, detail=f"Invalid OTP purpose. Allowed: {OTP_PURPOSES}")
    now = utcnow()
    latest = db.execute(
        select(OTP).where(OTP.user_id == user.id, OTP.purpose == purpose).order_by(OTP.id.desc()).limit(1)
    ).scalar_one_or_none()
    if latest is not None:
        elapsed = (now - latest.created_at).total_seconds()
        if elapsed < OTP_RESEND_SECONDS:
            wait = math.ceil(OTP_RESEND_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {wait} seconds before requesting another OTP",
                headers={"Retry-After": str(wait)},
            )
    db.execute(
        update(OTP)
        .where(OTP.user_id == user.id, OTP.purpose == purpose, OTP.status == "Active")
        .values(status="Superseded")
    )
    code = f"{secrets.randbelow(10 ** 6):06d}"
    db.add(
        OTP(
            user_id=user.id,
            purpose=purpose,
            code_hash=_hash(user.id, purpose, code),
            expires_at=now + timedelta(minutes=OTP_TTL_MINUTES),
            attempts=0,
            status="Active",
        )
    )
    db.flush()
    address = user.email
    body = f"Your Digital Wallet OTP for {purpose.replace('_', ' ')} is {code}. It is valid for {OTP_TTL_MINUTES} minutes. Do not share it with anyone."
    add_after_commit(db, lambda: send_email(address, "Your Digital Wallet OTP", body))
    return code


def check_otp(db: Session, user: User, purpose: str, code: str, consume: bool) -> OTP:
    """Validate ``code``. Failed attempts are committed immediately so they persist."""
    now = utcnow()
    otp = db.execute(
        select(OTP)
        .where(OTP.user_id == user.id, OTP.purpose == purpose, OTP.status == "Active")
        .order_by(OTP.id.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if otp is None:
        raise HTTPException(status_code=400, detail="No active OTP found. Please request a new OTP.")
    if otp.expires_at < now:
        otp.status = "Expired"
        db.commit()
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new OTP.")
    if not hmac.compare_digest(otp.code_hash, _hash(user.id, purpose, code)):
        otp.attempts += 1
        if otp.attempts >= OTP_MAX_ATTEMPTS:
            otp.status = "Locked"
            db.commit()
            raise HTTPException(status_code=423, detail="Too many incorrect attempts. This OTP is locked; request a new one.")
        remaining = OTP_MAX_ATTEMPTS - otp.attempts
        db.commit()
        raise HTTPException(status_code=400, detail=f"Invalid OTP. {remaining} attempt(s) remaining.")
    otp.verified_at = now
    if consume:
        otp.status = "Used"
        otp.used_at = now
    db.flush()
    return otp


def verify_otp(db: Session, user: User, purpose: str, code: str) -> None:
    """Standalone verification: marks the OTP verified but keeps it usable once by the action."""
    if purpose not in OTP_PURPOSES:
        raise HTTPException(status_code=422, detail=f"Invalid OTP purpose. Allowed: {OTP_PURPOSES}")
    check_otp(db, user, purpose, code, consume=False)


def require_otp(db: Session, user: User, purpose: str, code: Optional[str]) -> None:
    """Used by money / account actions: an OTP is mandatory and is consumed (single use)."""
    if not code:
        raise HTTPException(status_code=403, detail="OTP verification is required for this action")
    check_otp(db, user, purpose, code, consume=True)
