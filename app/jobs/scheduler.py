"""APScheduler lifecycle.

Several Uvicorn workers may start this module. Only the worker that obtains the
MySQL advisory lock (`GET_LOCK`) starts the scheduler, so jobs never run twice.
A keep-alive job re-checks the lock; if it is ever lost the scheduler pauses.
On top of that every financial job is itself idempotent (row locks with
SKIP LOCKED and status transitions), so a duplicate run could not double-pay.
"""
import logging
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from app.database import SessionLocal, engine
from app.jobs import tasks

logger = logging.getLogger(__name__)

LOCK_NAME = "digital_wallet_scheduler"

_scheduler: Optional[BackgroundScheduler] = None
_lock_connection = None


def _with_session(task: Callable) -> Callable:
    def runner() -> None:
        db = SessionLocal()
        try:
            task(db)
        except Exception:
            logger.exception("Scheduled job %s failed", getattr(task, "__name__", task))
            db.rollback()
        finally:
            db.close()

    runner.__name__ = getattr(task, "__name__", "job")
    return runner


def _acquire_lock() -> bool:
    """Try to become the single scheduler owner across all workers."""
    global _lock_connection
    try:
        connection = engine.connect()
        got = connection.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": LOCK_NAME}).scalar()
        connection.commit()
    except Exception:
        logger.exception("Could not acquire the scheduler advisory lock")
        return False
    if got == 1:
        _lock_connection = connection
        return True
    connection.close()
    return False


def _keepalive() -> None:
    """Make sure we still own the lock; pause jobs if not, resume when re-acquired."""
    global _lock_connection
    if _scheduler is None:
        return
    try:
        owned = _lock_connection is not None and bool(
            _lock_connection.execute(text("SELECT IS_USED_LOCK(:n) = CONNECTION_ID()"), {"n": LOCK_NAME}).scalar()
        )
        _lock_connection.commit() if _lock_connection is not None else None
    except Exception:
        owned = False
        _lock_connection = None
    if not owned:
        _lock_connection = None
        if _acquire_lock():
            _scheduler.resume()
        else:
            logger.warning("Scheduler lock lost to another worker; pausing jobs in this worker")
            _scheduler.pause()


def start_scheduler() -> bool:
    """Start the scheduler in this process if it wins the lock. Returns True when started."""
    global _scheduler
    if _scheduler is not None:
        return True
    if not _acquire_lock():
        logger.info("Another worker owns the scheduler; not starting it here")
        return False
    scheduler = BackgroundScheduler(timezone="UTC")
    defaults = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 300, "replace_existing": True}
    scheduler.add_job(_with_session(tasks.cashback_job), IntervalTrigger(hours=1), id="cashback", **defaults)
    scheduler.add_job(_with_session(tasks.withdrawal_job), IntervalTrigger(minutes=5), id="withdrawals", **defaults)
    scheduler.add_job(
        _with_session(tasks.money_request_expiry_job), IntervalTrigger(hours=1), id="money_request_expiry", **defaults
    )
    scheduler.add_job(_with_session(tasks.otp_cleanup_job), CronTrigger(hour=2, minute=0), id="otp_cleanup", **defaults)
    scheduler.add_job(
        _with_session(tasks.idempotency_cleanup_job), CronTrigger(hour=2, minute=30), id="idempotency_cleanup", **defaults
    )
    scheduler.add_job(
        _with_session(tasks.ledger_reconciliation_job), CronTrigger(hour=3, minute=0), id="ledger_reconciliation", **defaults
    )
    scheduler.add_job(
        _with_session(tasks.scheduled_payments_job), IntervalTrigger(minutes=1), id="scheduled_payments", **defaults
    )
    scheduler.add_job(_keepalive, IntervalTrigger(minutes=5), id="lock_keepalive", **defaults)
    scheduler.start()
    _scheduler = scheduler
    logger.info("APScheduler started with %s jobs", len(scheduler.get_jobs()))
    return True


def shutdown_scheduler() -> None:
    global _scheduler, _lock_connection
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    if _lock_connection is not None:
        try:
            _lock_connection.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": LOCK_NAME})
            _lock_connection.commit()
        except Exception:
            pass
        finally:
            _lock_connection.close()
            _lock_connection = None


def job_ids() -> list:
    return [job.id for job in _scheduler.get_jobs()] if _scheduler else []
