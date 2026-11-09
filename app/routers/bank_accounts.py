from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import money_user
from app.schemas.bank_account import BankAccountCreate, BankAccountOut
from app.schemas.common import Message
from app.services import bank_account_service
from app.services.events import commit_and_dispatch

router = APIRouter(prefix="/bank-accounts", tags=["Bank Accounts"])


@router.post("", response_model=BankAccountOut, status_code=201, summary="Link a bank account (OTP purpose: bank_account)")
def add_bank_account(payload: BankAccountCreate, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    account = bank_account_service.add_bank_account(db, user, payload)
    commit_and_dispatch(db, background_tasks)
    return bank_account_service.bank_account_out(account)


@router.get("", response_model=List[BankAccountOut], summary="Linked bank accounts (masked)")
def list_bank_accounts(user: User = Depends(money_user), db: Session = Depends(get_db)):
    return bank_account_service.list_bank_accounts(db, user)


@router.delete("/{bank_account_id}", response_model=Message, summary="Remove a linked bank account")
def delete_bank_account(bank_account_id: int, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    bank_account_service.delete_bank_account(db, user, bank_account_id)
    commit_and_dispatch(db, background_tasks)
    return Message(message="Bank account removed")
