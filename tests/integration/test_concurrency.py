from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from app.database import SessionLocal
from app.services import ledger_service
from tests.integration.helpers import balance, make_actor, new_key, transfer


def test_parallel_transfers_never_overspend(client):
    sender = make_actor(client, balance="100.00")
    receiver = make_actor(client)

    def go(_):
        return transfer(client, sender, receiver, "30.00").status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = list(pool.map(go, range(6)))
    assert codes.count(201) == 3, codes
    assert all(code in (201, 400, 409) for code in codes)
    assert balance(client, sender) == Decimal("10.00")
    assert balance(client, receiver) == Decimal("90.00")
    with SessionLocal() as db:
        assert ledger_service.reconcile(db)["ok"]


def test_parallel_same_idempotency_key_moves_money_once(client):
    sender = make_actor(client, balance="100.00")
    receiver = make_actor(client)
    key = new_key()

    def go(_):
        return transfer(client, sender, receiver, "40.00", key=key).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = list(pool.map(go, range(5)))
    assert 201 in codes
    assert all(code in (201, 409) for code in codes), codes
    assert balance(client, sender) == Decimal("60.00")


def test_opposite_direction_transfers_do_not_deadlock(client):
    a = make_actor(client, balance="500.00")
    b = make_actor(client, balance="500.00")

    def go(i):
        return transfer(client, a, b, "10.00").status_code if i % 2 == 0 else transfer(client, b, a, "10.00").status_code

    # 5 transfers per direction: a 6th transfer within a minute is placed On Hold by the fraud rule
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(go, range(10)))
    assert all(code == 201 for code in codes), codes
    assert balance(client, a) + balance(client, b) == Decimal("1000.00")
    with SessionLocal() as db:
        assert ledger_service.reconcile(db)["ok"]
