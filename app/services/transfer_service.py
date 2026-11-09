"""Wallet-to-wallet transfers (also used by money requests and scheduled payments)."""
from datetime import timedelta
from decimal import Decimal
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    FRAUD_AMOUNT_THRESHOLD,
    FRAUD_BURST_COUNT,
    FRAUD_BURST_WINDOW_SECONDS,
    FRAUD_CHECKED_TYPES,
    LOW_BALANCE_THRESHOLD,
    OTP_REQUIRED_ABOVE,
    AccountType,
    OtpPurpose,
    Role,
    TxnStatus,
    TxnType,
)
from app.models.fraud import FraudReview
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transfer import TransferRequest
from app.services import otp_service, pin_service
from app.services.events import notify
from app.services.ledger_service import credit, debit, post_entries, system_account, wallet_account
from app.services.serializers import build_transaction_out
from app.services.wallet_service import (
    enforce_balance_cap,
    enforce_limits,
    ensure_not_frozen,
    lock_wallets_for_users,
)
from app.utils.time import utcnow


def find_active_user_by_phone(db: Session, phone: str, label: str = "Receiver") -> User:
    user = db.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
    if user is None or user.role == Role.ADMIN:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail=f"{label} account is not active")
    return user


def fraud_reason(db: Session, sender_wallet, txn_type: str, amount: Decimal) -> Optional[str]:
    """Return a reason when the transfer must be placed On Hold for admin review."""
    if txn_type not in FRAUD_CHECKED_TYPES:
        return None
    if amount > FRAUD_AMOUNT_THRESHOLD:
        return f"Transaction amount above ₹{FRAUD_AMOUNT_THRESHOLD}"
    since = utcnow() - timedelta(seconds=FRAUD_BURST_WINDOW_SECONDS)
    recent = db.execute(
        select(func.count(Transaction.id)).where(
            Transaction.sender_wallet_id == sender_wallet.id,
            Transaction.type.in_(FRAUD_CHECKED_TYPES),
            Transaction.status.in_([TxnStatus.SUCCESS, TxnStatus.ON_HOLD]),
            Transaction.created_at >= since,
        )
    ).scalar_one()
    if recent >= FRAUD_BURST_COUNT:
        return f"More than {FRAUD_BURST_COUNT} outgoing transfers within one minute"
    return None


