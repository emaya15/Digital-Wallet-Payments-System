from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin
from app.utils.refs import new_transaction_ref


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_sender_created", "sender_wallet_id", "created_at"),
        Index("ix_transactions_receiver_created", "receiver_wallet_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_ref: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, default=new_transaction_ref, nullable=False
    )
    type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    sender_wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallets.id"), nullable=True)
    receiver_wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallets.id"), nullable=True)
    parent_transaction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sender_balance_after: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    receiver_balance_after: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)

    sender_wallet: Mapped[Optional["Wallet"]] = relationship("Wallet", foreign_keys=[sender_wallet_id])
    receiver_wallet: Mapped[Optional["Wallet"]] = relationship("Wallet", foreign_keys=[receiver_wallet_id])
    ledger_entries: Mapped[list["LedgerEntry"]] = relationship("LedgerEntry", back_populates="transaction")
