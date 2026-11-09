"""Registration, login and profile."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.security import create_access_token, hash_secret, verify_secret
from app.config import settings
from app.constants import Role
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.auth import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.services import wallet_service
from app.services.events import notify
from app.utils.refs import new_merchant_code
from app.utils.time import to_local, utcnow


def user_out(db: Session, user: User) -> UserOut:
    wallet_number = db.execute(select(Wallet.wallet_number).where(Wallet.user_id == user.id)).scalar_one_or_none()
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        role=user.role,
        is_active=user.is_active,
        date_of_birth=user.date_of_birth,
        business_name=user.business_name,
        business_category=user.business_category,
        merchant_code=user.merchant_code,
        wallet_number=wallet_number,
        created_at=user.created_at,
    )


def register_user(db: Session, payload: RegisterRequest) -> User:
    if payload.role == Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin accounts cannot be registered publicly")
    if db.execute(select(User.id).where(User.email == payload.email)).first():
        raise HTTPException(status_code=409, detail="Email is already registered")
    if db.execute(select(User.id).where(User.phone == payload.phone)).first():
        raise HTTPException(status_code=409, detail="Phone number is already registered")

    user = User(
        name=payload.name.strip(),
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_secret(payload.password),
        role=payload.role,
        is_active=True,
        date_of_birth=payload.date_of_birth,
        business_name=payload.business_name if payload.role == Role.MERCHANT else None,
        business_category=payload.business_category if payload.role == Role.MERCHANT else None,
        merchant_code=new_merchant_code() if payload.role == Role.MERCHANT else None,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email or phone number is already registered")
    wallet_service.create_wallet(db, user)
    db.commit()
    return user


def create_user_directly(
    db: Session, *, name: str, email: str, phone: str, password: str, role: str, date_of_birth, business_name=None, business_category=None
) -> User:
    """Internal helper (seed script, tests) that can also create admins."""
    user = User(
        name=name,
        email=email.lower(),
        phone=phone,
        password_hash=hash_secret(password),
        role=role,
        is_active=True,
        date_of_birth=date_of_birth,
        business_name=business_name,
        business_category=business_category,
        merchant_code=new_merchant_code() if role == Role.MERCHANT else None,
    )
    db.add(user)
    db.flush()
    wallet_service.create_wallet(db, user)
    db.commit()
    return user


def login_user(db: Session, payload: LoginRequest) -> TokenOut:
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if user is None or not verify_secret(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive. Please contact support.")
    token = create_access_token(user.id, user.role)
    when = to_local(utcnow()).strftime("%d %b %Y %H:%M IST")
    notify(
        db,
        user,
        "login",
        "Successful login to your wallet",
        f"Hi {user.name}, a login to your Digital Wallet account was detected on {when}. If this was not you, contact support immediately.",
    )
    return TokenOut(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=user_out(db, user),
    )
