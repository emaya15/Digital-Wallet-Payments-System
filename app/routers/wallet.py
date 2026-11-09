from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import IdempotencyKeyHeader, money_user
from app.schemas.wallet import AddMoneyRequest, WalletOut
from app.services import add_money_service, idempotency, wallet_admin_service
from app.services.wallet_service import get_wallet_for_user

router = APIRouter(prefix="/wallet", tags=["Wallet"])


@router.get("", response_model=WalletOut, summary="Wallet balance, KYC level and limits")
def get_wallet(user: User = Depends(money_user), db: Session = Depends(get_db)):
    wallet = get_wallet_for_user(db, user.id)
    return wallet_admin_service.wallet_out(db, wallet)


@router.post("/add-money", status_code=201, summary="Add money via UPI, Card or Net Banking (Idempotency-Key required)")
def add_money(
    payload: AddMoneyRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return idempotency.run_idempotent(
        db,
        user,
        "POST /wallet/add-money",
        idempotency_key,
        payload.model_dump(mode="json"),
        lambda: add_money_service.add_money(db, user, payload),
        background_tasks,
    )
