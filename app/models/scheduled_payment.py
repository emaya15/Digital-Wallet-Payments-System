from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin


class ScheduledPayment(TimestampMixin, Base):
    __tablename__ = "scheduled_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    receiver_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    frequency: Mapped[str] = mapped_column(String(20), default="Monthly", nullable=False)
    anchor_day: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True, nullable=True)
    # Active | Paused | Cancelled | Completed
    status: Mapped[str] = mapped_column(String(20), default="Active", index=True, nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    executions: Mapped[list["ScheduledPaymentExecution"]] = relationship(
        "ScheduledPaymentExecution",
        back_populates="scheduled_payment",
        order_by="ScheduledPaymentExecution.id.desc()",
    )


class ScheduledPaymentExecution(TimestampMixin, Base):
    __tablename__ = "scheduled_payment_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    scheduled_payment_id: Mapped[int] = mapped_column(
        ForeignKey("scheduled_payments.id"), index=True, nullable=False
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Success | On Hold | Failed
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    transaction_id: Mapped[Optional[int]] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    scheduled_payment: Mapped["ScheduledPayment"] = relationship("ScheduledPayment", back_populates="executions")
