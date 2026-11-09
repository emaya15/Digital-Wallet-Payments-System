"""Dashboards and reports."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import OUTGOING_LIMIT_TYPES, SYSTEM_ACCOUNT_TYPES, TxnStatus, TxnType
from app.models.cashback import Cashback
from app.models.merchant_payment import MerchantPayment
from app.models.refund import Refund
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.report import (
    AdminDashboardOut,
    DailySales,
    LedgerSummaryOut,
    MerchantSalesOut,
    MySpendingOut,
    SpendingByType,
    SystemAccountBalance,
    WalletMismatch,
)
from app.services import ledger_service
from app.services.wallet_service import get_wallet_for_user
from app.utils.time import local_date_start_utc, local_day_bounds, month_bounds, parse_month, to_local, today_local

ZERO = Decimal("0.00")


def _dec(value) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def admin_dashboard(db: Session) -> AdminDashboardOut:
    today = today_local()
    day_start, day_end = local_day_bounds(today)
    total_in_wallets = _dec(db.execute(select(func.coalesce(func.sum(Wallet.balance), 0))).scalar_one())
    count_today, volume_today = db.execute(
        select(func.count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.created_at >= day_start,
            Transaction.created_at < day_end,
            Transaction.status == TxnStatus.SUCCESS,
        )
    ).one()
    failed_today = db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.status == TxnStatus.FAILED, Transaction.created_at >= day_start, Transaction.created_at < day_end
        )
    ).scalar_one()
    failed_total = db.execute(select(func.count(Transaction.id)).where(Transaction.status == TxnStatus.FAILED)).scalar_one()
    on_hold = db.execute(select(func.count(Transaction.id)).where(Transaction.status == TxnStatus.ON_HOLD)).scalar_one()
    cashback_paid = _dec(
        db.execute(select(func.coalesce(func.sum(Cashback.amount), 0)).where(Cashback.status == "Credited")).scalar_one()
    )
    summaries = ledger_service.account_summaries(db)
    system = [
        SystemAccountBalance(**s) for s in summaries if s["account_type"] in SYSTEM_ACCOUNT_TYPES
    ]
    total_debits = sum((s["total_debits"] for s in summaries), ZERO)
    total_credits = sum((s["total_credits"] for s in summaries), ZERO)
    return AdminDashboardOut(
        report_date=today,
        total_money_in_wallets=total_in_wallets,
        todays_transaction_count=count_today,
        todays_transaction_volume=_dec(volume_today),
        failed_transactions_today=failed_today,
        failed_transactions_total=failed_total,
        on_hold_transactions=on_hold,
        cashback_paid_total=cashback_paid,
        system_accounts=system,
        total_ledger_debits=total_debits,
        total_ledger_credits=total_credits,
        ledger_balanced=total_debits == total_credits,
    )


def ledger_summary(db: Session) -> LedgerSummaryOut:
    result = ledger_service.reconcile(db)
    return LedgerSummaryOut(
        accounts=[SystemAccountBalance(**s) for s in ledger_service.account_summaries(db)],
        total_debits=result["total_debits"],
        total_credits=result["total_credits"],
        balanced=result["balanced"],
        wallet_mismatches=[WalletMismatch(**m) for m in result["wallet_mismatches"]],
        reconciled=result["ok"],
    )


def merchant_sales(db: Session, merchant: User, from_date: Optional[date], to_date: Optional[date]) -> MerchantSalesOut:
    today = today_local()
    to_date = to_date or today
    from_date = from_date or (to_date - timedelta(days=29))
    if from_date > to_date:
        raise HTTPException(status_code=422, detail="from_date cannot be after to_date")
    start = local_date_start_utc(from_date)
    end = local_date_start_utc(to_date + timedelta(days=1))

    rows = db.execute(
        select(MerchantPayment, Transaction.status)
        .join(Transaction, Transaction.id == MerchantPayment.transaction_id)
        .where(
            MerchantPayment.merchant_user_id == merchant.id,
            MerchantPayment.created_at >= start,
            MerchantPayment.created_at < end,
            Transaction.status == TxnStatus.SUCCESS,
        )
    ).all()
    buckets = defaultdict(lambda: {"payments": 0, "gross": ZERO, "fees": ZERO, "net": ZERO})
    for payment, _status in rows:
        day = to_local(payment.created_at).date()
        bucket = buckets[day]
        bucket["payments"] += 1
        bucket["gross"] += payment.amount
        bucket["fees"] += payment.fee
        bucket["net"] += payment.net_amount
    daily = [
        DailySales(date=day, payments=b["payments"], gross_sales=b["gross"], fees=b["fees"], net_sales=b["net"])
        for day, b in sorted(buckets.items())
    ]
    refunds_total, fees_refunded = db.execute(
        select(func.coalesce(func.sum(Refund.amount), 0), func.coalesce(func.sum(Refund.fee_refunded), 0))
        .join(MerchantPayment, MerchantPayment.id == Refund.merchant_payment_id)
        .where(MerchantPayment.merchant_user_id == merchant.id, Refund.created_at >= start, Refund.created_at < end)
    ).one()
    return MerchantSalesOut(
        merchant_code=merchant.merchant_code,
        from_date=from_date,
        to_date=to_date,
        daily=daily,
        total_payments=sum(d.payments for d in daily),
        total_gross_sales=sum((d.gross_sales for d in daily), ZERO),
        total_fees=sum((d.fees for d in daily), ZERO),
        total_net_sales=sum((d.net_sales for d in daily), ZERO),
        total_refunds=_dec(refunds_total),
        fees_refunded=_dec(fees_refunded),
    )


def my_spending(db: Session, user: User, month: Optional[str]) -> MySpendingOut:
    if month:
        try:
            year, month_number = parse_month(month)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    else:
        today = today_local()
        year, month_number = today.year, today.month
    label = f"{year:04d}-{month_number:02d}"
    start, end = month_bounds(year, month_number)
    wallet = get_wallet_for_user(db, user.id)

    spent_rows = db.execute(
        select(Transaction.type, func.count(Transaction.id), func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.sender_wallet_id == wallet.id,
            Transaction.type.in_(OUTGOING_LIMIT_TYPES),
            Transaction.status.in_([TxnStatus.SUCCESS, TxnStatus.ON_HOLD, TxnStatus.PENDING]),
            Transaction.created_at >= start,
            Transaction.created_at < end,
        )
        .group_by(Transaction.type)
        .order_by(Transaction.type)
    ).all()
    by_type = [SpendingByType(type=t, count=c, total=_dec(total)) for t, c, total in spent_rows]
    cashback = _dec(
        db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.receiver_wallet_id == wallet.id,
                Transaction.type == TxnType.CASHBACK,
                Transaction.status == TxnStatus.SUCCESS,
                Transaction.created_at >= start,
                Transaction.created_at < end,
            )
        ).scalar_one()
    )
    received = _dec(
        db.execute(
            select(func.coalesce(func.sum(Transaction.amount), 0)).where(
                Transaction.receiver_wallet_id == wallet.id,
                Transaction.status == TxnStatus.SUCCESS,
                Transaction.type.notin_([TxnType.ADD_MONEY, TxnType.CASHBACK]),
                Transaction.created_at >= start,
                Transaction.created_at < end,
            )
        ).scalar_one()
    )
    return MySpendingOut(
        month=label,
        total_spent=sum((b.total for b in by_type), ZERO),
        transaction_count=sum(b.count for b in by_type),
        by_type=by_type,
        cashback_earned=cashback,
        total_received=received,
    )
