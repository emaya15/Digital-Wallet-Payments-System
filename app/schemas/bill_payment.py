from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, model_validator

from app.constants import ELECTRICITY_BOARDS, MOBILE_OPERATORS
from app.schemas.common import Amount, PinStr

MOBILE_RECHARGE_RANGE = (Decimal("10.00"), Decimal("3000.00"))
ELECTRICITY_RANGE = (Decimal("100.00"), Decimal("50000.00"))


class BillPaymentCreate(BaseModel):
    bill_type: Literal["Mobile Recharge", "Electricity"]
    provider: str
    customer_identifier: str
    amount: Amount
    pin: PinStr

    @model_validator(mode="after")
    def _validate_bill(self):
        ident = self.customer_identifier.strip()
        self.customer_identifier = ident
        if self.bill_type == "Mobile Recharge":
            if self.provider not in MOBILE_OPERATORS:
                raise ValueError(f"provider must be one of {MOBILE_OPERATORS}")
            if not (ident.isdigit() and len(ident) == 10 and ident[0] in "6789"):
                raise ValueError("customer_identifier must be a 10 digit mobile number")
            low, high = MOBILE_RECHARGE_RANGE
        else:
            if self.provider not in ELECTRICITY_BOARDS:
                raise ValueError(f"provider must be one of {ELECTRICITY_BOARDS}")
            if not (ident.isdigit() and 8 <= len(ident) <= 13):
                raise ValueError("customer_identifier must be an 8 to 13 digit consumer number")
            low, high = ELECTRICITY_RANGE
        if not (low <= self.amount <= high):
            raise ValueError(f"amount must be between {low} and {high} for {self.bill_type}")
        return self


class BillPaymentOut(BaseModel):
    id: int
    reference_number: str
    bill_type: str
    provider: str
    customer_identifier: str
    amount: Decimal
    status: str
    transaction_ref: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime


class BillPaymentPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[BillPaymentOut]
