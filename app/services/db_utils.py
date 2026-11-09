"""Database helpers: deadlock-safe retry."""
import random
import time
from typing import Callable, TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.services.events import discard_after_commit

T = TypeVar("T")

# MySQL: 1213 = deadlock detected, 1205 = lock wait timeout exceeded
RETRYABLE_MYSQL_CODES = {1213, 1205}


def is_retryable(exc: OperationalError) -> bool:
    args = getattr(getattr(exc, "orig", None), "args", ())
    return bool(args) and args[0] in RETRYABLE_MYSQL_CODES


def with_deadlock_retry(db: Session, fn: Callable[[], T], retries: int = 3) -> T:
    """Run ``fn``; on deadlock roll back and retry with a short random back-off."""
    attempt = 0
    while True:
        try:
            return fn()
        except OperationalError as exc:
            if not is_retryable(exc) or attempt >= retries:
                raise
            db.rollback()
            discard_after_commit(db)
            attempt += 1
            time.sleep(0.05 * attempt + random.random() * 0.05)
