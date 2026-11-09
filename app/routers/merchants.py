from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import IdempotencyKeyHeader, merchant_only, money_user
from app.schemas.merchant import (
    MerchantPaymentPage,
    MerchantPaymentRequest,
    MerchantQrOut,
    RefundRequest,
)
from app.services import idempotency, merchant_service

router = APIRouter(tags=["Merchant"])


@router.get("/merchants/me/qr", response_model=MerchantQrOut, summary="Merchant payment QR code (PNG as base64)")
def merchant_qr(merchant: User = Depends(merchant_only)):
    return merchant_service.merchant_qr(merchant)


@router.get("/merchants/me/payments", response_model=MerchantPaymentPage, summary="Payments received by the merchant")
def merchant_payments(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    merchant: User = Depends(merchant_only),
    db: Session = Depends(get_db),
):
    return merchant_service.list_merchant_payments(db, merchant, skip, limit, from_date, to_date)


@router.post("/payments/merchant", status_code=201, summary="Pay a merchant by code (Idempotency-Key required)")
def pay_merchant(
    payload: MerchantPaymentRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: IdempotencyKeyHeader,
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return idempotency.run_idempotent(
        db,
        user,
        "POST /payments/merchant",
        idempotency_key,
        payload.model_dump(mode="json"),
        lambda: merchant_service.pay_merchant(db, user, payload),
        background_tasks,
    )


@router.post(
    "/payments/{transaction_ref}/refund",
    status_code=201,
    summary="Full or partial refund within 7 days (Idempotency-Key required)",
)
def refund_payment(
    transaction_ref: str,
    payload: RefundRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: IdempotencyKeyHeader,
    merchant: User = Depends(merchant_only),
    db: Session = Depends(get_db),
):
    body = payload.model_dump(mode="json")
    body["transaction_ref"] = transaction_ref
    return idempotency.run_idempotent(
        db,
        merchant,
        "POST /payments/refund",
        idempotency_key,
        body,
        lambda: merchant_service.refund_payment(db, merchant, transaction_ref, payload),
        background_tasks,
    )
