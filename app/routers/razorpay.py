from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import IdempotencyKeyHeader, money_user
from app.schemas.razorpay import RazorpayConfirmRequest, RazorpayOrderOut, RazorpayOrderRequest
from app.services import idempotency, razorpay_service
from app.services.events import commit_and_dispatch

router = APIRouter(tags=["Razorpay"])


@router.post("/wallet/razorpay-order", response_model=RazorpayOrderOut, status_code=201, summary="Create a Razorpay test-mode order")
def create_order(payload: RazorpayOrderRequest, user: User = Depends(money_user), db: Session = Depends(get_db)):
    result = razorpay_service.create_order(db, user, payload)
    db.commit()
    return result


@router.post("/wallet/razorpay-confirm", status_code=201, summary="Verify the checkout signature and credit the wallet (Idempotency-Key required)")
def confirm_payment(
    payload: RazorpayConfirmRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return idempotency.run_idempotent(
        db,
        user,
        "POST /wallet/razorpay-confirm",
        idempotency_key,
        payload.model_dump(mode="json"),
        lambda: razorpay_service.confirm_payment(db, user, payload),
        background_tasks,
    )


@router.post("/webhooks/razorpay", summary="Razorpay webhook (HMAC SHA256 verified, de-duplicated by event id)")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None),
    x_razorpay_event_id: Optional[str] = Header(None),
):
    raw_body = await request.body()
    return await run_in_threadpool(
        razorpay_service.handle_webhook, raw_body, x_razorpay_signature, x_razorpay_event_id
    )


__all__ = ["router", "commit_and_dispatch"]
