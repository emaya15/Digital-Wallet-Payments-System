from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import Amount, PinStr
from app.schemas.transaction import TransactionOut


class MerchantQrOut(BaseModel):
    merchant_code: str
    business_name: str
    qr_payload: str
    qr_png_base64: str


class MerchantPaymentRequest(BaseModel):
    merchant_code: str = Field(min_length=4, max_length=20)
    amount: Amount
    pin: PinStr
    note: Optional[str] = Field(default=None, max_length=200)

    @field_validator("merchant_code")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()


class MerchantPaymentOut(TransactionOut):
    merchant_code: Optional[str] = None
    business_name: Optional[str] = None
    net_amount: Optional[Decimal] = None
    cashback_amount: Optional[Decimal] = None
    cashback_credit_at: Optional[datetime] = None


class RefundRequest(BaseModel):
    amount: Optional[Amount] = None  # omitted = refund everything still refundable
    reason: Optional[str] = Field(default=None, max_length=200)


class RefundOut(BaseModel):
    refund_transaction_ref: str
    original_transaction_ref: str
    amount: Decimal
    fee_refunded: Decimal
    total_refunded: Decimal
    remaining_refundable: Decimal
    status: str
    created_at: datetime


class MerchantPaymentItem(BaseModel):
    transaction_ref: str
    payer_name: str
    payer_phone: str  # masked
    amount: Decimal
    fee: Decimal
    net_amount: Decimal
    refunded_amount: Decimal
    status: str
    created_at: datetime


class MerchantPaymentPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[MerchantPaymentItem]
