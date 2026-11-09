"""Digital Wallet & Payments backend - application entry point."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.config import DEFAULT_JWT_SECRET, settings
from app.database import SessionLocal
from app.jobs.scheduler import shutdown_scheduler, start_scheduler
from app.routers import (
    admin,
    auth,
    bank_accounts,
    bill_payments,
    fraud,
    kyc,
    merchants,
    money_requests,
    notifications,
    otp,
    pin,
    razorpay,
    reports,
    scheduled_payments,
    statements,
    transactions,
    transfers,
    wallet,
    withdrawals,
)
from app.services.ledger_service import ensure_system_accounts
from app.websocket import routes as websocket_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("digital_wallet")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_production and settings.jwt_secret_key == DEFAULT_JWT_SECRET:
        raise RuntimeError("JWT_SECRET_KEY must be set to a strong secret when APP_ENV=production")
    try:
        with SessionLocal() as db:
            ensure_system_accounts(db)
    except Exception:
        logger.exception("Could not create system ledger accounts. Have the Alembic migrations been applied? (alembic upgrade head)")
    if settings.scheduler_enabled:
        start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="Digital Wallet & Payments API",
    description=(
        "Paytm / PhonePe style wallet backend: double-entry ledger, KYC limits, PIN + OTP security, "
        "idempotent money movement, merchant payments, withdrawals, fraud review and live WebSocket updates."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

for module in (
    auth,
    wallet,
    pin,
    otp,
    kyc,
    admin,
    transfers,
    merchants,
    money_requests,
    bank_accounts,
    withdrawals,
    fraud,
    transactions,
    statements,
    reports,
    scheduled_payments,
    bill_payments,
    razorpay,
    notifications,
):
    app.include_router(module.router)
app.include_router(websocket_routes.router)


@app.get("/checkout", include_in_schema=False)
def checkout_page():
    """Small Razorpay test checkout page (log in, pay, confirm) served from the same origin as the API."""
    return FileResponse(Path(__file__).parent / "static" / "checkout.html")


@app.get("/health", tags=["Health"], summary="Liveness probe")
def health():
    return {"status": "ok", "environment": settings.app_env}
