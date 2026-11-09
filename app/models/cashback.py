from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class Cashback(TimestampMixin, Base):
    __tablename__ = "cashbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_payment_id: Mapped[int] = mapped_column(
        ForeignKey("merchant_payments.id"), unique=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Pending | Credited | Cancelled
    status: Mapped[str] = mapped_column(String(20), default="Pending", index=True, nullable=False)
    credit_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    credited_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    transaction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id"), nullable=True)
