from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.constants import TRANSFER_MAX, TRANSFER_MIN
from app.schemas.common import Amount, OtpStr, PhoneStr, PinStr


class TransferRequest(BaseModel):
    receiver_phone: PhoneStr
    amount: Amount
    pin: PinStr
    otp_code: Optional[OtpStr] = None
    note: Optional[str] = Field(default=None, max_length=200)

    @field_validator("amount")
    @classmethod
    def _amount_range(cls, value):
        if value < TRANSFER_MIN or value > TRANSFER_MAX:
            raise ValueError(f"amount must be between {TRANSFER_MIN} and {TRANSFER_MAX}")
        return value
