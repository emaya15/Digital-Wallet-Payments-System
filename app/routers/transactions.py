from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.transaction import TransactionOut, TransactionPage
from app.services import transaction_service

router = APIRouter(prefix="/transactions", tags=["Transaction History"])


@router.get("", response_model=TransactionPage, summary="Transaction history (users: own, admin: all)")
def list_transactions(
    type_: Optional[str] = Query(None, alias="type", description="e.g. 'P2P Transfer'"),
    status: Optional[str] = Query(None),
    min_amount: Optional[Decimal] = Query(None, ge=0),
    max_amount: Optional[Decimal] = Query(None, ge=0),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    sort_by: str = Query("date"),
    order: str = Query("desc"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return transaction_service.list_transactions(
        db,
        user,
        type_=type_,
        status=status,
        min_amount=min_amount,
        max_amount=max_amount,
        from_date=from_date,
        to_date=to_date,
        sort_by=sort_by,
        order=order,
        skip=skip,
        limit=limit,
    )


@router.get("/{transaction_ref}", response_model=TransactionOut, summary="Transaction details")
def get_transaction(transaction_ref: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return transaction_service.get_transaction(db, user, transaction_ref)
