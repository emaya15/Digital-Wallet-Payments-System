from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.utils.validators import normalize_phone

# Positive money with at most two decimal places (stored as DECIMAL(12,2)).
Amount = Annotated[Decimal, Field(gt=Decimal("0"), max_digits=10, decimal_places=2)]
PinStr = Annotated[str, Field(pattern=r"^\d{4}$", description="Four digit transaction PIN")]
OtpStr = Annotated[str, Field(pattern=r"^\d{6}$", description="Six digit OTP")]
PhoneStr = Annotated[str, AfterValidator(normalize_phone)]


class Message(BaseModel):
    message: str


class PartyOut(BaseModel):
    name: str
    phone: str  # always masked
    wallet_number: str | None = None
