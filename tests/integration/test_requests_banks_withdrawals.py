from datetime import timedelta
from decimal import Decimal

from sqlalchemy import update

from app.database import SessionLocal
from app.jobs import tasks
from app.models.money_request import MoneyRequest
from app.utils.time import utcnow
from tests.integration.helpers import (
    PIN, balance, get_otp, idem, make_actor, make_admin, new_key, upgrade_kyc,
)
from tests.integration.test_add_money_transfers import assert_ledger_consistent


# ------------------------------------------------------------ money requests

def test_money_request_lifecycle(client):
    requester = make_actor(client)
    payer = make_actor(client, balance="500.00")
    created = client.post("/money-requests", json={"payer_phone": payer.phone, "amount": "120.00", "note": "Lunch"}, headers=requester.headers)
    assert created.status_code == 201, created.text
    rid = created.json()["id"]
    assert created.json()["status"] == "Pending"
    assert client.get("/money-requests?direction=sent", headers=requester.headers).json()["total"] == 1
    assert client.get("/money-requests?direction=received", headers=payer.headers).json()["total"] == 1
    # wrong party cannot pay
    assert client.put(f"/money-requests/{rid}/pay", json={"pin": PIN}, headers=idem(requester)).status_code == 403
    paid = client.put(f"/money-requests/{rid}/pay", json={"pin": PIN}, headers=idem(payer))
    assert paid.status_code in (200, 201), paid.text
    assert balance(client, payer) == Decimal("380.00")
    assert balance(client, requester) == Decimal("120.00")
    assert client.put(f"/money-requests/{rid}/pay", json={"pin": PIN}, headers=idem(payer)).status_code == 409
    assert_ledger_consistent()


def test_money_request_decline_cancel_and_rules(client):
    a = make_actor(client)
    b = make_actor(client, balance="100.00")
    assert client.post("/money-requests", json={"payer_phone": a.phone, "amount": "10"}, headers=a.headers).status_code == 400
    first = client.post("/money-requests", json={"payer_phone": b.phone, "amount": "10"}, headers=a.headers).json()["id"]
    assert client.put(f"/money-requests/{first}/cancel", headers=b.headers).status_code == 403
    assert client.put(f"/money-requests/{first}/decline", headers=a.headers).status_code == 403
    assert client.put(f"/money-requests/{first}/decline", headers=b.headers).json()["status"] == "Declined"
    second = client.post("/money-requests", json={"payer_phone": b.phone, "amount": "10"}, headers=a.headers).json()["id"]
    assert client.put(f"/money-requests/{second}/cancel", headers=a.headers).json()["status"] == "Cancelled"
    assert client.put("/money-requests/99999/decline", headers=b.headers).status_code == 404


def test_money_request_pending_limit_and_expiry_job(client):
    a = make_actor(client)
    b = make_actor(client)
    for _ in range(5):
        assert client.post("/money-requests", json={"payer_phone": b.phone, "amount": "10"}, headers=a.headers).status_code == 201
    assert client.post("/money-requests", json={"payer_phone": b.phone, "amount": "10"}, headers=a.headers).status_code == 400
    with SessionLocal() as db:
        db.execute(update(MoneyRequest).values(expires_at=utcnow() - timedelta(hours=1)))
        db.commit()
    with SessionLocal() as db:
        assert tasks.money_request_expiry_job(db) == 5
    listing = client.get("/money-requests?status=Expired", headers=b.headers).json()
    assert listing["total"] == 5


# -------------------------------------------------------------- bank accounts

def link_bank(client, actor, number="123456789012", primary=False):
    otp = get_otp(client, actor, "bank_account")
    return client.post(
        "/bank-accounts",
        json={"account_holder_name": "Asha K", "bank_name": "HDFC Bank", "account_number": number,
              "ifsc": "HDFC0001234", "is_primary": primary, "otp_code": otp},
        headers=actor.headers,
    )


