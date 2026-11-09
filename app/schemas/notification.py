from datetime import datetime

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: int
    event_type: str
    title: str
    message: str
    is_read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[NotificationOut]
