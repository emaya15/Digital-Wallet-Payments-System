from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import IdempotencyKeyHeader, money_user
from app.schemas.bill_payment import BillPaymentCreate, BillPaymentOut, BillPaymentPage
from app.services import bill_payment_service, idempotency

router = APIRouter(prefix="/bill-payments", tags=["Bill Payments"])


@router.post("", status_code=201, summary="Mobile recharge / electricity bill (Idempotency-Key required)")
def create_bill_payment(
    payload: BillPaymentCreate,
    background_tasks: BackgroundTasks,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return idempotency.run_idempotent(
        db,
        user,
        "POST /bill-payments",
        idempotency_key,
        payload.model_dump(mode="json"),
        lambda: bill_payment_service.pay_bill(db, user, payload),
        background_tasks,
    )


@router.get("", response_model=BillPaymentPage, summary="Bill payment history")
def list_bill_payments(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return bill_payment_service.list_bills(db, user, skip, limit)


@router.get("/{payment_id}", response_model=BillPaymentOut, summary="Bill payment details")
def get_bill_payment(payment_id: int, user: User = Depends(money_user), db: Session = Depends(get_db)):
    return bill_payment_service.get_bill(db, user, payment_id)
