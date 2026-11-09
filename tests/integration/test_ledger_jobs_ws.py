import pytest
from sqlalchemy import text, update

from app.database import SessionLocal, engine
from app.jobs import scheduler, tasks
from app.models.ledger import LedgerEntry
from app.models.wallet import Wallet
from tests.integration.helpers import make_actor, make_admin, transfer


def test_ledger_entries_are_immutable(client):
    user = make_actor(client, balance="100.00")
    with SessionLocal() as db:
        entry = db.query(LedgerEntry).first()
        entry.amount = 1
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
        entry = db.query(LedgerEntry).first()
        with pytest.raises(Exception):
            db.delete(entry)
            db.commit()
        db.rollback()
    assert user.id


def test_reconciliation_job_detects_tampering_and_alerts_admin(client, outbox):
    admin = make_admin(client)
    user = make_actor(client, balance="100.00")
    with SessionLocal() as db:
        assert tasks.ledger_reconciliation_job(db)["ok"] is True
    with SessionLocal() as db:  # bypass the ledger: change a wallet balance directly
        db.execute(update(Wallet).where(Wallet.user_id == user.id).values(balance=999))
        db.commit()
    with SessionLocal() as db:
        result = tasks.ledger_reconciliation_job(db)
    assert result["ok"] is False and len(result["wallet_mismatches"]) == 1
    assert any(m["to"] == admin.email for m in outbox)
    listing = client.get("/notifications", headers=admin.headers).json()
    assert any(n["event_type"] == "ledger_reconciliation_error" for n in listing["items"])


def test_cleanup_jobs(client):
    from datetime import timedelta
    from app.models.otp import OTP
    from app.utils.time import utcnow
    from tests.integration.helpers import get_otp

    user = make_actor(client)
    get_otp(client, user, "transfer")
    with SessionLocal() as db:
        db.execute(update(OTP).values(expires_at=utcnow() - timedelta(days=2)))
        db.commit()
        assert tasks.otp_cleanup_job(db) == 1
        assert tasks.idempotency_cleanup_job(db) == 0


def test_scheduler_registers_all_jobs_and_single_owner():
    started = scheduler.start_scheduler()
    try:
        assert started is True
        ids = set(scheduler.job_ids())
        assert {"cashback", "withdrawals", "money_request_expiry", "otp_cleanup", "idempotency_cleanup",
                "ledger_reconciliation", "scheduled_payments"} <= ids
        # a second scheduler instance (another worker) cannot take the advisory lock
        with engine.connect() as other:
            assert other.execute(text("SELECT GET_LOCK(:n, 0)"), {"n": scheduler.LOCK_NAME}).scalar() == 0
    finally:
        scheduler.shutdown_scheduler()


def test_websocket_auth_events_and_isolation(client):
    a = make_actor(client, balance="100.00")
    b = make_actor(client)
    c = make_actor(client)
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/wallet") as ws:
            ws.receive_json()
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/wallet?token=garbage") as ws:
            ws.receive_json()
    with client.websocket_connect(f"/ws/wallet?token={a.token}") as ws_a, client.websocket_connect(f"/ws/wallet?token={c.token}") as ws_c:
        assert ws_a.receive_json()["event"] == "connected"
        assert ws_c.receive_json()["event"] == "connected"
        ws_a.send_text("ping")
        assert ws_a.receive_json()["event"] == "pong"
        assert transfer(client, a, b, "10.00").status_code == 201
        message = ws_a.receive_json()
        assert message["event"] in ("payment_sent", "balance_update")
        ws_c.send_text("ping")
        assert ws_c.receive_json()["event"] == "pong"  # nothing leaked to the third user
    with client.websocket_connect("/ws/wallet", headers={"Authorization": f"Bearer {a.token}"}) as ws:
        assert ws.receive_json()["event"] == "connected"
