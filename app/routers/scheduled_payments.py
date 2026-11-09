from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import money_user
from app.schemas.common import Message
from app.schemas.scheduled_payment import ScheduledPaymentCreate, ScheduledPaymentOut, ScheduledPaymentUpdate
from app.services import scheduled_payment_service
from app.services.events import commit_and_dispatch

router = APIRouter(prefix="/scheduled-payments", tags=["Scheduled Payments"])


@router.post("", response_model=ScheduledPaymentOut, status_code=201, summary="Schedule a recurring monthly transfer")
def create_scheduled_payment(
    payload: ScheduledPaymentCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    result = scheduled_payment_service.create_payment(db, user, payload)
    commit_and_dispatch(db, background_tasks)
    return result


@router.get("", response_model=List[ScheduledPaymentOut], summary="Your scheduled payments")
def list_scheduled_payments(
    response: Response,
    status: Optional[str] = Query(None, pattern="^(Active|Paused|Cancelled|Completed)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    total, items = scheduled_payment_service.list_payments(db, user, skip, limit, status)
    response.headers["X-Total-Count"] = str(total)
    return items


@router.get("/{payment_id}", response_model=ScheduledPaymentOut, summary="Scheduled payment with execution history")
def get_scheduled_payment(payment_id: int, user: User = Depends(money_user), db: Session = Depends(get_db)):
    return scheduled_payment_service.get_payment(db, user, payment_id)


@router.put("/{payment_id}", response_model=ScheduledPaymentOut, summary="Update amount / end date / note, pause or resume")
def update_scheduled_payment(
    payment_id: int,
    payload: ScheduledPaymentUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    result = scheduled_payment_service.update_payment(db, user, payment_id, payload)
    commit_and_dispatch(db, background_tasks)
    return result


@router.delete("/{payment_id}", response_model=Message, summary="Cancel a scheduled payment")
def cancel_scheduled_payment(payment_id: int, background_tasks: BackgroundTasks, user: User = Depends(money_user), db: Session = Depends(get_db)):
    scheduled_payment_service.cancel_payment(db, user, payment_id)
    commit_and_dispatch(db, background_tasks)
    return Message(message="Scheduled payment cancelled")
