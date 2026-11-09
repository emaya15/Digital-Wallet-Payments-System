"""Add money to the wallet through the (simulated) payment gateway."""
from typing import Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.constants import ADD_MONEY_MAX, ADD_MONEY_MIN, AccountType, TxnStatus, TxnType
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.wallet import AddMoneyRequest
from app.services.events import notify
from app.services.ledger_service import credit, debit, post_entries, system_account, wallet_account
from app.services.serializers import build_transaction_out
from app.services.wallet_service import enforce_balance_cap, ensure_not_frozen, lock_wallets_for_users


def credit_wallet_from_bank(
    db: Session,
    user: User,
    wallet,
    amount,
    payment_method: str,
    description: str,
    enforce_cap: bool = True,
) -> Transaction:
    """Create a successful Add Money transaction: Bank Settlement debit, wallet credit."""
    if enforce_cap:
        enforce_balance_cap(wallet, amount)
    txn = Transaction(
        type=TxnType.ADD_MONEY,
        status=TxnStatus.SUCCESS,
        amount=amount,
        receiver_wallet_id=wallet.id,
        payment_method=payment_method,
        description=description,
    )
    db.add(txn)
    db.flush()
    bank = system_account(db, AccountType.BANK_SETTLEMENT)
    post_entries(db, txn, [debit(bank, amount), credit(wallet_account(db, wallet.id), amount)])
    txn.receiver_balance_after = wallet.balance
    db.flush()
    notify(
        db,
        user,
        "money_added",
        "Money added to wallet",
        f"₹{amount} was added to your wallet via {payment_method}. New balance: ₹{wallet.balance}.",
        ws_event="money_added",
        ws_data={"transaction_ref": txn.transaction_ref, "amount": str(amount), "balance": str(wallet.balance)},
        email=False,
    )
    return txn


def add_money(db: Session, user: User, payload: AddMoneyRequest) -> Tuple[dict, int]:
    if payload.amount < ADD_MONEY_MIN or payload.amount > ADD_MONEY_MAX:
        raise HTTPException(status_code=422, detail=f"Amount must be between ₹{ADD_MONEY_MIN} and ₹{ADD_MONEY_MAX}")
    wallet = lock_wallets_for_users(db, [user.id])[user.id]
    ensure_not_frozen(wallet)
    enforce_balance_cap(wallet, payload.amount)

    description = f"Added via {payload.payment_method}"
    if payload.simulate_failure:
        txn = Transaction(
            type=TxnType.ADD_MONEY,
            status=TxnStatus.FAILED,
            amount=payload.amount,
            receiver_wallet_id=wallet.id,
            payment_method=payload.payment_method,
            description=description,
            failure_reason="Payment declined by the payment gateway",
            receiver_balance_after=wallet.balance,
        )
        db.add(txn)
        db.flush()  # NOTE: no ledger entries are written for failed payments
        out = build_transaction_out(db, txn, viewer_wallet_id=wallet.id, message="Payment failed. No money was added.")
        return out.model_dump(mode="json"), 200

    txn = credit_wallet_from_bank(db, user, wallet, payload.amount, payload.payment_method, description, enforce_cap=False)
    out = build_transaction_out(db, txn, viewer_wallet_id=wallet.id, message="Money added successfully")
    return out.model_dump(mode="json"), 201
