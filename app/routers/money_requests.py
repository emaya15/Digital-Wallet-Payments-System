from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import IdempotencyKeyHeader, money_user
from app.schemas.money_request import MoneyRequestCreate, MoneyRequestOut, MoneyRequestPage, MoneyRequestPay
from app.services import idempotency, money_request_service
from app.services.events import commit_and_dispatch

router = APIRouter(prefix="/money-requests", tags=["Money Requests"])


@router.post("", response_model=MoneyRequestOut, status_code=201, summary="Request money from a phone number")
def create_request(payload: MoneyRequestCreate, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    result = money_request_service.create_request(db, user, payload)
    commit_and_dispatch(db, background_tasks)
    return result


@router.get("", response_model=MoneyRequestPage, summary="List sent / received requests")
def list_requests(
    direction: str = Query("all", pattern="^(all|sent|received)$"),
    status: Optional[str] = Query(None, pattern="^(Pending|Paid|Declined|Cancelled|Expired)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return money_request_service.list_requests(db, user, direction, status, skip, limit)


@router.put("/{request_id}/pay", summary="Pay a request (payer only, Idempotency-Key required)")
def pay_request(
    request_id: int,
    payload: MoneyRequestPay,
    background_tasks: BackgroundTasks,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    body = payload.model_dump(mode="json")
    body["request_id"] = request_id
    return idempotency.run_idempotent(
        db,
        user,
        "PUT /money-requests/pay",
        idempotency_key,
        body,
        lambda: money_request_service.pay_request(db, user, request_id, payload),
        background_tasks,
    )


@router.put("/{request_id}/decline", response_model=MoneyRequestOut, summary="Decline a request (payer only)")
def decline_request(request_id: int, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    result = money_request_service.decline_request(db, user, request_id)
    commit_and_dispatch(db, background_tasks)
    return result


@router.put("/{request_id}/cancel", response_model=MoneyRequestOut, summary="Cancel your own request (requester only)")
def cancel_request(request_id: int, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    result = money_request_service.cancel_request(db, user, request_id)
    commit_and_dispatch(db, background_tasks)
    return result
