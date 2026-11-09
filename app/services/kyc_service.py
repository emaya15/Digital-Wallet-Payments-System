"""KYC submission and admin review."""
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import KYC_RANK, KycLevel, KycStatus
from app.models.kyc import KYC
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.kyc import KycOut, KycStatusOut, KycSubmitRequest
from app.services.events import notify
from app.services.wallet_service import get_wallet_for_user, lock_wallets
from app.utils.time import utcnow
from app.utils.validators import mask_pan


def _mask_proof(value: str) -> str:
    return ("X" * max(len(value) - 4, 0)) + value[-4:]


def kyc_out(record: KYC) -> KycOut:
    return KycOut(
        id=record.id,
        user_id=record.user_id,
        kyc_type=record.kyc_type,
        pan_number_masked=mask_pan(record.pan_number) if record.pan_number else None,
        id_proof_type=record.id_proof_type,
        id_proof_number_masked=_mask_proof(record.id_proof_number),
        address=record.address,
        status=record.status,
        rejection_reason=record.rejection_reason,
        reviewed_by=record.reviewed_by,
        reviewed_at=record.reviewed_at,
        created_at=record.created_at,
    )


def submit_kyc(db: Session, user: User, payload: KycSubmitRequest) -> KYC:
    wallet = get_wallet_for_user(db, user.id)
    lock_wallets(db, [wallet.id])  # serialises concurrent submissions for the same user
    records = db.execute(select(KYC).where(KYC.user_id == user.id)).scalars().all()
    if any(r.status == KycStatus.PENDING for r in records):
        raise HTTPException(status_code=409, detail="A KYC request is already pending review")
    current_rank = KYC_RANK[wallet.kyc_level]
    if KYC_RANK[payload.kyc_type] <= current_rank:
        raise HTTPException(
            status_code=409,
            detail=f"Your wallet already has {wallet.kyc_level} KYC. Submit a higher level to upgrade.",
        )
    if payload.pan_number:
        clash = db.execute(
            select(KYC.id).where(
                KYC.pan_number == payload.pan_number,
                KYC.user_id != user.id,
                KYC.status.in_([KycStatus.PENDING, KycStatus.APPROVED]),
            )
        ).first()
        if clash:
            raise HTTPException(status_code=409, detail="This PAN is already linked to another account")
    record = KYC(
        user_id=user.id,
        kyc_type=payload.kyc_type,
        pan_number=payload.pan_number,
        id_proof_type=payload.id_proof_type,
        id_proof_number=payload.id_proof_number,
        address=payload.address,
        status=KycStatus.PENDING,
    )
    db.add(record)
    db.flush()
    return record


def get_kyc_status(db: Session, user: User) -> KycStatusOut:
    wallet = get_wallet_for_user(db, user.id)
    records = db.execute(select(KYC).where(KYC.user_id == user.id).order_by(KYC.id.desc())).scalars().all()
    outs = [kyc_out(r) for r in records]
    return KycStatusOut(kyc_level=wallet.kyc_level, latest=outs[0] if outs else None, history=outs)


def list_kyc(db: Session, status: Optional[str], skip: int, limit: int) -> List[KycOut]:
    stmt = select(KYC).order_by(KYC.id.desc()).offset(skip).limit(limit)
    if status:
        stmt = stmt.where(KYC.status == status)
    return [kyc_out(r) for r in db.execute(stmt).scalars().all()]


def _locked_pending(db: Session, kyc_id: int) -> KYC:
    record = db.execute(
        select(KYC).where(KYC.id == kyc_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="KYC record not found")
    if record.status != KycStatus.PENDING:
        raise HTTPException(status_code=409, detail=f"KYC request is already {record.status}")
    return record


def approve_kyc(db: Session, admin: User, kyc_id: int) -> KYC:
    record = _locked_pending(db, kyc_id)
    wallet = get_wallet_for_user(db, record.user_id)
    lock_wallets(db, [wallet.id])
    if KYC_RANK[record.kyc_type] > KYC_RANK[wallet.kyc_level]:
        wallet.kyc_level = record.kyc_type
    record.status = KycStatus.APPROVED
    record.reviewed_by = admin.id
    record.reviewed_at = utcnow()
    record.rejection_reason = None
    owner = db.get(User, record.user_id)
    db.flush()
    notify(
        db,
        owner,
        "kyc_approved",
        "KYC approved",
        f"Your {record.kyc_type} KYC has been approved. Your wallet limits have been upgraded.",
    )
    return record


def reject_kyc(db: Session, admin: User, kyc_id: int, reason: str) -> KYC:
    record = _locked_pending(db, kyc_id)
    record.status = KycStatus.REJECTED
    record.rejection_reason = reason
    record.reviewed_by = admin.id
    record.reviewed_at = utcnow()
    owner = db.get(User, record.user_id)
    db.flush()
    notify(db, owner, "kyc_rejected", "KYC rejected", f"Your {record.kyc_type} KYC was rejected: {reason}")
    return record


__all__ = ["submit_kyc", "get_kyc_status", "approve_kyc", "reject_kyc", "list_kyc", "kyc_out", "KycLevel"]
