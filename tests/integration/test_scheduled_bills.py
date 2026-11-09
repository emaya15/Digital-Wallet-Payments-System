from datetime import timedelta
from decimal import Decimal

from sqlalchemy import update

from app.database import SessionLocal
from app.jobs import tasks
from app.models.scheduled_payment import ScheduledPayment
from app.utils.time import today_local, utcnow
from tests.integration.helpers import PIN, balance, get_otp, idem, make_actor, new_key
from tests.integration.test_add_money_transfers import assert_ledger_consistent


def create_sp(client, user, receiver, amount="100.00", **extra):
    body = {"receiver_phone": receiver.phone, "amount": amount, "start_date": str(today_local()), "pin": PIN, **extra}
    return client.post("/scheduled-payments", json=body, headers=user.headers)


def make_due():
    with SessionLocal() as db:
        db.execute(update(ScheduledPayment).values(next_run_at=utcnow() - timedelta(minutes=1)))
        db.commit()


def test_scheduled_payment_crud_and_execution(client):
    user = make_actor(client, balance="1000.00")
    receiver = make_actor(client)
    created = create_sp(client, user, receiver)
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    assert client.get("/scheduled-payments", headers=user.headers).json()[0]["id"] == pid
    assert client.get(f"/scheduled-payments/{pid}", headers=receiver.headers).status_code == 404
    make_due()
    with SessionLocal() as db:
        assert tasks.scheduled_payments_job(db) == {"success": 1}
    with SessionLocal() as db:
        assert tasks.scheduled_payments_job(db) == {}  # next run moved a month ahead; no double execution
    assert balance(client, user) == Decimal("900.00")
    assert balance(client, receiver) == Decimal("100.00")
    detail = client.get(f"/scheduled-payments/{pid}", headers=user.headers).json()
    assert detail["run_count"] == 1 and detail["executions"][0]["status"] == "Success"
    assert_ledger_consistent()


def test_scheduled_payment_failure_is_recorded(client):
    user = make_actor(client, balance="50.00")
    receiver = make_actor(client)
    pid = create_sp(client, user, receiver, amount="100.00").json()["id"]
    make_due()
    with SessionLocal() as db:
        tasks.scheduled_payments_job(db)
    detail = client.get(f"/scheduled-payments/{pid}", headers=user.headers).json()
    assert detail["executions"][0]["status"] == "Failed"
    assert "Insufficient" in detail["executions"][0]["failure_reason"]
    assert balance(client, user) == Decimal("50.00")


def test_scheduled_payment_update_pause_cancel_and_rules(client):
    user = make_actor(client, balance="1000.00")
    receiver = make_actor(client)
    yesterday = str(today_local() - timedelta(days=1))
    past = client.post("/scheduled-payments", json={"receiver_phone": receiver.phone, "amount": "10", "start_date": yesterday, "pin": PIN},
                       headers=user.headers)
    assert past.status_code == 422
    assert create_sp(client, user, user).status_code == 400
    assert create_sp(client, user, receiver, pin="0000").status_code == 403
    pid = create_sp(client, user, receiver).json()["id"]
    updated = client.put(f"/scheduled-payments/{pid}", json={"pin": PIN, "amount": "150.00"}, headers=user.headers)
    assert updated.status_code == 200 and updated.json()["amount"] == "150.00"
    assert client.put(f"/scheduled-payments/{pid}", json={"pin": PIN, "status": "Paused"}, headers=user.headers).json()["status"] == "Paused"
    make_due()
    with SessionLocal() as db:
        assert tasks.scheduled_payments_job(db) == {}  # paused payments never run
    assert client.delete(f"/scheduled-payments/{pid}", headers=user.headers).status_code == 200
    assert client.get(f"/scheduled-payments/{pid}", headers=user.headers).json()["status"] == "Cancelled"


def test_scheduled_payment_large_amount_needs_otp(client):
    user = make_actor(client, balance="9000.00")
    receiver = make_actor(client)
    assert create_sp(client, user, receiver, amount="6000.00").status_code == 403
    otp = get_otp(client, user, "scheduled_payment")
    assert create_sp(client, user, receiver, amount="6000.00", otp_code=otp).status_code == 201


# ------------------------------------------------------------------- bills

def bill(client, user, **overrides):
    key = overrides.pop("key", None)
    body = {"bill_type": "Mobile Recharge", "provider": "Jio", "customer_identifier": "9876543210", "amount": "299.00", "pin": PIN}
    body.update(overrides)
    return client.post("/bill-payments", json=body, headers=idem(user, key))


def test_bill_payment_success_history_and_validation(client):
    user = make_actor(client, balance="1000.00")
    ok = bill(client, user)
    assert ok.status_code == 201, ok.text
    assert ok.json()["status"] == "Success" and ok.json()["reference_number"]
    assert balance(client, user) == Decimal("701.00")
    assert client.get("/bill-payments", headers=user.headers).json()["total"] == 1
    assert client.get(f"/bill-payments/{ok.json()['id']}", headers=user.headers).status_code == 200
    other = make_actor(client)
    assert client.get(f"/bill-payments/{ok.json()['id']}", headers=other.headers).status_code == 404
    assert bill(client, user, provider="Nope").status_code == 422
    assert bill(client, user, customer_identifier="12345").status_code == 422
    assert bill(client, user, amount="5.00").status_code == 422
    assert bill(client, user, bill_type="Electricity", provider="TNEB", customer_identifier="12345678", amount="50.00").status_code == 422
    elec = bill(client, user, bill_type="Electricity", provider="TNEB", customer_identifier="12345678", amount="200.00")
    assert elec.status_code == 201
    assert_ledger_consistent()


def test_bill_payment_simulated_failure_and_idempotency(client):
    user = make_actor(client, balance="500.00")
    failed = bill(client, user, customer_identifier="9876540000")
    assert failed.status_code == 200 and failed.json()["status"] == "Failed"
    assert balance(client, user) == Decimal("500.00")
    key = new_key()
    first = client.post("/bill-payments", json={"bill_type": "Mobile Recharge", "provider": "Airtel", "customer_identifier": "9876543211",
                                                "amount": "100.00", "pin": PIN}, headers=idem(user, key))
    second = client.post("/bill-payments", json={"bill_type": "Mobile Recharge", "provider": "Airtel", "customer_identifier": "9876543211",
                                                 "amount": "100.00", "pin": PIN}, headers=idem(user, key))
    assert first.status_code == 201 and second.headers.get("Idempotent-Replayed") == "true"
    assert balance(client, user) == Decimal("400.00")
