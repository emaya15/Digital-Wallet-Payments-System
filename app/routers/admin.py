from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import admin_only
from app.schemas.kyc import KycOut, KycRejectRequest
from app.schemas.wallet import AdminWalletOut, FreezeRequest
from app.services import kyc_service, wallet_admin_service
from app.services.events import commit_and_dispatch

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/kyc", response_model=List[KycOut], summary="List KYC requests (masked documents)")
def list_kyc(
    status: Optional[str] = Query(None, pattern="^(Pending|Approved|Rejected)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return kyc_service.list_kyc(db, status, skip, limit)


@router.put("/kyc/{kyc_id}/approve", response_model=KycOut, summary="Approve a KYC request")
def approve_kyc(kyc_id: int, background_tasks: BackgroundTasks, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    record = kyc_service.approve_kyc(db, admin, kyc_id)
    commit_and_dispatch(db, background_tasks)
    return kyc_service.kyc_out(record)


@router.put("/kyc/{kyc_id}/reject", response_model=KycOut, summary="Reject a KYC request (reason required)")
def reject_kyc(
    kyc_id: int,
    payload: KycRejectRequest,
    background_tasks: BackgroundTasks,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    record = kyc_service.reject_kyc(db, admin, kyc_id, payload.reason)
    commit_and_dispatch(db, background_tasks)
    return kyc_service.kyc_out(record)


@router.get("/wallets", response_model=List[AdminWalletOut], summary="List wallets")
def list_wallets(
    frozen: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return wallet_admin_service.list_wallets(db, frozen, skip, limit)


@router.put("/wallets/{wallet_id}/freeze", response_model=AdminWalletOut, summary="Freeze a wallet (reason mandatory)")
def freeze_wallet(
    wallet_id: int,
    payload: FreezeRequest,
    background_tasks: BackgroundTasks,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    result = wallet_admin_service.freeze_wallet(db, admin, wallet_id, payload.reason)
    commit_and_dispatch(db, background_tasks)
    return result


@router.put("/wallets/{wallet_id}/unfreeze", response_model=AdminWalletOut, summary="Unfreeze a wallet")
def unfreeze_wallet(wallet_id: int, background_tasks: BackgroundTasks, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    result = wallet_admin_service.unfreeze_wallet(db, admin, wallet_id)
    commit_and_dispatch(db, background_tasks)
    return result
