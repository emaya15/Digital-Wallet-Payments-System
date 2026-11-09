from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.common import Amount
from app.schemas.transaction import TransactionOut


class RazorpayOrderRequest(BaseModel):
    amount: Amount


class RazorpayOrderOut(BaseModel):
    razorpay_order_id: str
    amount: Decimal
    amount_paise: int
    currency: str
    key_id: str


class RazorpayConfirmRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=5, max_length=64)
    razorpay_payment_id: str = Field(min_length=5, max_length=64)
    razorpay_signature: str = Field(min_length=10, max_length=256)


class RazorpayConfirmOut(BaseModel):
    status: str
    razorpay_order_id: str
    razorpay_payment_id: str
    credited: bool
    transaction: TransactionOut | None = None
