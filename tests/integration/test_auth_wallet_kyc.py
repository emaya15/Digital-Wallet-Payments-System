from decimal import Decimal

from tests.integration.helpers import make_actor, make_admin, upgrade_kyc, balance


def test_register_login_me(client):
    user = make_actor(client, pin=False)
    me = client.get("/auth/me", headers=user.headers)
    assert me.status_code == 200
    assert me.json()["email"] == user.email
    assert me.json()["wallet_number"]


def test_register_rules(client):
    user = make_actor(client, pin=False)
    base = {"name": "Dup", "email": "dup@example.com", "phone": "9123456780", "password": "Passw0rd!x",
            "date_of_birth": "1995-01-01", "role": "user"}
    assert client.post("/auth/register", json={**base, "email": user.email}).status_code == 409
    assert client.post("/auth/register", json={**base, "phone": user.phone}).status_code == 409
    assert client.post("/auth/register", json={**base, "phone": "1234567890"}).status_code == 422
    assert client.post("/auth/register", json={**base, "role": "admin"}).status_code == 403
    assert client.post("/auth/register", json={**base, "role": "merchant"}).status_code == 422  # business details missing


def test_login_failures_and_auth_required(client):
    user = make_actor(client, pin=False)
    assert client.post("/auth/login", json={"email": user.email, "password": "wrongpass1"}).status_code == 401
    assert client.get("/auth/me").status_code in (401, 403)
    assert client.get("/auth/me", headers={"Authorization": "Bearer not.a.token"}).status_code == 401


def test_wallet_defaults_and_roles(client):
    user = make_actor(client, pin=False)
    admin = make_admin(client)
    wallet = client.get("/wallet", headers=user.headers).json()
    assert wallet["balance"] == "0.00"
    assert wallet["kyc_level"] == "None"
    assert wallet["pin_set"] is False
    assert Decimal(wallet["limits"]["daily_limit"]) == Decimal("10000.00")
    assert client.get("/wallet", headers=admin.headers).status_code == 403


def test_kyc_flow_and_limits(client):
    user = make_actor(client)
    admin = make_admin(client)
    assert client.get("/admin/kyc", headers=user.headers).status_code == 403
    bad = client.post("/kyc", json={"kyc_type": "Full", "id_proof_type": "Aadhaar", "id_proof_number": "123456789012",
                                    "pan_number": "BADPAN", "address": "12 Main Street"}, headers=user.headers)
    assert bad.status_code == 422
    upgrade_kyc(client, admin, user, "Minimum")
    assert client.get("/wallet", headers=user.headers).json()["kyc_level"] == "Minimum"
    status = client.get("/kyc", headers=user.headers).json()
    assert status["kyc_level"] == "Minimum"
    assert "123456789012" not in str(status)  # documents are masked
    upgrade_kyc(client, admin, user, "Full")
    wallet = client.get("/wallet", headers=user.headers).json()
    assert wallet["kyc_level"] == "Full"
    assert Decimal(wallet["limits"]["max_balance"]) == Decimal("200000.00")


def test_kyc_reject_requires_reason_and_no_double_review(client):
    user = make_actor(client)
    admin = make_admin(client)
    created = client.post("/kyc", json={"kyc_type": "Minimum", "id_proof_type": "Passport", "id_proof_number": "P1234567"},
                          headers=user.headers).json()
    assert client.post("/kyc", json={"kyc_type": "Minimum", "id_proof_type": "Passport", "id_proof_number": "P1234567"},
                       headers=user.headers).status_code == 409
    assert client.put(f"/admin/kyc/{created['id']}/reject", json={}, headers=admin.headers).status_code == 422
    rejected = client.put(f"/admin/kyc/{created['id']}/reject", json={"reason": "Blurry document"}, headers=admin.headers)
    assert rejected.status_code == 200 and rejected.json()["status"] == "Rejected"
    assert client.put(f"/admin/kyc/{created['id']}/approve", headers=admin.headers).status_code == 409
    assert client.put("/admin/kyc/99999/approve", headers=admin.headers).status_code == 404


def test_freeze_blocks_payments_and_unfreeze_restores(client):
    sender = make_actor(client, balance="500.00")
    receiver = make_actor(client)
    admin = make_admin(client)
    wallet_id = client.get("/wallet", headers=sender.headers).json()["wallet_id"]
    assert client.put(f"/admin/wallets/{wallet_id}/freeze", json={}, headers=admin.headers).status_code == 422
    assert client.put(f"/admin/wallets/{wallet_id}/freeze", json={"reason": "Suspicious"}, headers=admin.headers).status_code == 200
    from tests.integration.helpers import transfer
    assert transfer(client, sender, receiver, "10.00").status_code == 423
    assert client.put(f"/admin/wallets/{wallet_id}/unfreeze", headers=admin.headers).status_code == 200
    assert transfer(client, sender, receiver, "10.00").status_code == 201
    assert balance(client, sender) == Decimal("490.00")
    assert client.put(f"/admin/wallets/{wallet_id}/freeze", json={"reason": "x y z"}, headers=sender.headers).status_code == 403
