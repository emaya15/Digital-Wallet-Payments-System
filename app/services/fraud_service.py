"""Admin review of transfers placed On Hold."""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import AccountType, TxnStatus, TxnType
from app.models.fraud import FraudReview
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.fraud import FlaggedTransactionOut, FlaggedTransactionPage
from app.services.events import notify
from app.services.ledger_service import credit, debit, post_entries, system_account, wallet_account
from app.services.serializers import load_parties
from app.services.wallet_service import enforce_balance_cap, lock_wallets
from app.utils.time import utcnow


def list_flagged(db: Session, review_status: Optional[str], skip: int, limit: int) -> FlaggedTransactionPage:
    base = select(FraudReview, Transaction).join(Transaction, Transaction.id == FraudReview.transaction_id)
    if review_status:
        base = base.where(FraudReview.status == review_status)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = db.execute(base.order_by(FraudReview.id.desc()).offset(skip).limit(limit)).all()
    parties = load_parties(
        db, [w for _, t in rows for w in (t.sender_wallet_id, t.receiver_wallet_id)], include_wallet_number=True
    )
    items = [
        FlaggedTransactionOut(
            transaction_ref=txn.transaction_ref,
            type=txn.type,
            transaction_status=txn.status,
            amount=txn.amount,
            sender=parties.get(txn.sender_wallet_id),
            receiver=parties.get(txn.receiver_wallet_id),
            flag_reason=review.reason,
            review_status=review.status,
            reviewed_by=review.reviewed_by,
            decision_reason=review.decision_reason,
            decided_at=review.decided_at,
            created_at=txn.created_at,
        )
        for review, txn in rows
    ]
    return FlaggedTransactionPage(total=total, skip=skip, limit=limit, items=items)


def _locked_held_transaction(db: Session, transaction_ref: str):
    txn = db.execute(
        select(Transaction)
        .where(Transaction.transaction_ref == transaction_ref)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    review = db.execute(
        select(FraudReview)
        .where(FraudReview.transaction_id == txn.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if review is None or txn.status != TxnStatus.ON_HOLD or review.status != "Pending":
        raise HTTPException(status_code=409, detail="Transaction is not awaiting fraud review")
    return txn, review


def approve_transaction(db: Session, admin: User, transaction_ref: str, reason: Optional[str]) -> FlaggedTransactionOut:
    txn, review = _locked_held_transaction(db, transaction_ref)
    receiver_wallet = lock_wallets(db, [txn.receiver_wallet_id])[txn.receiver_wallet_id]
    if receiver_wallet.is_frozen:
        raise HTTPException(status_code=409, detail="Receiver wallet is frozen; reject the transaction instead")
    try:
        enforce_balance_cap(receiver_wallet, txn.amount, "Receiver's")
    except HTTPException as exc:
        raise HTTPException(status_code=409, detail=f"{exc.detail}; reject the transaction instead")

    hold = system_account(db, AccountType.HOLD)
    post_entries(db, txn, [debit(hold, txn.amount), credit(wallet_account(db, receiver_wallet.id), txn.amount)])
    txn.status = TxnStatus.SUCCESS
    txn.receiver_balance_after = receiver_wallet.balance
    review.status = "Approved"
    review.reviewed_by = admin.id
    review.decision_reason = reason
    review.decided_at = utcnow()
    db.flush()

    sender_user = db.get(User, _user_id_of_wallet(db, txn.sender_wallet_id))
    receiver_user = db.get(User, receiver_wallet.user_id)
    notify(
        db,
        sender_user,
        "transfer_approved",
        "Transfer approved",
        f"Your held transfer of ₹{txn.amount} ({txn.transaction_ref}) was approved and delivered.",
        ws_event="payment_approved",
        ws_data={"transaction_ref": txn.transaction_ref, "amount": str(txn.amount)},
    )
    notify(
        db,
        receiver_user,
        "money_received",
        "Money received",
        f"You received ₹{txn.amount} from {sender_user.name} ({txn.transaction_ref}).",
        ws_event="payment_received",
        ws_data={"transaction_ref": txn.transaction_ref, "amount": str(txn.amount), "balance": str(receiver_wallet.balance)},
    )
    return _flagged_out(db, review, txn)


def reject_transaction(db: Session, admin: User, transaction_ref: str, reason: str) -> FlaggedTransactionOut:
    txn, review = _locked_held_transaction(db, transaction_ref)
    sender_wallet = lock_wallets(db, [txn.sender_wallet_id])[txn.sender_wallet_id]

    # Reversals are new transactions - the original ledger rows are never touched.
    reversal = Transaction(
        type=TxnType.REVERSAL,
        status=TxnStatus.SUCCESS,
        amount=txn.amount,
        receiver_wallet_id=sender_wallet.id,
        parent_transaction_id=txn.id,
        description=f"Reversal of held transfer {txn.transaction_ref}",
    )
    db.add(reversal)
    db.flush()
    hold = system_account(db, AccountType.HOLD)
    post_entries(db, reversal, [debit(hold, txn.amount), credit(wallet_account(db, sender_wallet.id), txn.amount)])
    reversal.receiver_balance_after = sender_wallet.balance

    txn.status = TxnStatus.REJECTED
    txn.failure_reason = f"Rejected by admin: {reason}"
    review.status = "Rejected"
    review.reviewed_by = admin.id
    review.decision_reason = reason
    review.decided_at = utcnow()
    db.flush()

    sender_user = db.get(User, sender_wallet.user_id)
    notify(
        db,
        sender_user,
        "transfer_rejected",
        "Transfer rejected",
        f"Your held transfer of ₹{txn.amount} ({txn.transaction_ref}) was rejected: {reason}. The money has been returned to your wallet.",
        ws_event="payment_rejected",
        ws_data={"transaction_ref": txn.transaction_ref, "amount": str(txn.amount), "balance": str(sender_wallet.balance)},
    )
    return _flagged_out(db, review, txn)


def _user_id_of_wallet(db: Session, wallet_id: int) -> int:
    from app.models.wallet import Wallet

    return db.execute(select(Wallet.user_id).where(Wallet.id == wallet_id)).scalar_one()


def _flagged_out(db: Session, review: FraudReview, txn: Transaction) -> FlaggedTransactionOut:
    parties = load_parties(db, [txn.sender_wallet_id, txn.receiver_wallet_id], include_wallet_number=True)
    return FlaggedTransactionOut(
        transaction_ref=txn.transaction_ref,
        type=txn.type,
        transaction_status=txn.status,
        amount=txn.amount,
        sender=parties.get(txn.sender_wallet_id),
        receiver=parties.get(txn.receiver_wallet_id),
        flag_reason=review.reason,
        review_status=review.status,
        reviewed_by=review.reviewed_by,
        decision_reason=review.decision_reason,
        decided_at=review.decided_at,
        created_at=txn.created_at,
    )
