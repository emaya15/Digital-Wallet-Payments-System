from pydantic import BaseModel

from app.schemas.common import OtpStr, PinStr


class SetPinRequest(BaseModel):
    pin: PinStr
    confirm_pin: PinStr


class ChangePinRequest(BaseModel):
    old_pin: PinStr
    new_pin: PinStr


class ResetPinRequest(BaseModel):
    otp_code: OtpStr
    new_pin: PinStr
