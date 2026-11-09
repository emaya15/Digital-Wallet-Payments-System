from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.validators import is_valid_pan


class KycSubmitRequest(BaseModel):
    kyc_type: Literal["Minimum", "Full"]
    id_proof_type: Literal["Aadhaar", "Voter ID", "Driving License", "Passport"]
    id_proof_number: str = Field(min_length=4, max_length=40)
    pan_number: Optional[str] = None
    address: Optional[str] = Field(default=None, min_length=5, max_length=500)

    @field_validator("pan_number")
    @classmethod
    def _valid_pan(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return None
        value = value.strip().upper()
        if not is_valid_pan(value):
            raise ValueError("Invalid PAN. Expected format: ABCDE1234F")
        return value

    @model_validator(mode="after")
    def _full_kyc_requirements(self):
        if self.kyc_type == "Full" and not self.pan_number:
            raise ValueError("pan_number is required for Full KYC")
        if self.kyc_type == "Full" and not self.address:
            raise ValueError("address is required for Full KYC")
        return self


class KycOut(BaseModel):
    id: int
    user_id: int
    kyc_type: str
    pan_number_masked: Optional[str] = None
    id_proof_type: str
    id_proof_number_masked: str
    address: Optional[str] = None
    status: str
    rejection_reason: Optional[str] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime


class KycStatusOut(BaseModel):
    kyc_level: str
    latest: Optional[KycOut] = None
    history: list[KycOut] = []


class KycRejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=255)