def perform_transfer(
    db: Session,
    sender: User,
    receiver: User,
    amount: Decimal,
    *,
    txn_type: str = TxnType.P2P,
    description: Optional[str] = None,
    pin: Optional[str] = None,
    otp_code: Optional[str] = None,
    require_pin: bool = True,
    require_otp: bool = True,
) -> Transaction:
    """Move ``amount`` from sender to receiver inside the caller's DB transaction."""
    if sender.id == receiver.id:
        raise HTTPException(status_code=400, detail="You cannot transfer money to yourself")
    if not receiver.is_active or receiver.role == Role.ADMIN:
        raise HTTPException(status_code=400, detail="Receiver account is not available")

    # Locks both wallets in ascending wallet-id order -> no lock-order deadlocks.
    wallets = lock_wallets_for_users(db, [sender.id, receiver.id])
    sender_wallet, receiver_wallet = wallets[sender.id], wallets[receiver.id]
    ensure_not_frozen(sender_wallet, "Your")
    ensure_not_frozen(receiver_wallet, "Receiver's")

    if require_pin:
        pin_service.verify_pin(db, sender_wallet, pin or "")
    enforce_limits(db, sender_wallet, amount)
    if sender_wallet.balance < amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")
    if require_otp and amount > OTP_REQUIRED_ABOVE:
        otp_service.require_otp(db, sender, OtpPurpose.TRANSFER, otp_code)

    hold_reason = fraud_reason(db, sender_wallet, txn_type, amount)
    if hold_reason is None:
        enforce_balance_cap(receiver_wallet, amount, "Receiver's")

    txn = Transaction(
        type=txn_type,
        status=TxnStatus.ON_HOLD if hold_reason else TxnStatus.SUCCESS,
        amount=amount,
        sender_wallet_id=sender_wallet.id,
        receiver_wallet_id=receiver_wallet.id,
        description=description,
    )
    db.add(txn)
    db.flush()
    sender_account = wallet_account(db, sender_wallet.id)

    if hold_reason:
        hold = system_account(db, AccountType.HOLD)
        post_entries(db, txn, [debit(sender_account, amount), credit(hold, amount)])
        txn.sender_balance_after = sender_wallet.balance
        db.add(FraudReview(transaction_id=txn.id, reason=hold_reason, status="Pending"))
        db.flush()
        notify(
            db,
            sender,
            "transfer_on_hold",
            "Transfer placed on hold",
            f"Your transfer of ₹{amount} ({txn.transaction_ref}) is on hold for review: {hold_reason}.",
            ws_event="payment_on_hold",
            ws_data={"transaction_ref": txn.transaction_ref, "amount": str(amount), "balance": str(sender_wallet.balance)},
        )
        return txn

    post_entries(db, txn, [debit(sender_account, amount), credit(wallet_account(db, receiver_wallet.id), amount)])
    txn.sender_balance_after = sender_wallet.balance
    txn.receiver_balance_after = receiver_wallet.balance
    db.flush()
    notify(
        db,
        sender,
        "money_sent",
        "Money sent",
        f"You sent ₹{amount} to {receiver.name} ({txn.transaction_ref}). Balance: ₹{sender_wallet.balance}.",
        ws_event="payment_sent",
        ws_data={"transaction_ref": txn.transaction_ref, "amount": str(amount), "balance": str(sender_wallet.balance)},
    )
    notify(
        db,
        receiver,
        "money_received",
        "Money received",
        f"You received ₹{amount} from {sender.name} ({txn.transaction_ref}). Balance: ₹{receiver_wallet.balance}.",
        ws_event="payment_received",
        ws_data={"transaction_ref": txn.transaction_ref, "amount": str(amount), "balance": str(receiver_wallet.balance)},
    )
    if sender_wallet.balance < LOW_BALANCE_THRESHOLD:
        notify(
            db,
            sender,
            "low_balance",
            "Low wallet balance",
            f"Your wallet balance is only ₹{sender_wallet.balance}. Add money to keep making payments.",
            ws_event="low_balance",
        )
    return txn


def execute_p2p(db: Session, sender: User, payload: TransferRequest) -> Tuple[dict, int]:
    receiver = find_active_user_by_phone(db, payload.receiver_phone)
    txn = perform_transfer(
        db,
        sender,
        receiver,
        payload.amount,
        txn_type=TxnType.P2P,
        description=payload.note,
        pin=payload.pin,
        otp_code=payload.otp_code,
    )
    if txn.status == TxnStatus.ON_HOLD:
        message = "Transfer placed on hold for security review"
    else:
        message = "Transfer successful"
    out = build_transaction_out(db, txn, viewer_wallet_id=txn.sender_wallet_id, message=message)
    return out.model_dump(mode="json"), 201


TRANSFER_TYPES = [TxnType.P2P, TxnType.MONEY_REQUEST_PAYMENT, TxnType.SCHEDULED_PAYMENT]


def get_transfer(db: Session, user: User, transaction_ref: str):
    from app.services.wallet_service import get_wallet_for_user

    txn = db.execute(select(Transaction).where(Transaction.transaction_ref == transaction_ref)).scalar_one_or_none()
    if txn is None or txn.type not in TRANSFER_TYPES:
        raise HTTPException(status_code=404, detail="Transfer not found")
    if user.role == Role.ADMIN:
        return build_transaction_out(db, txn, admin=True, with_ledger=True)
    wallet = get_wallet_for_user(db, user.id)
    if wallet.id not in (txn.sender_wallet_id, txn.receiver_wallet_id):
        raise HTTPException(status_code=404, detail="Transfer not found")
    if wallet.id == txn.receiver_wallet_id and txn.status in (TxnStatus.ON_HOLD, TxnStatus.REJECTED):
        raise HTTPException(status_code=404, detail="Transfer not found")
    return build_transaction_out(db, txn, viewer_wallet_id=wallet.id)
