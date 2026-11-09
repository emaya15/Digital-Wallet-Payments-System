from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import money_user
from app.schemas.common import Message
from app.schemas.pin import ChangePinRequest, ResetPinRequest, SetPinRequest
from app.services import pin_service
from app.services.events import commit_and_dispatch
from app.services.wallet_service import get_wallet_for_user

router = APIRouter(prefix="/wallet/pin", tags=["Transaction PIN"])


@router.post("", response_model=Message, status_code=201, summary="Set the four digit transaction PIN")
def set_pin(payload: SetPinRequest, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    wallet = get_wallet_for_user(db, user.id)
    pin_service.set_pin(db, user, wallet, payload.pin, payload.confirm_pin)
    commit_and_dispatch(db, background_tasks)
    return Message(message="Transaction PIN set successfully")


@router.put("/change", response_model=Message, summary="Change the PIN (old PIN required)")
def change_pin(payload: ChangePinRequest, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    wallet = get_wallet_for_user(db, user.id)
    pin_service.change_pin(db, user, wallet, payload.old_pin, payload.new_pin)
    commit_and_dispatch(db, background_tasks)
    return Message(message="Transaction PIN changed successfully")


@router.post("/reset", response_model=Message, summary="Reset a forgotten PIN using an OTP (purpose: pin_reset)")
def reset_pin(payload: ResetPinRequest, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    wallet = get_wallet_for_user(db, user.id)
    pin_service.reset_pin(db, user, wallet, payload.otp_code, payload.new_pin)
    commit_and_dispatch(db, background_tasks)
    return Message(message="Transaction PIN reset successfully")
