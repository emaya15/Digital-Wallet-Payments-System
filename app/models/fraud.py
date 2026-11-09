from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin


class FraudReview(TimestampMixin, Base):
    __tablename__ = "fraud_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), unique=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    # Pending | Approved | Rejected
    status: Mapped[str] = mapped_column(String(20), default="Pending", index=True, nullable=False)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    transaction: Mapped["Transaction"] = relationship("Transaction")
