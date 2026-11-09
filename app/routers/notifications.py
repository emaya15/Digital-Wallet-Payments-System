from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationOut, NotificationPage

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationPage, summary="Your in-app notifications")
def list_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total = db.execute(select(func.count(Notification.id)).where(Notification.user_id == user.id)).scalar_one()
    rows = db.execute(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).offset(skip).limit(limit)
    ).scalars().all()
    items = [
        NotificationOut(
            id=n.id, event_type=n.event_type, title=n.title, message=n.message, is_read=n.is_read, created_at=n.created_at
        )
        for n in rows
    ]
    return NotificationPage(total=total, skip=skip, limit=limit, items=items)
