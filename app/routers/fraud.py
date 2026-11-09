from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import admin_only
from app.schemas.fraud import ApproveRequest, FlaggedTransactionOut, FlaggedTransactionPage, RejectRequest
from app.services import fraud_service
from app.services.events import commit_and_dispatch

router = APIRouter(prefix="/admin", tags=["Fraud Management"])


@router.get("/flagged-transactions", response_model=FlaggedTransactionPage, summary="Transactions flagged for review")
def flagged_transactions(
    review_status: Optional[str] = Query("Pending", pattern="^(Pending|Approved|Rejected)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    return fraud_service.list_flagged(db, review_status, skip, limit)


@router.put("/transactions/{transaction_ref}/approve", response_model=FlaggedTransactionOut, summary="Approve a held transaction")
def approve_transaction(
    transaction_ref: str,
    background_tasks: BackgroundTasks,
    payload: Optional[ApproveRequest] = None,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    result = fraud_service.approve_transaction(db, admin, transaction_ref, payload.reason if payload else None)
    commit_and_dispatch(db, background_tasks)
    return result


@router.put("/transactions/{transaction_ref}/reject", response_model=FlaggedTransactionOut, summary="Reject a held transaction (reason required)")
def reject_transaction(
    transaction_ref: str,
    payload: RejectRequest,
    background_tasks: BackgroundTasks,
    admin: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    result = fraud_service.reject_transaction(db, admin, transaction_ref, payload.reason)
    commit_and_dispatch(db, background_tasks)
    return result
