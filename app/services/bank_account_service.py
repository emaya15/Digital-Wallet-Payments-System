"""Linked bank accounts (account numbers encrypted at rest, masked in responses)."""
from typing import List

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import MAX_BANK_ACCOUNTS, OtpPurpose
from app.models.bank_account import BankAccount
from app.models.user import User
from app.models.withdrawal import Withdrawal
from app.schemas.bank_account import BankAccountCreate, BankAccountOut
from app.services import otp_service
from app.services.wallet_service import lock_wallets_for_users
from app.utils.crypto import decrypt_value, encrypt_value
from app.utils.time import utcnow
from app.utils.validators import mask_account_number


def bank_account_out(account: BankAccount) -> BankAccountOut:
    return BankAccountOut(
        id=account.id,
        account_holder_name=account.account_holder_name,
        bank_name=account.bank_name,
        account_number_masked=mask_account_number(account.account_last4),
        ifsc=account.ifsc,
        is_primary=account.is_primary,
        created_at=account.created_at,
    )


def _active_accounts(db: Session, user_id: int) -> List[BankAccount]:
    return list(
        db.execute(
            select(BankAccount)
            .where(BankAccount.user_id == user_id, BankAccount.is_active.is_(True))
            .order_by(BankAccount.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        .scalars()
        .all()
    )


def add_bank_account(db: Session, user: User, payload: BankAccountCreate) -> BankAccount:
    lock_wallets_for_users(db, [user.id])  # serialises concurrent additions for the same user
    accounts = _active_accounts(db, user.id)
    if len(accounts) >= MAX_BANK_ACCOUNTS:
        raise HTTPException(status_code=400, detail=f"You can link at most {MAX_BANK_ACCOUNTS} bank accounts")
    for existing in accounts:
        if decrypt_value(existing.account_number_encrypted) == payload.account_number:
            raise HTTPException(status_code=409, detail="This bank account is already linked")
    otp_service.require_otp(db, user, OtpPurpose.BANK_ACCOUNT, payload.otp_code)

    make_primary = payload.is_primary or not accounts
    if make_primary:
        for existing in accounts:
            existing.is_primary = False
    account = BankAccount(
        user_id=user.id,
        account_holder_name=payload.account_holder_name.strip(),
        bank_name=payload.bank_name.strip(),
        account_number_encrypted=encrypt_value(payload.account_number),
        account_last4=payload.account_number[-4:],
        ifsc=payload.ifsc,
        is_primary=make_primary,
        is_active=True,
    )
    db.add(account)
    db.flush()
    return account


def list_bank_accounts(db: Session, user: User) -> List[BankAccountOut]:
    accounts = db.execute(
        select(BankAccount)
        .where(BankAccount.user_id == user.id, BankAccount.is_active.is_(True))
        .order_by(BankAccount.is_primary.desc(), BankAccount.id)
    ).scalars().all()
    return [bank_account_out(a) for a in accounts]


def delete_bank_account(db: Session, user: User, bank_account_id: int) -> None:
    lock_wallets_for_users(db, [user.id])
    accounts = _active_accounts(db, user.id)
    target = next((a for a in accounts if a.id == bank_account_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="Bank account not found")
    pending = db.execute(
        select(Withdrawal.id).where(Withdrawal.bank_account_id == target.id, Withdrawal.status == "Pending")
    ).first()
    if pending:
        raise HTTPException(status_code=409, detail="This bank account has pending withdrawals and cannot be removed yet")
    target.is_active = False
    target.is_primary = False
    target.deleted_at = utcnow()
    remaining = [a for a in accounts if a.id != target.id]
    if target.is_primary or not any(a.is_primary for a in remaining):
        if remaining:
            remaining[0].is_primary = True
    db.flush()
