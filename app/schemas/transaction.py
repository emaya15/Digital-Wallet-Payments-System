from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import PartyOut


class LedgerEntryOut(BaseModel):
    account: str
    entry_type: str
    amount: Decimal


class TransactionOut(BaseModel):
    transaction_ref: str
    type: str
    status: str
    amount: Decimal
    fee: Decimal
    direction: Optional[str] = None  # Debit / Credit from the viewer's wallet; None for admins
    balance_after: Optional[Decimal] = None  # viewer's wallet balance after this transaction
    sender: Optional[PartyOut] = None
    receiver: Optional[PartyOut] = None
    description: Optional[str] = None
    payment_method: Optional[str] = None
    failure_reason: Optional[str] = None
    parent_transaction_ref: Optional[str] = None
    created_at: datetime
    # admin-only extras
    sender_balance_after: Optional[Decimal] = None
    receiver_balance_after: Optional[Decimal] = None
    ledger_entries: Optional[list[LedgerEntryOut]] = None
    message: Optional[str] = None


class TransactionPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[TransactionOut]
