from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator

from app.constants import MIN_WITHDRAWAL
from app.schemas.bank_account import BankAccountOut
from app.schemas.common import Amount, PinStr


class WithdrawalCreate(BaseModel):
    amount: Amount
    bank_account_id: int
    pin: PinStr

    @field_validator("amount")
    @classmethod
    def _minimum(cls, value):
        if value < MIN_WITHDRAWAL:
            raise ValueError(f"Minimum withdrawal amount is {MIN_WITHDRAWAL}")
        return value


class WithdrawalOut(BaseModel):
    id: int
    amount: Decimal
    status: str
    bank_account: BankAccountOut
    transaction_ref: Optional[str] = None
    reversal_transaction_ref: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None


class WithdrawalPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[WithdrawalOut]
