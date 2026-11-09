from datetime import timedelta

from sqlalchemy import update

from app.database import SessionLocal
from app.models.otp import OTP
from app.utils.time import utcnow
from tests.integration.helpers import PIN, get_otp, make_actor, make_admin, transfer, add_money


def test_set_pin_rules(client):
    user = make_actor(client, pin=False)
    assert client.post("/wallet/pin", json={"pin": "1234", "confirm_pin": "1234"}, headers=user.headers).status_code == 422
    assert client.post("/wallet/pin", json={"pin": "1111", "confirm_pin": "1111"}, headers=user.headers).status_code == 422
    assert client.post("/wallet/pin", json={"pin": "7391", "confirm_pin": "7392"}, headers=user.headers).status_code == 400
    assert client.post("/wallet/pin", json={"pin": "12", "confirm_pin": "12"}, headers=user.headers).status_code == 422
    assert client.post("/wallet/pin", json={"pin": PIN, "confirm_pin": PIN}, headers=user.headers).status_code == 201
    assert client.post("/wallet/pin", json={"pin": PIN, "confirm_pin": PIN}, headers=user.headers).status_code == 409


def test_change_pin(client):
    user = make_actor(client)
    assert client.put("/wallet/pin/change", json={"old_pin": "0000", "new_pin": "8264"}, headers=user.headers).status_code == 403
    assert client.put("/wallet/pin/change", json={"old_pin": PIN, "new_pin": PIN}, headers=user.headers).status_code == 400
    assert client.put("/wallet/pin/change", json={"old_pin": PIN, "new_pin": "8264"}, headers=user.headers).status_code == 200
    receiver = make_actor(client)
    add_money(client, user, "100.00")
    assert transfer(client, user, receiver, "5.00", pin=PIN).status_code == 403
    assert transfer(client, user, receiver, "5.00", pin="8264").status_code == 201


def test_pin_lockout_after_three_failures(client):
    sender = make_actor(client, balance="100.00")
    receiver = make_actor(client)
    assert transfer(client, sender, receiver, "1.00", pin="0000").status_code == 403
    assert transfer(client, sender, receiver, "1.00", pin="0000").status_code == 403
    assert transfer(client, sender, receiver, "1.00", pin="0000").status_code == 423
    # even the correct PIN is refused while locked
    assert transfer(client, sender, receiver, "1.00", pin=PIN).status_code == 423
    assert client.get("/wallet", headers=sender.headers).json()["pin_locked_until"] is not None


def test_pin_reset_with_otp(client):
    user = make_actor(client)
    assert client.post("/wallet/pin/reset", json={"otp_code": "123456", "new_pin": "8264"}, headers=user.headers).status_code == 400
    code = get_otp(client, user, "pin_reset")
    assert client.post("/wallet/pin/reset", json={"otp_code": code, "new_pin": "8264"}, headers=user.headers).status_code == 200
    # OTP is single use
    assert client.post("/wallet/pin/reset", json={"otp_code": code, "new_pin": "9157"}, headers=user.headers).status_code == 400


def test_otp_rules(client, outbox):
    user = make_actor(client)
    code = get_otp(client, user, "transfer")
    assert len(code) == 6 and code.isdigit()
    assert any(m["to"] == user.email and "OTP" in m["subject"].upper() for m in outbox)
    # resend inside 60 seconds is rate limited
    assert client.post("/otp/send", json={"purpose": "transfer"}, headers=user.headers).status_code == 429
    assert client.post("/otp/send", json={"purpose": "bogus"}, headers=user.headers).status_code == 422
    wrong = "000000" if code != "000000" else "111111"
    assert client.post("/otp/verify", json={"purpose": "transfer", "otp_code": wrong}, headers=user.headers).status_code == 400
    assert client.post("/otp/verify", json={"purpose": "transfer", "otp_code": wrong}, headers=user.headers).status_code == 400
    assert client.post("/otp/verify", json={"purpose": "transfer", "otp_code": wrong}, headers=user.headers).status_code == 423
    # locked: even the right code no longer works
    assert client.post("/otp/verify", json={"purpose": "transfer", "otp_code": code}, headers=user.headers).status_code in (400, 423)


def test_otp_expiry_and_purpose_binding(client):
    user = make_actor(client)
    code = get_otp(client, user, "transfer")
    assert client.post("/otp/verify", json={"purpose": "pin_reset", "otp_code": code}, headers=user.headers).status_code == 400
    with SessionLocal() as db:
        db.execute(update(OTP).values(expires_at=utcnow() - timedelta(minutes=1)))
        db.commit()
    assert client.post("/otp/verify", json={"purpose": "transfer", "otp_code": code}, headers=user.headers).status_code == 400


def test_admin_cannot_use_money_endpoints(client):
    admin = make_admin(client)
    assert client.post("/otp/send", json={"purpose": "transfer"}, headers=admin.headers).status_code == 403
