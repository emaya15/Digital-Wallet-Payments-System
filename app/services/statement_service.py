"""Monthly wallet statements (PDF protected with name+birth-year password, or CSV)."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import Side
from app.models.ledger import LedgerEntry
from app.models.transaction import Transaction
from app.models.user import User
from app.services.ledger_service import wallet_account
from app.services.wallet_service import get_wallet_for_user
from app.utils.statement_files import statement_password, write_statement_csv, write_statement_pdf
from app.utils.time import month_bounds, parse_month, to_local, today_local, utcnow

PASSWORD_HINT = "First four letters of your name in lower case followed by your birth year"


def _opening_balance(db: Session, account_id: int, start) -> Decimal:
    rows = db.execute(
        select(LedgerEntry.entry_type, func.coalesce(func.sum(LedgerEntry.amount), 0))
        .where(LedgerEntry.account_id == account_id, LedgerEntry.created_at < start)
        .group_by(LedgerEntry.entry_type)
    ).all()
    sums = {entry_type: Decimal(str(total)) for entry_type, total in rows}
    return sums.get(Side.CREDIT, Decimal("0")) - sums.get(Side.DEBIT, Decimal("0"))


def build_statement(db: Session, user: User, month: str, fmt: str) -> Tuple[str, str, str, Dict[str, str]]:
    """Generate the statement file under statements/ and return (path, media_type, filename, headers)."""
    try:
        year, month_number = parse_month(month)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if fmt not in ("pdf", "csv"):
        raise HTTPException(status_code=422, detail="format must be 'pdf' or 'csv'")
    today = today_local()
    if (year, month_number) > (today.year, today.month):
        raise HTTPException(status_code=400, detail="Statements cannot be generated for a future month")

    wallet = get_wallet_for_user(db, user.id)
    account = wallet_account(db, wallet.id)
    start, end = month_bounds(year, month_number)
    opening = _opening_balance(db, account.id, start)

    rows = db.execute(
        select(LedgerEntry, Transaction)
        .join(Transaction, Transaction.id == LedgerEntry.transaction_id)
        .where(LedgerEntry.account_id == account.id, LedgerEntry.created_at >= start, LedgerEntry.created_at < end)
        .order_by(LedgerEntry.id)
    ).all()

    lines: List[dict] = []
    balance = opening
    total_credits = Decimal("0.00")
    total_debits = Decimal("0.00")
    for entry, txn in rows:
        if entry.entry_type == Side.CREDIT:
            balance += entry.amount
            total_credits += entry.amount
            credit_text, debit_text = f"{entry.amount:.2f}", ""
        else:
            balance -= entry.amount
            total_debits += entry.amount
            credit_text, debit_text = "", f"{entry.amount:.2f}"
        lines.append(
            {
                "date": to_local(entry.created_at).strftime("%Y-%m-%d %H:%M"),
                "reference": txn.transaction_ref,
                "type": txn.type,
                "description": txn.description or txn.type,
                "credit": credit_text,
                "debit": debit_text,
                "balance": f"{balance:.2f}",
            }
        )
    closing = opening + total_credits - total_debits

    last_day = (end - timedelta(days=1))
    period = f"{to_local(start).strftime('%d %b %Y')} to {to_local(last_day).strftime('%d %b %Y')}"
    header = {
        "Account Holder": user.name,
        "Wallet Number": wallet.wallet_number,
        "Statement Period": period,
        "Generated On": to_local(utcnow()).strftime("%d %b %Y %H:%M IST"),
    }
    summary = {
        "Opening Balance": f"{opening:.2f}",
        "Total Credits": f"{total_credits:.2f}",
        "Total Debits": f"{total_debits:.2f}",
        "Closing Balance": f"{closing:.2f}",
    }

    directory = Path(settings.statements_dir)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"statement_{wallet.wallet_number}_{month}.{fmt}"
    path = str(directory / filename)
    headers: Dict[str, str] = {}
    if fmt == "csv":
        write_statement_csv(path, header, lines, summary)
        media_type = "text/csv"
    else:
        password = statement_password(user.name, user.date_of_birth)
        write_statement_pdf(path, password, header, lines, summary)
        media_type = "application/pdf"
        headers["X-Statement-Password-Hint"] = PASSWORD_HINT
    return path, media_type, filename, headers
