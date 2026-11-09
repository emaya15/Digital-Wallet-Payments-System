import json
from decimal import Decimal

import pytest

from app.config import settings
from app.services import razorpay_service
from app.utils.signatures import razorpay_payment_signature, webhook_signature
from tests.integration.helpers import balance, idem, make_actor, new_key


class FakeClient:
    """Stands in for the Razorpay SDK client (no network access in tests)."""

    def __init__(self, status="captured", amount=None, order_id=None):
        self.status, self.amount, self.order_id = status, amount, order_id
        self.captured = False
        self.count = 0
        self.order = self
        self.payment = self

    def create(self, data):
        self.amount = data["amount"]
        self.count += 1
        self.order_id = f"order_TEST{self.count:05d}"
        return {"id": self.order_id, "amount": data["amount"]}

    def fetch(self, payment_id):
        return {"id": payment_id, "order_id": self.order_id, "amount": self.amount, "status": "captured" if self.captured else self.status}

    def capture(self, payment_id, amount):
        self.captured = True
        return {}


@pytest.fixture()
def fake(monkeypatch):
    holder = FakeClient()
    monkeypatch.setattr(razorpay_service, "get_client", lambda: holder)
    return holder


def create_order(client, user, amount="500.00"):
    response = client.post("/wallet/razorpay-order", json={"amount": amount}, headers=user.headers)
    assert response.status_code == 201, response.text
    return response.json()


def confirm(client, user, order_id, payment_id="pay_TEST12345", signature=None, key=None):
    sig = signature or razorpay_payment_signature(order_id, payment_id, settings.razorpay_key_secret)
    return client.post(
        "/wallet/razorpay-confirm",
        json={"razorpay_order_id": order_id, "razorpay_payment_id": payment_id, "razorpay_signature": sig},
        headers=idem(user, key),
    )


def test_order_and_confirm_credits_once(client, fake):
    user = make_actor(client)
    order = create_order(client, user)
    assert order["amount_paise"] == 50000
    key = new_key()
    first = confirm(client, user, order["razorpay_order_id"], key=key)
    assert first.status_code == 201, first.text
    assert balance(client, user) == Decimal("500.00")
    assert confirm(client, user, order["razorpay_order_id"], key=key).headers.get("Idempotent-Replayed") == "true"
    again = confirm(client, user, order["razorpay_order_id"])  # new key, same payment -> no double credit
    assert again.status_code == 200 and again.json()["credited"] is False
    assert balance(client, user) == Decimal("500.00")


def test_confirm_rejects_bad_signature_and_foreign_orders(client, fake):
    user = make_actor(client)
    other = make_actor(client)
    order = create_order(client, user)
    assert confirm(client, user, order["razorpay_order_id"], signature="0" * 64).status_code == 400
    assert confirm(client, other, order["razorpay_order_id"]).status_code == 404
    assert balance(client, user) == Decimal("0.00")


def test_authorized_payment_is_captured(client, monkeypatch):
    holder = FakeClient(status="authorized")
    monkeypatch.setattr(razorpay_service, "get_client", lambda: holder)
    user = make_actor(client)
    order = create_order(client, user, "100.00")
    assert confirm(client, user, order["razorpay_order_id"]).status_code == 201
    assert holder.captured is True


def test_uncaptured_payment_is_not_credited(client, monkeypatch):
    holder = FakeClient(status="created")
    monkeypatch.setattr(razorpay_service, "get_client", lambda: holder)
    user = make_actor(client)
    order = create_order(client, user, "100.00")
    assert confirm(client, user, order["razorpay_order_id"]).status_code in (400, 409)
    assert balance(client, user) == Decimal("0.00")


def webhook_body(order_id, payment_id, amount_paise, event="payment.captured", status="captured"):
    return json.dumps({"event": event, "payload": {"payment": {"entity": {
        "id": payment_id, "order_id": order_id, "amount": amount_paise, "status": status}}}}).encode()


def post_webhook(client, body, signature=None, event_id="evt_1"):
    sig = signature if signature is not None else webhook_signature(body, settings.razorpay_webhook_secret)
    return client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id,
                                                                      "Content-Type": "application/json"})


def test_webhook_signature_credit_and_dedupe(client, fake):
    user = make_actor(client)
    order = create_order(client, user, "250.00")
    body = webhook_body(order["razorpay_order_id"], "pay_WH1", 25000)
    assert post_webhook(client, body, signature="bad").status_code == 400
    ok = post_webhook(client, body)
    assert ok.status_code == 200 and ok.json()["status"] == "credited"
    assert balance(client, user) == Decimal("250.00")
    assert post_webhook(client, body).json()["status"] == "duplicate"  # same event id
    other_event = post_webhook(client, body, event_id="evt_2")
    assert other_event.json()["status"] == "already_credited"
    assert balance(client, user) == Decimal("250.00")


def test_webhook_confirm_race_credits_once_and_failed_event(client, fake):
    user = make_actor(client)
    order = create_order(client, user, "100.00")
    assert post_webhook(client, webhook_body(order["razorpay_order_id"], "pay_X", 10000)).status_code == 200
    confirmed = confirm(client, user, order["razorpay_order_id"], payment_id="pay_X")
    assert confirmed.status_code == 200 and confirmed.json()["credited"] is False
    assert balance(client, user) == Decimal("100.00")
    order2 = create_order(client, user, "100.00")
    failed = post_webhook(client, webhook_body(order2["razorpay_order_id"], "pay_F", 10000, event="payment.failed", status="failed"), event_id="evt_f")
    assert failed.status_code == 200
    assert balance(client, user) == Decimal("100.00")
