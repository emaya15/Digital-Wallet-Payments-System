from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.deps import admin_only, merchant_only, money_user
from app.schemas.report import AdminDashboardOut, LedgerSummaryOut, MerchantSalesOut, MySpendingOut
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/admin-dashboard", response_model=AdminDashboardOut, summary="Platform dashboard (admin)")
def admin_dashboard(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    return report_service.admin_dashboard(db)


@router.get("/ledger-summary", response_model=LedgerSummaryOut, summary="Ledger totals and reconciliation (admin)")
def ledger_summary(admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    return report_service.ledger_summary(db)


@router.get("/merchant-sales", response_model=MerchantSalesOut, summary="Daily sales, refunds and fees (merchant)")
def merchant_sales(
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    merchant: User = Depends(merchant_only),
    db: Session = Depends(get_db),
):
    return report_service.merchant_sales(db, merchant, from_date, to_date)


@router.get("/my-spending", response_model=MySpendingOut, summary="Monthly spending and cashback earned")
def my_spending(
    month: Optional[str] = Query(None, description="YYYY-MM, default current month"),
    user: User = Depends(money_user),
    db: Session = Depends(get_db),
):
    return report_service.my_spending(db, user, month)
