from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.constants import TRANSFER_MAX, TRANSFER_MIN
from app.schemas.common import Amount, OtpStr, PartyOut, PhoneStr, PinStr


class MoneyRequestCreate(BaseModel):
    payer_phone: PhoneStr
    amount: Amount
    note: Optional[str] = Field(default=None, max_length=200)

    @field_validator("amount")
    @classmethod
    def _amount_range(cls, value):
        if value < TRANSFER_MIN or value > TRANSFER_MAX:
            raise ValueError(f"amount must be between {TRANSFER_MIN} and {TRANSFER_MAX}")
        return value


class MoneyRequestPay(BaseModel):
    pin: PinStr
    otp_code: Optional[OtpStr] = None


class MoneyRequestOut(BaseModel):
    id: int
    direction: str  # sent | received
    requester: PartyOut
    payer: PartyOut
    amount: Decimal
    note: Optional[str] = None
    status: str
    expires_at: datetime
    transaction_ref: Optional[str] = None
    responded_at: Optional[datetime] = None
    created_at: datetime


class MoneyRequestPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[MoneyRequestOut]
