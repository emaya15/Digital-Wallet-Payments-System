import csv
import io
from datetime import timedelta
from decimal import Decimal

from app.utils.time import today_local
from tests.integration.helpers import PIN, add_money, balance, idem, make_actor, make_admin, transfer


def seed_activity(client):
    sender = make_actor(client, balance="1000.00")
    receiver = make_actor(client)
    merchant = make_actor(client, "merchant")
    refs = [transfer(client, sender, receiver, a).json()["transaction_ref"] for a in ("10.00", "30.00", "20.00")]
    pay = client.post("/payments/merchant", json={"merchant_code": merchant.merchant_code, "amount": "100.00", "pin": PIN}, headers=idem(sender))
    assert pay.status_code == 201
    return sender, receiver, merchant, refs


def test_history_filters_sorting_pagination(client):
    sender, receiver, merchant, refs = seed_activity(client)
    everything = client.get("/transactions", headers=sender.headers).json()
    assert everything["total"] == 5  # add money + 3 transfers + 1 merchant payment
    only_p2p = client.get("/transactions?type=P2P Transfer", headers=sender.headers).json()
    assert only_p2p["total"] == 3
    big = client.get("/transactions?min_amount=25&type=P2P Transfer", headers=sender.headers).json()
    assert [Decimal(i["amount"]) for i in big["items"]] == [Decimal("30.00")]
    by_amount = client.get("/transactions?type=P2P Transfer&sort_by=amount&order=asc", headers=sender.headers).json()
    assert [Decimal(i["amount"]) for i in by_amount["items"]] == [Decimal("10.00"), Decimal("20.00"), Decimal("30.00")]
    page = client.get("/transactions?limit=2&skip=2", headers=sender.headers).json()
    assert len(page["items"]) == 2 and page["total"] == 5
    today = today_local()
    in_range = client.get(f"/transactions?from_date={today}&to_date={today}", headers=sender.headers).json()
    assert in_range["total"] == 5
    old = client.get(f"/transactions?to_date={today - timedelta(days=3)}", headers=sender.headers).json()
    assert old["total"] == 0
    assert client.get("/transactions?type=Bogus", headers=sender.headers).status_code == 422
    assert client.get("/transactions?status=Bogus", headers=sender.headers).status_code == 422
    assert client.get("/transactions?min_amount=50&max_amount=10", headers=sender.headers).status_code == 422
    assert client.get("/transactions?limit=1000", headers=sender.headers).status_code == 422


def test_transaction_detail_access_control_and_admin_view(client):
    sender, receiver, merchant, refs = seed_activity(client)
    admin = make_admin(client)
    stranger = make_actor(client)
    assert client.get(f"/transactions/{refs[0]}", headers=sender.headers).status_code == 200
    assert client.get(f"/transactions/{refs[0]}", headers=receiver.headers).json()["direction"] == "Credit"
    assert client.get(f"/transactions/{refs[0]}", headers=stranger.headers).status_code == 404
    assert client.get("/transactions/TXN-DOES-NOT-EXIST", headers=sender.headers).status_code == 404
    admin_view = client.get(f"/transactions/{refs[0]}", headers=admin.headers).json()
    assert admin_view["ledger_entries"]
    assert client.get("/transactions", headers=admin.headers).json()["total"] == 5
    assert client.get("/transactions").status_code in (401, 403)


def test_statements_csv_and_pdf(client):
    sender, *_ = seed_activity(client)
    month = today_local().strftime("%Y-%m")
    csv_response = client.get(f"/statements?month={month}&format=csv", headers=sender.headers)
    assert csv_response.status_code == 200
    assert "csv" in csv_response.headers["content-type"]
    rows = list(csv.reader(io.StringIO(csv_response.text)))
    assert any("P2P Transfer" in ",".join(r) for r in rows)
    pdf = client.get(f"/statements?month={month}&format=pdf", headers=sender.headers)
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"
    assert b"/Encrypt" in pdf.content  # password protected (DOB based)
    assert pdf.headers.get("X-Statement-Password-Hint")
    assert client.get("/statements?month=2999-01&format=pdf", headers=sender.headers).status_code == 400
    assert client.get("/statements?month=bad&format=pdf", headers=sender.headers).status_code == 422
    assert client.get(f"/statements?month={month}&format=xls", headers=sender.headers).status_code == 422
    assert client.get(f"/statements?month={month}", headers=sender.headers).status_code == 200  # default pdf


def test_reports(client):
    sender, receiver, merchant, _ = seed_activity(client)
    admin = make_admin(client)
    dash = client.get("/reports/admin-dashboard", headers=admin.headers)
    assert dash.status_code == 200, dash.text
    assert dash.json()["ledger_balanced"] is True
    assert Decimal(dash.json()["total_money_in_wallets"]) == Decimal("999.00")  # 1000 minus the 1.00 platform fee
    assert client.get("/reports/admin-dashboard", headers=sender.headers).status_code == 403
    ledger = client.get("/reports/ledger-summary", headers=admin.headers).json()
    assert ledger["balanced"] is True and ledger["reconciled"] is True and ledger["wallet_mismatches"] == []
    sales = client.get("/reports/merchant-sales", headers=merchant.headers)
    assert sales.status_code == 200, sales.text
    assert Decimal(sales.json()["total_gross_sales"]) == Decimal("100.00")
    assert Decimal(sales.json()["total_fees"]) == Decimal("1.00")
    assert client.get("/reports/merchant-sales", headers=sender.headers).status_code == 403
    spending = client.get("/reports/my-spending", headers=sender.headers)
    assert spending.status_code == 200
    assert Decimal(spending.json()["total_spent"]) == Decimal("160.00")
    assert client.get("/reports/my-spending?month=garbage", headers=sender.headers).status_code == 422


def test_notifications_listing_and_login_email(client, outbox):
    user = make_actor(client, balance="100.00")
    listing = client.get("/notifications", headers=user.headers).json()
    assert listing["total"] >= 1
    assert any("login" in m["subject"].lower() for m in outbox if m["to"] == user.email)
