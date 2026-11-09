"""Withdrawals to bank accounts via the Withdrawal Clearing ledger account."""
import logging
from typing import Dict, List, Tuple

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import AccountType, KycLevel, Role, TxnStatus, TxnType
from app.models.bank_account import BankAccount
from app.models.transaction import Transaction
from app.models.user import User
from app.models.withdrawal import Withdrawal
from app.schemas.withdrawal import WithdrawalCreate, WithdrawalOut, WithdrawalPage
from app.services import pin_service
from app.services.bank_account_service import bank_account_out
from app.services.events import commit_and_dispatch, discard_after_commit, notify
from app.services.ledger_service import credit, debit, post_entries, system_account, wallet_account
from app.services.wallet_service import enforce_limits, ensure_not_frozen, lock_wallets, lock_wallets_for_users
from app.utils.time import utcnow
from app.utils.validators import mask_account_number

logger = logging.getLogger(__name__)

SIMULATED_FAILURE_SUFFIX = "0000"


def _out(db: Session, withdrawals: List[Withdrawal]) -> List[WithdrawalOut]:
    if not withdrawals:
        return []
    bank_ids = {w.bank_account_id for w in withdrawals}
    banks: Dict[int, BankAccount] = {
        b.id: b for b in db.execute(select(BankAccount).where(BankAccount.id.in_(bank_ids))).scalars().all()
    }
    txn_ids = {t for w in withdrawals for t in (w.transaction_id, w.reversal_transaction_id) if t}
    refs: Dict[int, str] = {}
    if txn_ids:
        refs = dict(db.execute(select(Transaction.id, Transaction.transaction_ref).where(Transaction.id.in_(txn_ids))).all())
    return [
        WithdrawalOut(
            id=w.id,
            amount=w.amount,
            status=w.status,
            bank_account=bank_account_out(banks[w.bank_account_id]),
            transaction_ref=refs.get(w.transaction_id),
            reversal_transaction_ref=refs.get(w.reversal_transaction_id),
            failure_reason=w.failure_reason,
            created_at=w.created_at,
            processed_at=w.processed_at,
        )
        for w in withdrawals
    ]


def create_withdrawal(db: Session, user: User, payload: WithdrawalCreate) -> Tuple[dict, int]:
    wallet = lock_wallets_for_users(db, [user.id])[user.id]
    ensure_not_frozen(wallet)
    if user.role == Role.USER and wallet.kyc_level != KycLevel.FULL:
        raise HTTPException(status_code=403, detail="Full KYC is required to withdraw money to a bank account")
    bank = db.get(BankAccount, payload.bank_account_id)
    if bank is None or bank.user_id != user.id or not bank.is_active:
        raise HTTPException(status_code=404, detail="Bank account not found")

    pin_service.verify_pin(db, wallet, payload.pin)
    enforce_limits(db, wallet, payload.amount)
    if wallet.balance < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    txn = Transaction(
        type=TxnType.WITHDRAWAL,
        status=TxnStatus.PENDING,
        amount=payload.amount,
        sender_wallet_id=wallet.id,
        description=f"Withdrawal to bank account {mask_account_number(bank.account_last4)}",
    )
    db.add(txn)
    db.flush()
    clearing = system_account(db, AccountType.WITHDRAWAL_CLEARING)
    post_entries(db, txn, [debit(wallet_account(db, wallet.id), payload.amount), credit(clearing, payload.amount)])
    txn.sender_balance_after = wallet.balance
    withdrawal = Withdrawal(
        user_id=user.id,
        wallet_id=wallet.id,
        bank_account_id=bank.id,
        transaction_id=txn.id,
        amount=payload.amount,
        status="Pending",
    )
    db.add(withdrawal)
    db.flush()
    notify(
        db,
        user,
        "withdrawal_requested",
        "Withdrawal requested",
        f"Your withdrawal of ₹{payload.amount} to account {mask_account_number(bank.account_last4)} is being processed.",
        ws_event="withdrawal_update",
        ws_data={"withdrawal_id": withdrawal.id, "status": "Pending", "amount": str(payload.amount), "balance": str(wallet.balance)},
        email=False,
    )
    return _out(db, [withdrawal])[0].model_dump(mode="json"), 201


