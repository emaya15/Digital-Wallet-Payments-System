"""Small helpers shared by the integration tests."""
import itertools
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.constants import Role
from app.database import SessionLocal
from app.services import auth_service

PIN = "7391"
_counter = itertools.count(1)


def new_key() -> str:
    return str(uuid.uuid4())


@dataclass
class Actor:
    id: int
    email: str
    phone: str
    role: str
    password: str
    token: str
    merchant_code: str | None = None
    headers: dict = field(default_factory=dict)


def _login(client, email: str, password: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def make_actor(client, role: str = Role.USER, *, pin: bool = True, balance: str | None = None) -> Actor:
    n = next(_counter)
    email = f"{role}{n}_{uuid.uuid4().hex[:6]}@example.com"
    phone = "9" + f"{800000000 + n}"
    password = "Passw0rd!x"
    payload = {
        "name": f"Test {role.title()} {n}",
        "email": email,
        "phone": phone,
        "password": password,
        "date_of_birth": "1995-04-12",
        "role": role,
    }
    if role == Role.MERCHANT:
        payload.update(business_name=f"Shop {n}", business_category="Retail")
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201, response.text
    token = _login(client, email, password)
    actor = Actor(
        id=response.json()["id"],
        email=email,
        phone=phone,
        role=role,
        password=password,
        token=token,
        merchant_code=response.json().get("merchant_code"),
        headers={"Authorization": f"Bearer {token}"},
    )
    if pin:
        set_pin(client, actor)
    if balance:
        add_money(client, actor, balance)
    return actor


def make_admin(client) -> Actor:
    n = next(_counter)
    email = f"admin{n}_{uuid.uuid4().hex[:6]}@example.com"
    phone = "9" + f"{700000000 + n}"
    with SessionLocal() as db:
        user = auth_service.create_user_directly(
            db, name="Admin", email=email, phone=phone, password="Passw0rd!x", role=Role.ADMIN, date_of_birth=date(1990, 1, 1)
        )
        user_id = user.id
    token = _login(client, email, "Passw0rd!x")
    return Actor(id=user_id, email=email, phone=phone, role=Role.ADMIN, password="Passw0rd!x", token=token,
                 headers={"Authorization": f"Bearer {token}"})


def set_pin(client, actor: Actor, pin: str = PIN):
    response = client.post("/wallet/pin", json={"pin": pin, "confirm_pin": pin}, headers=actor.headers)
    assert response.status_code == 201, response.text


def idem(actor: Actor, key: str | None = None) -> dict:
    return {**actor.headers, "Idempotency-Key": key or new_key()}


def add_money(client, actor: Actor, amount: str, key: str | None = None):
    response = client.post(
        "/wallet/add-money",
        json={"amount": amount, "payment_method": "UPI", "upi_id": "someone@upi"},
        headers=idem(actor, key),
    )
    assert response.status_code == 201, response.text
    return response


def balance(client, actor: Actor) -> Decimal:
    response = client.get("/wallet", headers=actor.headers)
    assert response.status_code == 200, response.text
    return Decimal(response.json()["balance"])


def get_otp(client, actor: Actor, purpose: str) -> str:
    """Request an OTP. Earlier OTPs are back-dated first so the 60 s resend limit does not block the test."""
    from datetime import timedelta
    from sqlalchemy import update
    from app.models.otp import OTP
    from app.utils.time import utcnow

    with SessionLocal() as db:
        db.execute(update(OTP).where(OTP.user_id == actor.id, OTP.purpose == purpose).values(created_at=utcnow() - timedelta(minutes=2)))
        db.commit()
    response = client.post("/otp/send", json={"purpose": purpose}, headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()["debug_otp"]


def transfer(client, sender: Actor, receiver: Actor, amount: str, *, pin: str = PIN, otp: str | None = None, key: str | None = None):
    body = {"receiver_phone": receiver.phone, "amount": amount, "pin": pin}
    if otp:
        body["otp_code"] = otp
    return client.post("/transfers", json=body, headers=idem(sender, key))


def upgrade_kyc(client, admin: Actor, actor: Actor, level: str = "Full") -> None:
    body = {"kyc_type": level, "id_proof_type": "Aadhaar", "id_proof_number": "123456789012"}
    if level == "Full":
        body.update(pan_number=f"ABCDE{1000 + actor.id % 9000}F", address="12 Main Street, Chennai")
    response = client.post("/kyc", json=body, headers=actor.headers)
    assert response.status_code == 201, response.text
    approve = client.put(f"/admin/kyc/{response.json()['id']}/approve", headers=admin.headers)
    assert approve.status_code == 200, approve.text
