from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import money_user
from app.schemas.kyc import KycOut, KycStatusOut, KycSubmitRequest
from app.services import kyc_service
from app.services.events import commit_and_dispatch

router = APIRouter(prefix="/kyc", tags=["KYC"])


@router.post("", response_model=KycOut, status_code=201, summary="Submit Minimum or Full KYC")
def submit_kyc(payload: KycSubmitRequest, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    record = kyc_service.submit_kyc(db, user, payload)
    commit_and_dispatch(db, background_tasks)
    return kyc_service.kyc_out(record)


@router.get("", response_model=KycStatusOut, summary="Current KYC level and history")
def get_kyc(user: User = Depends(money_user), db: Session = Depends(get_db)):
    return kyc_service.get_kyc_status(db, user)
