from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import OTP_RESEND_SECONDS, OTP_TTL_MINUTES
from app.database import get_db
from app.models.user import User
from app.routers.deps import money_user
from app.schemas.otp import OtpSendOut, OtpSendRequest, OtpVerifyOut, OtpVerifyRequest
from app.services import otp_service
from app.services.events import commit_and_dispatch

router = APIRouter(prefix="/otp", tags=["OTP"])


@router.post("/send", response_model=OtpSendOut, summary="Send a six digit OTP to the user's e-mail")
def send_otp(payload: OtpSendRequest, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    code = otp_service.send_otp(db, user, payload.purpose)
    commit_and_dispatch(db, background_tasks)
    return OtpSendOut(
        message="OTP sent to your registered e-mail address",
        purpose=payload.purpose,
        expires_in_seconds=OTP_TTL_MINUTES * 60,
        resend_after_seconds=OTP_RESEND_SECONDS,
        debug_otp=code if settings.expose_debug_otp else None,
    )


@router.post("/verify", response_model=OtpVerifyOut, summary="Verify an OTP (it remains single-use for the action)")
def verify_otp(payload: OtpVerifyRequest, user: User = Depends(money_user), db: Session = Depends(get_db)):
    otp_service.verify_otp(db, user, payload.purpose, payload.otp_code)
    db.commit()
    return OtpVerifyOut(verified=True, purpose=payload.purpose, message="OTP verified")
