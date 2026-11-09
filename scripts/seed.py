"""Development seed data: one admin, one user and one merchant (funded, PIN set).

Usage (from the project root, after `alembic upgrade head`):
    python scripts/seed.py

Refuses to run when APP_ENV=production. The credentials printed are for local
development only.
"""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.constants import Role  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import auth_service, pin_service  # noqa: E402
from app.services.add_money_service import credit_wallet_from_bank  # noqa: E402
from app.services.ledger_service import ensure_system_accounts  # noqa: E402
from app.services.wallet_service import get_wallet_for_user  # noqa: E402

SEED_USERS = [
    dict(name="Admin User", email="admin@example.com", phone="9000000001", password="Admin@12345",
         role=Role.ADMIN, date_of_birth=date(1990, 1, 1)),
    dict(name="Asha User", email="asha@example.com", phone="9000000002", password="User@12345",
         role=Role.USER, date_of_birth=date(1998, 5, 20)),
    dict(name="Corner Store", email="store@example.com", phone="9000000003", password="Merchant@12345",
         role=Role.MERCHANT, date_of_birth=date(1985, 3, 10),
         business_name="Corner Store", business_category="Groceries"),
]
SEED_PIN = "7391"
SEED_BALANCE = Decimal("5000.00")


def main() -> None:
    if settings.is_production:
        raise SystemExit("Refusing to seed data when APP_ENV=production")
    with SessionLocal() as db:
        ensure_system_accounts(db)
        for spec in SEED_USERS:
            existing = db.execute(select(User).where(User.email == spec["email"])).scalar_one_or_none()
            if existing:
                print(f"exists : {spec['email']}")
                continue
            user = auth_service.create_user_directly(db, **spec)
            if spec["role"] != Role.ADMIN:
                wallet = get_wallet_for_user(db, user.id)
                pin_service.set_pin(db, user, wallet, SEED_PIN, SEED_PIN)
                credit_wallet_from_bank(db, user, wallet, SEED_BALANCE, "UPI", "Seed balance")
                db.commit()
            print(f"created: {spec['email']}  password={spec['password']}  role={spec['role']}")
    print(f"Transaction PIN for seeded users: {SEED_PIN}")


if __name__ == "__main__":
    main()
