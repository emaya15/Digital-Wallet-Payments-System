from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.routers.deps import IdempotencyKeyHeader, money_user
from app.schemas.transaction import TransactionOut
from app.schemas.transfer import TransferRequest
from app.services import idempotency, transfer_service

router = APIRouter(prefix="/transfers", tags=["Transfers"])


@router.post("", status_code=201, summary="Send money to a phone number (Idempotency-Key required)")
def create_transfer(
    payload: TransferRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return idempotency.run_idempotent(
        db,
        user,
        "POST /transfers",
        idempotency_key,
        payload.model_dump(mode="json"),
        lambda: transfer_service.execute_p2p(db, user, payload),
        background_tasks,
    )


@router.get("/{transaction_ref}", response_model=TransactionOut, summary="Transfer details (parties and admins only)")
def get_transfer(transaction_ref: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return transfer_service.get_transfer(db, user, transaction_ref)
