from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.common import OtpStr

Purpose = Literal["pin_reset", "transfer", "bank_account", "scheduled_payment"]


class OtpSendRequest(BaseModel):
    purpose: Purpose


class OtpSendOut(BaseModel):
    message: str
    purpose: str
    expires_in_seconds: int
    resend_after_seconds: int
    debug_otp: Optional[str] = None  # only outside production


class OtpVerifyRequest(BaseModel):
    purpose: Purpose
    otp_code: OtpStr


class OtpVerifyOut(BaseModel):
    verified: bool
    purpose: str
    message: str
