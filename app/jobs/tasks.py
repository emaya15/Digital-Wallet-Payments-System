"""Job bodies. Each takes a Session so tests can call them directly."""
import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.constants import Role
from app.models.otp import OTP
from app.models.user import User
from app.services import (
    idempotency,
    ledger_service,
    merchant_service,
    money_request_service,
    scheduled_payment_service,
    withdrawal_service,
)
from app.services.events import commit_and_dispatch, notify
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


def cashback_job(db: Session):
    credited = merchant_service.process_due_cashbacks(db)
    logger.info("cashback job: %s credited", credited)
    return credited


def withdrawal_job(db: Session):
    counts = withdrawal_service.process_pending_withdrawals(db)
    logger.info("withdrawal job: %s", counts)
    return counts


def money_request_expiry_job(db: Session):
    expired = money_request_service.expire_old_requests(db)
    logger.info("money request expiry job: %s expired", expired)
    return expired


def otp_cleanup_job(db: Session) -> int:
    cutoff = utcnow() - timedelta(hours=24)
    result = db.execute(delete(OTP).where(OTP.expires_at < cutoff))
    db.commit()
    removed = result.rowcount or 0
    logger.info("otp cleanup job: %s removed", removed)
    return removed


def idempotency_cleanup_job(db: Session) -> int:
    removed = idempotency.purge_expired(db)
    logger.info("idempotency cleanup job: %s removed", removed)
    return removed


def ledger_reconciliation_job(db: Session) -> dict:
    """Daily: wallet balance must equal ledger balance and total debits must equal credits."""
    result = ledger_service.reconcile(db)
    if result["ok"]:
        logger.info("ledger reconciliation OK (debits=credits=%s)", result["total_debits"])
        return result
    logger.error("LEDGER RECONCILIATION FAILED: %s", result)
    details = (
        f"Total debits: {result['total_debits']}, total credits: {result['total_credits']}, "
        f"balanced: {result['balanced']}. Wallet mismatches: {result['wallet_mismatches']}"
    )
    admins = db.execute(select(User).where(User.role == Role.ADMIN, User.is_active.is_(True))).scalars().all()
    for admin in admins:
        notify(db, admin, "ledger_reconciliation_error", "Ledger reconciliation error", details, ws_event="ledger_alert")
    commit_and_dispatch(db)
    return result


def scheduled_payments_job(db: Session):
    counts = scheduled_payment_service.execute_due_payments(db)
    if counts:
        logger.info("scheduled payments job: %s", counts)
    return counts
