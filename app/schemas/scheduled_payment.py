from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.constants import TRANSFER_MAX, TRANSFER_MIN
from app.schemas.common import Amount, OtpStr, PartyOut, PhoneStr, PinStr


class ScheduledPaymentCreate(BaseModel):
    receiver_phone: PhoneStr
    amount: Amount
    start_date: date
    end_date: Optional[date] = None
    frequency: Literal["Monthly"] = "Monthly"
    pin: PinStr
    otp_code: Optional[OtpStr] = None
    note: Optional[str] = Field(default=None, max_length=200)

    @field_validator("amount")
    @classmethod
    def _amount_range(cls, value):
        if value < TRANSFER_MIN or value > TRANSFER_MAX:
            raise ValueError(f"amount must be between {TRANSFER_MIN} and {TRANSFER_MAX}")
        return value

    @model_validator(mode="after")
    def _dates(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        return self


class ScheduledPaymentUpdate(BaseModel):
    pin: PinStr
    otp_code: Optional[OtpStr] = None
    amount: Optional[Amount] = None
    end_date: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=200)
    status: Optional[Literal["Active", "Paused"]] = None

    @field_validator("amount")
    @classmethod
    def _amount_range(cls, value):
        if value is not None and (value < TRANSFER_MIN or value > TRANSFER_MAX):
            raise ValueError(f"amount must be between {TRANSFER_MIN} and {TRANSFER_MAX}")
        return value


class ExecutionOut(BaseModel):
    id: int
    executed_at: datetime
    status: str
    transaction_ref: Optional[str] = None
    failure_reason: Optional[str] = None


class ScheduledPaymentOut(BaseModel):
    id: int
    receiver: PartyOut
    amount: Decimal
    note: Optional[str] = None
    frequency: str
    start_date: date
    end_date: Optional[date] = None
    next_run_at: Optional[datetime] = None
    status: str
    last_run_at: Optional[datetime] = None
    run_count: int
    created_at: datetime
    executions: Optional[list[ExecutionOut]] = None  # populated on the detail endpoint
