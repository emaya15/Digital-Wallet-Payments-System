from decimal import Decimal

from sqlalchemy import select

from app.database import SessionLocal
from app.models.ledger import LedgerEntry
from app.services import ledger_service
from tests.integration.helpers import (
    PIN, add_money, balance, get_otp, idem, make_actor, make_admin, new_key, transfer, upgrade_kyc,
)


def assert_ledger_consistent():
    with SessionLocal() as db:
        result = ledger_service.reconcile(db)
    assert result["balanced"], result
    assert result["wallet_mismatches"] == [], result


def test_add_money(client):
    user = make_actor(client)
    response = add_money(client, user, "1000.00")
    body = response.json()
    assert body["type"] == "Add Money" and body["status"] == "Success"
    assert balance(client, user) == Decimal("1000.00")
    assert_ledger_consistent()


def test_add_money_validation_and_failure(client):
    user = make_actor(client)
    for amount in ("5.00", "50000.01", "0", "-5"):
        r = client.post("/wallet/add-money", json={"amount": amount, "payment_method": "UPI"}, headers=idem(user))
        assert r.status_code == 422, amount
    assert client.post("/wallet/add-money", json={"amount": "100", "payment_method": "Cheque"}, headers=idem(user)).status_code == 422
    # no Idempotency-Key -> 422
    assert client.post("/wallet/add-money", json={"amount": "100", "payment_method": "UPI"}, headers=user.headers).status_code == 422
    # balance cap for non-KYC users is 10000
    add_money(client, user, "9000.00")
    assert client.post("/wallet/add-money", json={"amount": "1500", "payment_method": "UPI"}, headers=idem(user)).status_code == 400
    failed = client.post("/wallet/add-money", json={"amount": "100", "payment_method": "UPI", "simulate_failure": True}, headers=idem(user))
    assert failed.status_code == 200 and failed.json()["status"] == "Failed"
    assert balance(client, user) == Decimal("9000.00")
    assert_ledger_consistent()


def test_transfer_success_and_ledger(client):
    sender = make_actor(client, balance="1000.00")
    receiver = make_actor(client)
    response = transfer(client, sender, receiver, "250.50")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "Success"
    assert balance(client, sender) == Decimal("749.50")
    assert balance(client, receiver) == Decimal("250.50")
    ref = body["transaction_ref"]
    assert client.get(f"/transfers/{ref}", headers=sender.headers).status_code == 200
    assert client.get(f"/transfers/{ref}", headers=receiver.headers).status_code == 200
    stranger = make_actor(client)
    assert client.get(f"/transfers/{ref}", headers=stranger.headers).status_code == 404
    with SessionLocal() as db:
        entries = db.execute(select(LedgerEntry)).scalars().all()
        debits = sum(e.amount for e in entries if e.entry_type == "Debit")
        credits = sum(e.amount for e in entries if e.entry_type == "Credit")
    assert debits == credits
    assert_ledger_consistent()


def test_transfer_validation_errors(client):
    sender = make_actor(client, balance="100.00")
    receiver = make_actor(client)
    assert transfer(client, sender, sender, "5.00").status_code == 400
    assert transfer(client, sender, receiver, "500.00").status_code == 400  # insufficient
    assert transfer(client, sender, receiver, "0.50").status_code == 422
    assert transfer(client, sender, receiver, "100001").status_code == 422
    ghost = client.post("/transfers", json={"receiver_phone": "9999999999", "amount": "5", "pin": PIN}, headers=idem(sender))
    assert ghost.status_code == 404
    no_pin_user = make_actor(client, pin=False, balance="100.00")
    assert transfer(client, no_pin_user, receiver, "5.00").status_code == 400
    assert balance(client, sender) == Decimal("100.00")


def test_otp_required_above_5000_and_daily_limit(client):
    admin = make_admin(client)
    sender = make_actor(client, balance="9000.00")
    receiver = make_actor(client)
    upgrade_kyc(client, admin, sender, "Minimum")
    upgrade_kyc(client, admin, receiver, "Minimum")  # receiver without KYC could not hold more than 10000
    add_money(client, sender, "20000.00")
    assert transfer(client, sender, receiver, "6000.00").status_code == 403  # OTP missing
    otp = get_otp(client, sender, "transfer")
    ok = transfer(client, sender, receiver, "6000.00", otp=otp)
    assert ok.status_code == 201, ok.text
    # same OTP cannot be reused
    assert transfer(client, sender, receiver, "6000.00", otp=otp).status_code == 400
    # exactly 5000 needs no OTP
    assert transfer(client, sender, receiver, "5000.00").status_code == 201


