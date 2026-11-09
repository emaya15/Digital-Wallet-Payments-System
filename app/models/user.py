from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(15), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    business_name: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    business_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    merchant_code: Mapped[Optional[str]] = mapped_column(String(20), unique=True, index=True, nullable=True)

    wallet: Mapped[Optional["Wallet"]] = relationship(
        "Wallet", back_populates="user", uselist=False, foreign_keys="Wallet.user_id"
    )
