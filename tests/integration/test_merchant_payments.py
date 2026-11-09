import base64
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import update

from app.database import SessionLocal
from app.models.cashback import Cashback
from app.models.merchant_payment import MerchantPayment
from app.models.transaction import Transaction
from app.jobs import tasks
from app.utils.time import utcnow
from tests.integration.helpers import PIN, balance, idem, make_actor, new_key
from tests.integration.test_add_money_transfers import assert_ledger_consistent


def pay(client, payer, merchant, amount, key=None, pin=PIN):
    return client.post(
        "/payments/merchant",
        json={"merchant_code": merchant.merchant_code, "amount": amount, "pin": pin},
        headers=idem(payer, key),
    )


def test_qr_and_role_protection(client):
    merchant = make_actor(client, "merchant")
    user = make_actor(client)
    qr = client.get("/merchants/me/qr", headers=merchant.headers)
    assert qr.status_code == 200
    assert qr.json()["merchant_code"] == merchant.merchant_code
    assert base64.b64decode(qr.json()["qr_png_base64"])[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/merchants/me/qr", headers=user.headers).status_code == 403


def test_merchant_payment_fee_and_ledger(client):
    merchant = make_actor(client, "merchant")
    user = make_actor(client, balance="1000.00")
    response = pay(client, user, merchant, "500.00")
    assert response.status_code == 201, response.text
    assert balance(client, user) == Decimal("500.00")
    assert balance(client, merchant) == Decimal("495.00")  # 1% platform fee
    listing = client.get("/merchants/me/payments", headers=merchant.headers).json()
    assert listing["total"] == 1
    assert Decimal(listing["items"][0]["fee"]) == Decimal("5.00")
    assert "XXXX" in listing["items"][0]["payer_phone"] or "X" in listing["items"][0]["payer_phone"]
    assert_ledger_consistent()


def test_merchant_payment_errors_and_idempotency(client):
    merchant = make_actor(client, "merchant", balance="100.00")
    user = make_actor(client, balance="100.00")
    bad = client.post("/payments/merchant", json={"merchant_code": "NOPE0000", "amount": "10", "pin": PIN}, headers=idem(user))
    assert bad.status_code == 404
    assert pay(client, user, merchant, "500.00").status_code == 400
    assert pay(client, merchant, merchant, "10.00").status_code == 400
    key = new_key()
    assert pay(client, user, merchant, "10.00", key=key).status_code == 201
    replay = pay(client, user, merchant, "10.00", key=key)
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert balance(client, user) == Decimal("90.00")


def test_refund_full_partial_and_limits(client):
    merchant = make_actor(client, "merchant")
    user = make_actor(client, balance="1000.00")
    ref = pay(client, user, merchant, "200.00").json()["transaction_ref"]
    other = make_actor(client, "merchant")
    assert client.post(f"/payments/{ref}/refund", json={}, headers=idem(other)).status_code in (403, 404)
    assert client.post(f"/payments/{ref}/refund", json={}, headers=idem(user)).status_code == 403
    partial = client.post(f"/payments/{ref}/refund", json={"amount": "50.00", "reason": "Damaged"}, headers=idem(merchant))
    assert partial.status_code == 201, partial.text
    assert balance(client, user) == Decimal("850.00")
    assert client.post(f"/payments/{ref}/refund", json={"amount": "500.00"}, headers=idem(merchant)).status_code == 400
    rest = client.post(f"/payments/{ref}/refund", json={}, headers=idem(merchant))
    assert rest.status_code == 201, rest.text
    assert balance(client, user) == Decimal("1000.00")
    assert balance(client, merchant) == Decimal("0.00")
    assert client.post(f"/payments/{ref}/refund", json={}, headers=idem(merchant)).status_code == 400
    assert_ledger_consistent()


def test_refund_window_is_7_days(client):
    merchant = make_actor(client, "merchant")
    user = make_actor(client, balance="100.00")
    ref = pay(client, user, merchant, "50.00").json()["transaction_ref"]
    with SessionLocal() as db:
        db.execute(update(Transaction).where(Transaction.transaction_ref == ref).values(created_at=utcnow() - timedelta(days=8)))
        db.execute(update(MerchantPayment).values(created_at=utcnow() - timedelta(days=8)))
        db.commit()
    assert client.post(f"/payments/{ref}/refund", json={}, headers=idem(merchant)).status_code == 400


def test_cashback_credited_by_job_once(client):
    merchant = make_actor(client, "merchant")
    user = make_actor(client, balance="1000.00")
    pay(client, user, merchant, "500.00")  # 2% = 10.00
    with SessionLocal() as db:
        assert tasks.cashback_job(db) == 0  # not yet due (24h delay)
        db.execute(update(Cashback).values(credit_at=utcnow() - timedelta(minutes=1)))
        db.commit()
    with SessionLocal() as db:
        assert tasks.cashback_job(db) == 1
    with SessionLocal() as db:
        assert tasks.cashback_job(db) == 0  # idempotent
    assert balance(client, user) == Decimal("510.00")
    assert_ledger_consistent()


def test_cashback_is_capped_at_50(client):
    merchant = make_actor(client, "merchant")
    user = make_actor(client, balance="9000.00")
    pay(client, user, merchant, "5000.00")  # 2% would be 100 -> capped at 50
    with SessionLocal() as db:
        amount = db.query(Cashback).one().amount
    assert amount == Decimal("50.00")
