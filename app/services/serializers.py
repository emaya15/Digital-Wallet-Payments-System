"""Builders that turn ORM rows into API schemas (with masked personal data)."""
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ledger import LedgerAccount, LedgerEntry
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.common import PartyOut
from app.schemas.transaction import LedgerEntryOut, TransactionOut
from app.utils.validators import mask_phone


def load_parties(db: Session, wallet_ids: Iterable[Optional[int]], include_wallet_number: bool = False) -> Dict[int, PartyOut]:
    ids = {wid for wid in wallet_ids if wid}
    if not ids:
        return {}
    rows = db.execute(
        select(Wallet.id, Wallet.wallet_number, User.name, User.phone)
        .join(User, User.id == Wallet.user_id)
        .where(Wallet.id.in_(ids))
    ).all()
    return {
        row.id: PartyOut(
            name=row.name,
            phone=mask_phone(row.phone),
            wallet_number=row.wallet_number if include_wallet_number else None,
        )
        for row in rows
    }


def party_for_user(user: User, wallet_number: Optional[str] = None) -> PartyOut:
    return PartyOut(name=user.name, phone=mask_phone(user.phone), wallet_number=wallet_number)


def build_transaction_outs(
    db: Session,
    txns: List[Transaction],
    viewer_wallet_id: Optional[int] = None,
    admin: bool = False,
    with_ledger: bool = False,
    message: Optional[str] = None,
) -> List[TransactionOut]:
    if not txns:
        return []
    parties = load_parties(
        db,
        [wid for t in txns for wid in (t.sender_wallet_id, t.receiver_wallet_id)],
        include_wallet_number=admin,
    )
    parent_ids = {t.parent_transaction_id for t in txns if t.parent_transaction_id}
    parent_refs: Dict[int, str] = {}
    if parent_ids:
        parent_refs = dict(
            db.execute(select(Transaction.id, Transaction.transaction_ref).where(Transaction.id.in_(parent_ids))).all()
        )
    ledger: Dict[int, List[LedgerEntryOut]] = {}
    if with_ledger:
        rows = db.execute(
            select(LedgerEntry.transaction_id, LedgerAccount.name, LedgerEntry.entry_type, LedgerEntry.amount)
            .join(LedgerAccount, LedgerAccount.id == LedgerEntry.account_id)
            .where(LedgerEntry.transaction_id.in_([t.id for t in txns]))
            .order_by(LedgerEntry.id)
        ).all()
        for txn_id, account_name, entry_type, amount in rows:
            ledger.setdefault(txn_id, []).append(LedgerEntryOut(account=account_name, entry_type=entry_type, amount=amount))

    outs: List[TransactionOut] = []
    for t in txns:
        direction = None
        balance_after = None
        if not admin and viewer_wallet_id is not None:
            if t.sender_wallet_id == viewer_wallet_id:
                direction, balance_after = "Debit", t.sender_balance_after
            elif t.receiver_wallet_id == viewer_wallet_id:
                direction, balance_after = "Credit", t.receiver_balance_after
        outs.append(
            TransactionOut(
                transaction_ref=t.transaction_ref,
                type=t.type,
                status=t.status,
                amount=t.amount,
                fee=t.fee,
                direction=direction,
                balance_after=balance_after,
                sender=parties.get(t.sender_wallet_id),
                receiver=parties.get(t.receiver_wallet_id),
                description=t.description,
                payment_method=t.payment_method,
                failure_reason=t.failure_reason,
                parent_transaction_ref=parent_refs.get(t.parent_transaction_id),
                created_at=t.created_at,
                sender_balance_after=t.sender_balance_after if admin else None,
                receiver_balance_after=t.receiver_balance_after if admin else None,
                ledger_entries=ledger.get(t.id, []) if with_ledger else None,
                message=message,
            )
        )
    return outs


def build_transaction_out(db: Session, txn: Transaction, **kwargs) -> TransactionOut:
    return build_transaction_outs(db, [txn], **kwargs)[0]
