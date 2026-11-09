from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin
from app.utils.time import utcnow


class LedgerImmutableError(Exception):
    """Raised when code tries to modify or delete a ledger entry."""


class LedgerAccount(TimestampMixin, Base):
    __tablename__ = "ledger_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    account_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallets.id"), unique=True, nullable=True)

    wallet: Mapped[Optional["Wallet"]] = relationship("Wallet", back_populates="ledger_account")


class LedgerEntry(Base):
    """Append-only ledger line. There is deliberately no updated_at column."""

    __tablename__ = "ledger_entries"
    __table_args__ = (Index("ix_ledger_entries_account_created", "account_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), index=True, nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("ledger_accounts.id"), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(10), nullable=False)  # Debit | Credit
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    transaction: Mapped["Transaction"] = relationship("Transaction", back_populates="ledger_entries")
    account: Mapped["LedgerAccount"] = relationship("LedgerAccount")


@event.listens_for(LedgerEntry, "before_update")
def _block_ledger_update(mapper, connection, target):
    raise LedgerImmutableError("Ledger entries are immutable and cannot be updated.")


@event.listens_for(LedgerEntry, "before_delete")
def _block_ledger_delete(mapper, connection, target):
    raise LedgerImmutableError("Ledger entries are immutable and cannot be deleted.")
