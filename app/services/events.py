"""Post-commit side effects: e-mails and WebSocket pushes.

Services register callables with ``add_after_commit``; they only run once the
database transaction has actually committed (and are discarded on rollback).
Routers hand over ``BackgroundTasks`` so e-mails go out after the response.
"""
import logging
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.utils.email import send_email
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

_KEY = "after_commit"


def add_after_commit(db: Session, fn: Callable[[], None]) -> None:
    db.info.setdefault(_KEY, []).append(fn)


def discard_after_commit(db: Session) -> None:
    db.info.pop(_KEY, None)


def hook_count(db: Session) -> int:
    return len(db.info.get(_KEY, []))


def truncate_hooks(db: Session, count: int) -> None:
    """Drop hooks registered after the first ``count`` (used when a savepoint rolls back)."""
    hooks = db.info.get(_KEY)
    if hooks is not None:
        del hooks[count:]


def _safe(fn: Callable[[], None]) -> Callable[[], None]:
    def runner() -> None:
        try:
            fn()
        except Exception:
            logger.exception("after-commit hook failed")

    return runner


def run_after_commit(db: Session, background_tasks=None) -> None:
    hooks = db.info.pop(_KEY, [])
    for fn in hooks:
        task = _safe(fn)
        if background_tasks is not None:
            background_tasks.add_task(task)
        else:
            task()


def commit_and_dispatch(db: Session, background_tasks=None) -> None:
    db.commit()
    run_after_commit(db, background_tasks)


def notify(
    db: Session,
    user,
    event_type: str,
    title: str,
    message: str,
    *,
    ws_event: Optional[str] = None,
    ws_data: Optional[dict] = None,
    email: bool = True,
) -> None:
    """Persist an in-app notification now; e-mail / WebSocket push after commit."""
    db.add(Notification(user_id=user.id, event_type=event_type, title=title, message=message))
    user_id = user.id
    address = user.email

    def hook() -> None:
        if email and address:
            send_email(address, title, message)
        if ws_event:
            payload = {"event": ws_event, "title": title, "message": message}
            payload.update(ws_data or {})
            manager.publish(user_id, payload)

    add_after_commit(db, hook)


def push_balance(db: Session, user_id: int, balance) -> None:
    """Queue a live ``balance_update`` WebSocket message for after commit."""
    amount = str(balance)

    def hook() -> None:
        manager.publish(user_id, {"event": "balance_update", "balance": amount})

    add_after_commit(db, hook)
