"""Mock mobile-recharge and electricity bill payments (double-entry accounted)."""
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import AccountType, TxnStatus, TxnType
from app.models.bill_payment import BillPayment
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.bill_payment import BillPaymentCreate, BillPaymentOut, BillPaymentPage
from app.services import pin_service
from app.services.events import notify
from app.services.ledger_service import credit, debit, post_entries, system_account, wallet_account
from app.services.wallet_service import enforce_limits, ensure_not_frozen, lock_wallets_for_users
from app.utils.refs import new_bill_reference

SIMULATED_FAILURE_SUFFIX = "0000"


def _out(db: Session, bills: List[BillPayment]) -> List[BillPaymentOut]:
    ids = {b.transaction_id for b in bills if b.transaction_id}
    refs: Dict[int, str] = {}
    if ids:
        refs = dict(db.execute(select(Transaction.id, Transaction.transaction_ref).where(Transaction.id.in_(ids))).all())
    return [
        BillPaymentOut(
            id=b.id,
            reference_number=b.reference_number,
            bill_type=b.bill_type,
            provider=b.provider,
            customer_identifier=b.customer_identifier,
            amount=b.amount,
            status=b.status,
            transaction_ref=refs.get(b.transaction_id),
            failure_reason=b.failure_reason,
            created_at=b.created_at,
        )
        for b in bills
    ]


def pay_bill(db: Session, user: User, payload: BillPaymentCreate) -> Tuple[dict, int]:
    wallet = lock_wallets_for_users(db, [user.id])[user.id]
    ensure_not_frozen(wallet)
    pin_service.verify_pin(db, wallet, payload.pin)
    enforce_limits(db, wallet, payload.amount)
    if wallet.balance < payload.amount:
        raise HTTPException(status_code=400, detail="Insufficient balance")

    description = f"{payload.bill_type} - {payload.provider} - {payload.customer_identifier}"
    failed = payload.customer_identifier.endswith(SIMULATED_FAILURE_SUFFIX)
    txn = Transaction(
        type=TxnType.BILL_PAYMENT,
        status=TxnStatus.FAILED if failed else TxnStatus.SUCCESS,
        amount=payload.amount,
        sender_wallet_id=wallet.id,
        description=description,
        failure_reason="Biller rejected the payment (simulated failure for identifiers ending in 0000)" if failed else None,
    )
    db.add(txn)
    db.flush()
    if failed:
        # Failed transactions never touch the ledger.
        txn.sender_balance_after = wallet.balance
    else:
        settlement = system_account(db, AccountType.BANK_SETTLEMENT)
        post_entries(db, txn, [debit(wallet_account(db, wallet.id), payload.amount), credit(settlement, payload.amount)])
        txn.sender_balance_after = wallet.balance

    bill = BillPayment(
        user_id=user.id,
        transaction_id=txn.id,
        bill_type=payload.bill_type,
        provider=payload.provider,
        customer_identifier=payload.customer_identifier,
        amount=payload.amount,
        status="Failed" if failed else "Success",
        reference_number=new_bill_reference(),
        failure_reason=txn.failure_reason,
    )
    db.add(bill)
    db.flush()
    if not failed:
        notify(
            db,
            user,
            "bill_payment",
            "Bill payment successful",
            f"{payload.bill_type} of ₹{payload.amount} for {payload.customer_identifier} ({payload.provider}) was successful. Ref {bill.reference_number}.",
            ws_event="payment_sent",
            ws_data={"transaction_ref": txn.transaction_ref, "amount": str(payload.amount), "balance": str(wallet.balance)},
        )
    return _out(db, [bill])[0].model_dump(mode="json"), (200 if failed else 201)


def list_bills(db: Session, user: User, skip: int, limit: int) -> BillPaymentPage:
    total = db.execute(select(func.count(BillPayment.id)).where(BillPayment.user_id == user.id)).scalar_one()
    rows = db.execute(
        select(BillPayment).where(BillPayment.user_id == user.id).order_by(BillPayment.id.desc()).offset(skip).limit(limit)
    ).scalars().all()
    return BillPaymentPage(total=total, skip=skip, limit=limit, items=_out(db, list(rows)))


def get_bill(db: Session, user: User, payment_id: int) -> BillPaymentOut:
    bill = db.execute(
        select(BillPayment).where(BillPayment.id == payment_id, BillPayment.user_id == user.id)
    ).scalar_one_or_none()
    if bill is None:
        raise HTTPException(status_code=404, detail="Bill payment not found")
    return _out(db, [bill])[0]


__all__ = ["pay_bill", "list_bills", "get_bill"]
