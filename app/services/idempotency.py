"""Idempotency-Key handling for every money-moving endpoint.

Flow
----
1. Look up (user, key). Expired (>24h) records are discarded.
2. Existing record:
   * different endpoint / body hash   -> 422
   * still ``Processing``              -> 409
   * ``Completed``                     -> replay stored response + ``Idempotent-Replayed: true``
3. New key: insert a ``Processing`` row and commit it (so concurrent duplicates
   see it), then run the handler. The handler only *flushes*; this wrapper stores
   the response on the idempotency row and commits business data and response
   atomically.
4. Business errors (HTTPException) release the key so the client can retry.
"""
import hashlib
import json
from datetime import timedelta
from typing import Callable, Tuple

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.constants import IDEMPOTENCY_TTL_HOURS
from app.models.idempotency import IdempotencyKey
from app.models.user import User
from app.services.db_utils import is_retryable, with_deadlock_retry
from app.services.events import discard_after_commit, run_after_commit
from app.utils.time import utcnow

Handler = Callable[[], Tuple[dict, int]]


def request_hash(body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _release(db: Session, record_id: int) -> None:
    """Delete a Processing key after a failed attempt so the client may retry."""
    try:
        db.rollback()
        discard_after_commit(db)
        db.execute(delete(IdempotencyKey).where(IdempotencyKey.id == record_id, IdempotencyKey.status == "Processing"))
        db.commit()
    except Exception:  # never mask the original error
        db.rollback()


def run_idempotent(
    db: Session,
    user: User,
    endpoint: str,
    key: str,
    body: dict,
    handler: Handler,
    background_tasks=None,
) -> JSONResponse:
    user_id = user.id
    digest = request_hash(body)
    now = utcnow()

    record = db.execute(
        select(IdempotencyKey)
        .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()

    if record is not None and record.created_at < now - timedelta(hours=IDEMPOTENCY_TTL_HOURS):
        db.delete(record)
        db.commit()
        record = None

    if record is not None:
        if record.endpoint != endpoint or record.request_hash != digest:
            db.rollback()
            raise HTTPException(
                status_code=422,
                detail="This Idempotency-Key was already used with a different request",
            )
        if record.status != "Completed":
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="A request with this Idempotency-Key is still being processed",
            )
        body_out, status_out = record.response_body, record.response_status
        db.rollback()
        return JSONResponse(content=body_out, status_code=status_out, headers={"Idempotent-Replayed": "true"})

    record = IdempotencyKey(key=key, user_id=user_id, endpoint=endpoint, request_hash=digest, status="Processing")
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A request with this Idempotency-Key is still being processed",
        )
    record_id = record.id

    try:
        payload, status_code = with_deadlock_retry(db, handler)
        stored = db.get(IdempotencyKey, record_id)
        stored.response_body = payload
        stored.response_status = status_code
        stored.status = "Completed"
        db.commit()
    except HTTPException:
        _release(db, record_id)
        raise
    except OperationalError as exc:
        _release(db, record_id)
        if is_retryable(exc):
            raise HTTPException(status_code=409, detail="Temporary conflict, please retry with the same Idempotency-Key")
        raise
    except Exception:
        _release(db, record_id)
        raise

    run_after_commit(db, background_tasks)
    return JSONResponse(content=payload, status_code=status_code)


def purge_expired(db: Session) -> int:
    cutoff = utcnow() - timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    result = db.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at < cutoff))
    db.commit()
    return result.rowcount or 0
