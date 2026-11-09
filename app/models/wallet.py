from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin


class Wallet(TimestampMixin, Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True, nullable=False)
    wallet_number: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    kyc_level: Mapped[str] = mapped_column(String(20), default="None", nullable=False)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    freeze_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    frozen_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    frozen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="wallet", foreign_keys=[user_id])
    ledger_account: Mapped[Optional["LedgerAccount"]] = relationship(
        "LedgerAccount", back_populates="wallet", uselist=False
    )
