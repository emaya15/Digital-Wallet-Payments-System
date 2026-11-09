from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.schemas.common import PhoneStr
from app.utils.validators import validate_password_strength


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: PhoneStr
    password: str = Field(min_length=8, max_length=72)
    date_of_birth: date
    role: Literal["user", "merchant", "admin"] = "user"
    business_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    business_category: Optional[str] = Field(default=None, min_length=2, max_length=100)

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value: str) -> str:
        return validate_password_strength(value)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return value.lower()

    @field_validator("date_of_birth")
    @classmethod
    def _dob_in_past(cls, value: date) -> date:
        if value >= date.today() or value.year < 1900:
            raise ValueError("date_of_birth must be a valid date in the past")
        return value

    @model_validator(mode="after")
    def _merchant_fields(self):
        if self.role == "merchant" and not (self.business_name and self.business_category):
            raise ValueError("business_name and business_category are required for merchant registration")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return value.lower()


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    phone: str
    role: str
    is_active: bool
    date_of_birth: date
    business_name: Optional[str] = None
    business_category: Optional[str] = None
    merchant_code: Optional[str] = None
    wallet_number: Optional[str] = None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
