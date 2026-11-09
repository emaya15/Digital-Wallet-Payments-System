from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import PartyOut


class FlaggedTransactionOut(BaseModel):
    transaction_ref: str
    type: str
    transaction_status: str
    amount: Decimal
    sender: Optional[PartyOut] = None
    receiver: Optional[PartyOut] = None
    flag_reason: str
    review_status: str
    reviewed_by: Optional[int] = None
    decision_reason: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: datetime


class FlaggedTransactionPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[FlaggedTransactionOut]


class ApproveRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=255)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=255)
