from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin


class KYC(TimestampMixin, Base):
    __tablename__ = "kyc_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    kyc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    pan_number: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    id_proof_type: Mapped[str] = mapped_column(String(30), nullable=False)
    id_proof_number: Mapped[str] = mapped_column(String(40), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Pending", index=True, nullable=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