def test_bank_account_crud_and_validation(client):
    user = make_actor(client)
    r = link_bank(client, user)
    assert r.status_code == 201, r.text
    assert r.json()["account_number_masked"].endswith("9012")
    assert "123456789012" not in r.text
    assert client.get("/bank-accounts", headers=user.headers).json()[0]["id"] == r.json()["id"]
    assert link_bank(client, user).status_code == 409  # duplicate
    bad_ifsc = client.post("/bank-accounts", json={"account_holder_name": "A B", "bank_name": "HDFC", "account_number": "111122223333",
                                                  "ifsc": "BAD", "otp_code": "123456"}, headers=user.headers)
    assert bad_ifsc.status_code == 422
    no_otp = client.post("/bank-accounts", json={"account_holder_name": "A B", "bank_name": "HDFC", "account_number": "111122223333",
                                                "ifsc": "HDFC0001234", "otp_code": "123456"}, headers=user.headers)
    assert no_otp.status_code in (400, 403)
    assert link_bank(client, user, "222233334444").status_code == 201
    assert link_bank(client, user, "333344445555").status_code == 201
    assert link_bank(client, user, "444455556666").status_code == 400  # max 3
    assert client.delete(f"/bank-accounts/{r.json()['id']}", headers=user.headers).status_code == 200
    assert client.delete("/bank-accounts/99999", headers=user.headers).status_code == 404


# ----------------------------------------------------------------- withdrawals

def test_withdrawal_requires_full_kyc_and_min_amount(client):
    admin = make_admin(client)
    user = make_actor(client, balance="5000.00")
    bank = link_bank(client, user).json()
    body = {"amount": "500.00", "bank_account_id": bank["id"], "pin": PIN}
    assert client.post("/withdrawals", json=body, headers=idem(user)).status_code == 403
    upgrade_kyc(client, admin, user, "Full")
    assert client.post("/withdrawals", json={**body, "amount": "99.99"}, headers=idem(user)).status_code == 422
    assert client.post("/withdrawals", json={**body, "bank_account_id": 9999}, headers=idem(user)).status_code == 404
    assert client.post("/withdrawals", json={**body, "pin": "0000"}, headers=idem(user)).status_code == 403
    assert client.post("/withdrawals", json={**body, "amount": "9999.00"}, headers=idem(user)).status_code == 400


def test_withdrawal_completes_via_job(client):
    admin = make_admin(client)
    user = make_actor(client, balance="5000.00")
    upgrade_kyc(client, admin, user, "Full")
    bank = link_bank(client, user).json()
    key = new_key()
    body = {"amount": "1000.00", "bank_account_id": bank["id"], "pin": PIN}
    created = client.post("/withdrawals", json=body, headers=idem(user, key))
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "Pending"
    assert client.post("/withdrawals", json=body, headers=idem(user, key)).headers.get("Idempotent-Replayed") == "true"
    assert balance(client, user) == Decimal("4000.00")
    assert client.delete(f"/bank-accounts/{bank['id']}", headers=user.headers).status_code == 409  # pending withdrawal
    with SessionLocal() as db:
        assert tasks.withdrawal_job(db)["completed"] == 1
    listing = client.get("/withdrawals", headers=user.headers).json()
    assert listing["items"][0]["status"] == "Completed"
    assert balance(client, user) == Decimal("4000.00")
    assert_ledger_consistent()


def test_failed_withdrawal_is_reversed(client):
    admin = make_admin(client)
    user = make_actor(client, balance="3000.00")
    upgrade_kyc(client, admin, user, "Full")
    bank = link_bank(client, user, number="999988880000").json()  # ends in 0000 -> simulated bank failure
    created = client.post("/withdrawals", json={"amount": "500.00", "bank_account_id": bank["id"], "pin": PIN}, headers=idem(user))
    assert created.status_code == 201
    assert balance(client, user) == Decimal("2500.00")
    with SessionLocal() as db:
        assert tasks.withdrawal_job(db)["failed"] == 1
    item = client.get("/withdrawals", headers=user.headers).json()["items"][0]
    assert item["status"] == "Failed" and item["reversal_transaction_ref"]
    assert balance(client, user) == Decimal("3000.00")
    assert_ledger_consistent()
