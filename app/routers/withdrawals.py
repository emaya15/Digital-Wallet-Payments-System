from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import IdempotencyKeyHeader, money_user
from app.schemas.withdrawal import WithdrawalCreate, WithdrawalPage
from app.services import idempotency, withdrawal_service

router = APIRouter(prefix="/withdrawals", tags=["Withdrawals"])


@router.post("", status_code=201, summary="Withdraw to a bank account (Idempotency-Key required)")
def create_withdrawal(
    payload: WithdrawalCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return idempotency.run_idempotent(
        db,
        user,
        "POST /withdrawals",
        idempotency_key,
        payload.model_dump(mode="json"),
        lambda: withdrawal_service.create_withdrawal(db, user, payload),
        background_tasks,
    )


@router.get("", response_model=WithdrawalPage, summary="Your withdrawals")
def list_withdrawals(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return withdrawal_service.list_withdrawals(db, user, skip, limit)
