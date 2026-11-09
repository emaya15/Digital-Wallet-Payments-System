from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import OtpStr
from app.utils.validators import is_valid_account_number, is_valid_ifsc


class BankAccountCreate(BaseModel):
    account_holder_name: str = Field(min_length=2, max_length=100)
    bank_name: str = Field(min_length=2, max_length=100)
    account_number: str = Field(min_length=9, max_length=18)
    ifsc: str
    is_primary: bool = False
    otp_code: OtpStr

    @field_validator("account_number")
    @classmethod
    def _account_number(cls, value: str) -> str:
        value = value.strip()
        if not is_valid_account_number(value):
            raise ValueError("Invalid account number. Expected 9 to 18 digits.")
        return value

    @field_validator("ifsc")
    @classmethod
    def _ifsc(cls, value: str) -> str:
        value = value.strip().upper()
        if not is_valid_ifsc(value):
            raise ValueError("Invalid IFSC code. Expected format: ABCD0123456")
        return value


class BankAccountOut(BaseModel):
    id: int
    account_holder_name: str
    bank_name: str
    account_number_masked: str
    ifsc: str
    is_primary: bool
    created_at: datetime