def test_daily_limit_enforced(client):
    sender = make_actor(client, balance="9000.00")
    receiver = make_actor(client)
    assert transfer(client, sender, receiver, "5000.00").status_code == 201
    assert transfer(client, sender, receiver, "4000.00").status_code == 201
    over = transfer(client, sender, receiver, "2000.00")  # 11000 > 10000 daily
    assert over.status_code == 400
    assert_ledger_consistent()


def test_receiver_balance_cap(client):
    receiver = make_actor(client, balance="9990.00")
    sender = make_actor(client, balance="500.00")
    assert transfer(client, sender, receiver, "50.00").status_code == 400
    assert balance(client, sender) == Decimal("500.00")


def test_idempotency_replay_conflict_and_mismatch(client):
    sender = make_actor(client, balance="1000.00")
    receiver = make_actor(client)
    key = new_key()
    first = transfer(client, sender, receiver, "100.00", key=key)
    assert first.status_code == 201
    assert "idempotent-replayed" not in {k.lower() for k in first.headers}
    second = transfer(client, sender, receiver, "100.00", key=key)
    assert second.status_code == 201
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert second.json()["transaction_ref"] == first.json()["transaction_ref"]
    assert balance(client, sender) == Decimal("900.00")
    assert balance(client, receiver) == Decimal("100.00")
    mismatch = transfer(client, sender, receiver, "200.00", key=key)
    assert mismatch.status_code == 422
    assert balance(client, sender) == Decimal("900.00")


def test_idempotency_key_expires_after_24h(client):
    from datetime import timedelta
    from sqlalchemy import update
    from app.models.idempotency import IdempotencyKey
    from app.services import idempotency
    from app.utils.time import utcnow

    user = make_actor(client)
    key = new_key()
    add_money(client, user, "100.00", key=key)
    with SessionLocal() as db:
        db.execute(update(IdempotencyKey).values(created_at=utcnow() - timedelta(hours=25)))
        db.commit()
        assert idempotency.purge_expired(db) >= 1
    add_money(client, user, "100.00", key=key)  # key may be reused after expiry
    assert balance(client, user) == Decimal("200.00")


def test_fraud_hold_approve_and_reject(client):
    admin = make_admin(client)
    sender = make_actor(client)
    receiver = make_actor(client)
    upgrade_kyc(client, admin, sender, "Minimum")
    upgrade_kyc(client, admin, receiver, "Minimum")  # approving credits 21000, above the 10000 cap of a no-KYC wallet
    add_money(client, sender, "50000.00")
    otp = get_otp(client, sender, "transfer")
    held = transfer(client, sender, receiver, "21000.00", otp=otp)
    assert held.status_code == 201, held.text
    assert held.json()["status"] == "On Hold"
    ref = held.json()["transaction_ref"]
    assert balance(client, sender) == Decimal("29000.00")
    assert balance(client, receiver) == Decimal("0.00")
    flagged = client.get("/admin/flagged-transactions", headers=admin.headers).json()
    assert flagged["total"] == 1 and flagged["items"][0]["transaction_ref"] == ref
    assert client.get("/admin/flagged-transactions", headers=sender.headers).status_code == 403
    assert client.put(f"/admin/transactions/{ref}/reject", json={}, headers=admin.headers).status_code == 422
    rejected = client.put(f"/admin/transactions/{ref}/reject", json={"reason": "Looks fraudulent"}, headers=admin.headers)
    assert rejected.status_code == 200, rejected.text
    assert balance(client, sender) == Decimal("50000.00")  # refunded
    assert client.put(f"/admin/transactions/{ref}/approve", headers=admin.headers).status_code == 409
    assert_ledger_consistent()

    otp = get_otp(client, sender, "transfer")
    held2 = transfer(client, sender, receiver, "21000.00", otp=otp).json()["transaction_ref"]
    approved = client.put(f"/admin/transactions/{held2}/approve", headers=admin.headers)
    assert approved.status_code == 200, approved.text
    assert balance(client, receiver) == Decimal("21000.00")
    detail = client.get(f"/transactions/{held2}", headers=sender.headers).json()
    assert detail["status"] == "Success"
    assert_ledger_consistent()


def test_fraud_hold_on_burst_of_transfers(client):
    sender = make_actor(client, balance="1000.00")
    receiver = make_actor(client)
    statuses = [transfer(client, sender, receiver, "1.00").json()["status"] for _ in range(6)]
    assert statuses[:5] == ["Success"] * 5
    assert statuses[5] == "On Hold"
