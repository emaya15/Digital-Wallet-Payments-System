"""Double-entry ledger.

Every money movement is expressed as a list of `Leg`s whose debits equal their
credits. `post_entries` writes the immutable ledger rows AND updates wallet
balances inside the caller's database transaction, so the two can never drift.

Wallet accounts are liabilities of the platform (credit = money in, debit =
money out). System accounts keep a running net (credits - debits) that is
derived from the entries, never stored.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants import SYSTEM_ACCOUNT_TYPES, Side
from app.models.ledger import LedgerAccount, LedgerEntry
from app.models.transaction import Transaction
from app.models.wallet import Wallet
from app.services.events import push_balance
from app.services.wallet_service import lock_wallets


class LedgerImbalanceError(Exception):
    """Debits and credits of a posting do not match (programming error)."""


@dataclass
class Leg:
    account: LedgerAccount
    side: str
    amount: Decimal


def debit(account: LedgerAccount, amount: Decimal) -> Leg:
    return Leg(account, Side.DEBIT, amount)


def credit(account: LedgerAccount, amount: Decimal) -> Leg:
    return Leg(account, Side.CREDIT, amount)


def ensure_system_accounts(db: Session) -> None:
    """Create the Bank Settlement / Cashback Pool / Fees / Withdrawal Clearing / Hold accounts."""
    for name in SYSTEM_ACCOUNT_TYPES:
        exists = db.execute(select(LedgerAccount.id).where(LedgerAccount.name == name)).first()
        if exists is None:
            db.add(LedgerAccount(name=name, account_type=name))
            try:
                db.commit()
            except IntegrityError:  # another worker created it first
                db.rollback()


def system_account(db: Session, name: str) -> LedgerAccount:
    account = db.execute(select(LedgerAccount).where(LedgerAccount.name == name)).scalar_one_or_none()
    if account is None:
        raise RuntimeError(f"System ledger account '{name}' is missing; run the application once or the seed script")
    return account


def wallet_account(db: Session, wallet_id: int) -> LedgerAccount:
    account = db.execute(select(LedgerAccount).where(LedgerAccount.wallet_id == wallet_id)).scalar_one_or_none()
    if account is None:
        raise RuntimeError(f"Ledger account for wallet {wallet_id} is missing")
    return account


def post_entries(db: Session, txn: Transaction, legs: List[Leg]) -> Dict[int, Wallet]:
    """Write balanced ledger rows for ``txn`` and apply them to wallet balances.

    Returns the touched wallets (by id). Raises HTTP 400 if a wallet would go
    negative, so the surrounding transaction is rolled back by the caller.
    """
    total_debit = sum((leg.amount for leg in legs if leg.side == Side.DEBIT), Decimal("0"))
    total_credit = sum((leg.amount for leg in legs if leg.side == Side.CREDIT), Decimal("0"))
    if total_debit != total_credit or total_debit <= 0:
        raise LedgerImbalanceError(f"Unbalanced posting: debits={total_debit} credits={total_credit}")
    if any(leg.amount <= 0 for leg in legs):
        raise LedgerImbalanceError("Ledger legs must have positive amounts")
    if txn.id is None:
        db.flush()

    wallet_ids = [leg.account.wallet_id for leg in legs if leg.account.wallet_id is not None]
    wallets = lock_wallets(db, wallet_ids)  # ascending id order, fresh balances

    for leg in legs:
        db.add(
            LedgerEntry(
                transaction_id=txn.id,
                account_id=leg.account.id,
                entry_type=leg.side,
                amount=leg.amount,
            )
        )
        if leg.account.wallet_id is not None:
            wallet = wallets[leg.account.wallet_id]
            delta = leg.amount if leg.side == Side.CREDIT else -leg.amount
            wallet.balance = wallet.balance + delta
            if wallet.balance < 0:
                raise HTTPException(status_code=400, detail="Insufficient balance")
    db.flush()
    for wallet in wallets.values():
        push_balance(db, wallet.user_id, wallet.balance)
    return wallets


# --------------------------------------------------------------- reporting


def _totals_by_account(db: Session) -> Dict[int, Dict[str, Decimal]]:
    rows = db.execute(
        select(LedgerEntry.account_id, LedgerEntry.entry_type, func.coalesce(func.sum(LedgerEntry.amount), 0)).group_by(
            LedgerEntry.account_id, LedgerEntry.entry_type
        )
    ).all()
    totals: Dict[int, Dict[str, Decimal]] = {}
    for account_id, entry_type, amount in rows:
        bucket = totals.setdefault(account_id, {Side.DEBIT: Decimal("0"), Side.CREDIT: Decimal("0")})
        bucket[entry_type] = Decimal(str(amount))
    return totals


def wallet_ledger_balance(db: Session, wallet_id: int) -> Decimal:
    account = wallet_account(db, wallet_id)
    rows = db.execute(
        select(LedgerEntry.entry_type, func.coalesce(func.sum(LedgerEntry.amount), 0))
        .where(LedgerEntry.account_id == account.id)
        .group_by(LedgerEntry.entry_type)
    ).all()
    sums = {entry_type: Decimal(str(total)) for entry_type, total in rows}
    return sums.get(Side.CREDIT, Decimal("0")) - sums.get(Side.DEBIT, Decimal("0"))


def reconcile(db: Session) -> dict:
    """Compare ledger and wallet balances and check global debit == credit."""
    totals = _totals_by_account(db)
    accounts = db.execute(select(LedgerAccount)).scalars().all()
    wallets = {w.id: w for w in db.execute(select(Wallet)).scalars().all()}
    mismatches = []
    grand_debit = Decimal("0")
    grand_credit = Decimal("0")
    for account in accounts:
        bucket = totals.get(account.id, {Side.DEBIT: Decimal("0"), Side.CREDIT: Decimal("0")})
        grand_debit += bucket[Side.DEBIT]
        grand_credit += bucket[Side.CREDIT]
        if account.wallet_id is not None:
            wallet = wallets.get(account.wallet_id)
            ledger_balance = bucket[Side.CREDIT] - bucket[Side.DEBIT]
            if wallet is None or wallet.balance != ledger_balance:
                mismatches.append(
                    {
                        "wallet_id": account.wallet_id,
                        "wallet_balance": str(wallet.balance if wallet else None),
                        "ledger_balance": str(ledger_balance),
                    }
                )
    return {
        "total_debits": grand_debit,
        "total_credits": grand_credit,
        "balanced": grand_debit == grand_credit,
        "wallet_mismatches": mismatches,
        "ok": grand_debit == grand_credit and not mismatches,
    }


def account_summaries(db: Session) -> List[dict]:
    """Per account-type debit / credit / net totals (System accounts and wallet groups)."""
    totals = _totals_by_account(db)
    accounts = db.execute(select(LedgerAccount)).scalars().all()
    grouped: Dict[str, Dict[str, Decimal]] = {}
    for account in accounts:
        bucket = totals.get(account.id, {Side.DEBIT: Decimal("0"), Side.CREDIT: Decimal("0")})
        group = grouped.setdefault(account.account_type, {Side.DEBIT: Decimal("0"), Side.CREDIT: Decimal("0")})
        group[Side.DEBIT] += bucket[Side.DEBIT]
        group[Side.CREDIT] += bucket[Side.CREDIT]
    return [
        {
            "account_type": account_type,
            "total_debits": values[Side.DEBIT],
            "total_credits": values[Side.CREDIT],
            "net_balance": values[Side.CREDIT] - values[Side.DEBIT],
        }
        for account_type, values in sorted(grouped.items())
    ]