def list_withdrawals(db: Session, user: User, skip: int, limit: int) -> WithdrawalPage:
    total = db.execute(select(func.count(Withdrawal.id)).where(Withdrawal.user_id == user.id)).scalar_one()
    rows = db.execute(
        select(Withdrawal).where(Withdrawal.user_id == user.id).order_by(Withdrawal.id.desc()).offset(skip).limit(limit)
    ).scalars().all()
    return WithdrawalPage(total=total, skip=skip, limit=limit, items=_out(db, list(rows)))


def _process_one(db: Session, withdrawal_id: int) -> str:
    withdrawal = db.execute(
        select(Withdrawal)
        .where(Withdrawal.id == withdrawal_id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if withdrawal is None or withdrawal.status != "Pending":
        return "skipped"
    bank = db.get(BankAccount, withdrawal.bank_account_id)
    txn = db.execute(
        select(Transaction)
        .where(Transaction.id == withdrawal.transaction_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    wallet = lock_wallets(db, [withdrawal.wallet_id])[withdrawal.wallet_id]
    owner = db.get(User, withdrawal.user_id)
    clearing = system_account(db, AccountType.WITHDRAWAL_CLEARING)
    now = utcnow()

    if bank.account_last4 == SIMULATED_FAILURE_SUFFIX:
        reason = "Bank rejected the transfer (simulated failure for account numbers ending in 0000)"
        reversal = Transaction(
            type=TxnType.WITHDRAWAL_REVERSAL,
            status=TxnStatus.SUCCESS,
            amount=withdrawal.amount,
            receiver_wallet_id=wallet.id,
            parent_transaction_id=txn.id,
            description=f"Reversal of failed withdrawal {txn.transaction_ref}",
        )
        db.add(reversal)
        db.flush()
        post_entries(db, reversal, [debit(clearing, withdrawal.amount), credit(wallet_account(db, wallet.id), withdrawal.amount)])
        reversal.receiver_balance_after = wallet.balance
        txn.status = TxnStatus.FAILED
        txn.failure_reason = reason
        withdrawal.status = "Failed"
        withdrawal.failure_reason = reason
        withdrawal.reversal_transaction_id = reversal.id
        withdrawal.processed_at = now
        db.flush()
        notify(
            db,
            owner,
            "withdrawal_failed",
            "Withdrawal failed",
            f"Your withdrawal of ₹{withdrawal.amount} failed and the money was returned to your wallet ({reversal.transaction_ref}).",
            ws_event="withdrawal_update",
            ws_data={"withdrawal_id": withdrawal.id, "status": "Failed", "amount": str(withdrawal.amount), "balance": str(wallet.balance)},
        )
        return "failed"

    bank_settlement = system_account(db, AccountType.BANK_SETTLEMENT)
    post_entries(db, txn, [debit(clearing, withdrawal.amount), credit(bank_settlement, withdrawal.amount)])
    txn.status = TxnStatus.SUCCESS
    withdrawal.status = "Completed"
    withdrawal.processed_at = now
    db.flush()
    notify(
        db,
        owner,
        "withdrawal_completed",
        "Withdrawal completed",
        f"₹{withdrawal.amount} was sent to your bank account {mask_account_number(bank.account_last4)} ({txn.transaction_ref}).",
        ws_event="withdrawal_update",
        ws_data={"withdrawal_id": withdrawal.id, "status": "Completed", "amount": str(withdrawal.amount), "balance": str(wallet.balance)},
    )
    return "completed"


def process_pending_withdrawals(db: Session, batch: int = 200) -> Dict[str, int]:
    """Five-minute job: settle Pending withdrawals (or reverse the failed ones)."""
    ids = db.execute(
        select(Withdrawal.id).where(Withdrawal.status == "Pending").order_by(Withdrawal.id).limit(batch)
    ).scalars().all()
    db.rollback()
    counts = {"completed": 0, "failed": 0, "skipped": 0}
    for withdrawal_id in ids:
        try:
            counts[_process_one(db, withdrawal_id)] += 1
            commit_and_dispatch(db)
        except Exception:
            db.rollback()
            discard_after_commit(db)
            logger.exception("Withdrawal %s could not be processed", withdrawal_id)
    return counts
