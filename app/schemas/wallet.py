from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.constants import ADD_MONEY_MAX, ADD_MONEY_MIN
from app.schemas.common import Amount


class LimitsOut(BaseModel):
    max_balance: Decimal
    daily_limit: Decimal
    monthly_limit: Decimal
    spent_today: Decimal
    spent_this_month: Decimal
    remaining_today: Decimal
    remaining_this_month: Decimal


class WalletOut(BaseModel):
    wallet_id: int
    wallet_number: str
    balance: Decimal
    currency: str = "INR"
    kyc_level: str
    is_frozen: bool
    freeze_reason: Optional[str] = None
    pin_set: bool
    pin_locked_until: Optional[datetime] = None
    limits: LimitsOut


class AddMoneyRequest(BaseModel):
    amount: Amount
    payment_method: Literal["UPI", "Card", "Net Banking"]
    upi_id: Optional[str] = Field(default=None, max_length=100)
    card_last4: Optional[str] = Field(default=None, pattern=r"^\d{4}$")
    bank_name: Optional[str] = Field(default=None, max_length=100)
    simulate_failure: bool = Field(
        default=False, description="Development / test only: force the payment gateway to fail"
    )


class FreezeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class AdminWalletOut(BaseModel):
    wallet_id: int
    wallet_number: str
    user_id: int
    user_name: str
    user_phone: str
    role: str
    balance: Decimal
    kyc_level: str
    is_frozen: bool
    freeze_reason: Optional[str] = None
    frozen_at: Optional[datetime] = None


__all__ = [
    "LimitsOut",
    "WalletOut",
    "AddMoneyRequest",
    "FreezeRequest",
    "AdminWalletOut",
    "ADD_MONEY_MIN",
    "ADD_MONEY_MAX",
]
