# Digital Wallet & Payments Backend

A Paytm / PhonePe style wallet backend built with **FastAPI, SQLAlchemy 2.x, MySQL 8, Alembic, JWT, APScheduler, WebSockets and Razorpay (test mode)**.

Highlights

- Double-entry **ledger** (immutable entries, reversals are new transactions, wallet balance == ledger balance)
- KYC levels with balance / daily / monthly limits, transaction **PIN** (bcrypt, 3 strikes -> 30 min lock) and **OTP** (HMAC-hashed, 5 min, 3 attempts, 60 s resend)
- **Idempotency-Key** on every money-moving API (replay header, 422 on body mismatch, 409 while processing, 24 h expiry)
- Row locking in ascending wallet-id order (`SELECT ... FOR UPDATE`) plus deadlock retry
- Merchant payments (1 % platform fee, 2 % cashback capped at 50 credited after 24 h, refunds within 7 days)
- Money requests, bank accounts (encrypted numbers), withdrawals, fraud hold + admin review
- Statements (password protected PDF / CSV), reports, scheduled payments, bill payments
- Razorpay order / confirm / webhook, WebSocket live updates (`/ws/wallet`)
- 7 scheduled jobs, guarded so only one worker runs them

## Project layout

```
digital_wallet/
  app/
    main.py            application + lifespan (system ledger accounts, scheduler)
    config.py          settings from environment / .env
    database.py        engine (READ COMMITTED), session, Base
    constants.py       every business rule constant
    models/            22 SQLAlchemy models
    schemas/           Pydantic v2 request / response models
    routers/           one module per API area
    services/          business logic (routers stay thin)
    auth/              JWT + password hashing + role dependencies
    jobs/              APScheduler setup and job bodies
    websocket/         connection manager and /ws/wallet
    utils/             money, time, validators, signatures, e-mail, crypto, files
  alembic/versions/    0001_initial_schema.py (the ONLY way tables are created)
  tests/unit/          pure-Python tests (no database needed)
  tests/integration/   API tests against a real MySQL test database
  scripts/seed.py      development seed data
  statements/          generated statements (git-ignored)
```

Tables are created **only through Alembic**. `Base.metadata.create_all()` is never used.

## Setup (local)

Requirements: Python 3.12, MySQL 8.

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # then edit DATABASE_URL, JWT_SECRET_KEY, SMTP, Razorpay keys
```

Create the databases (names are examples):

```sql
CREATE DATABASE digital_wallet CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE digital_wallet_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'wallet_user'@'%' IDENTIFIED BY 'wallet_password';
GRANT ALL ON digital_wallet.* TO 'wallet_user'@'%';
GRANT ALL ON digital_wallet_test.* TO 'wallet_user'@'%';
```

> The ledger immutability triggers in the migration need `SUPER` or `log_bin_trust_function_creators=1` when binary logging is on. If the triggers cannot be created the migration logs a warning and continues: immutability is then still enforced by the ORM, but add the triggers yourself for defence in depth.

Run migrations, seed (optional) and start the server:

```bash
alembic upgrade head
python scripts/seed.py              # dev only: admin / user / merchant + funded wallets
uvicorn app.main:app --reload
```

Interactive docs: <http://localhost:8000/docs>. Health: `GET /health`.

Seeded accounts (development only; the script refuses to run when `APP_ENV=production`):

| Role | Email | Password |
|------|-------|----------|
| admin | admin@example.com | Admin@12345 |
| user | asha@example.com | User@12345 |
| merchant | store@example.com | Merchant@12345 |

The seeded user and merchant have transaction PIN `7391` and a ₹5000 balance.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

The `api` container waits for MySQL, runs `alembic upgrade head` and then starts Uvicorn on port 8000. MySQL is published on host port 3307.

## Running the tests

The suite uses a **separate** MySQL database (its name must contain `test`). The schema is built by running the real Alembic migration, and all tables are truncated between tests.

```bash
export TEST_DATABASE_URL="mysql+pymysql://wallet_user:wallet_password@localhost:3306/digital_wallet_test"
pytest                       # everything
pytest tests/unit            # no database needed
pytest tests/integration -x  # API + concurrency + jobs + migration drift
```

Test mode (`APP_ENV=test`, set automatically by `tests/conftest.py`) sends no real e-mail (messages are captured in `app.utils.email.OUTBOX`), uses a low bcrypt cost and disables the scheduler. Razorpay tests replace the SDK client with a fake, so no network is used.

## Authentication and roles

`POST /auth/register` (user or merchant), `POST /auth/login` returns a 30 minute JWT. Send it as `Authorization: Bearer <token>`. Admins are created with the seed script (or directly in the database) and cannot register publicly. Payment endpoints are for `user` and `merchant` roles only; `admin` uses the `/admin` and `/reports` APIs.

Status codes: 200/201 success, 400 business rule, 401 unauthenticated, 403 forbidden / wrong PIN / OTP missing, 404 not found, 409 conflict, 422 validation, 423 locked or frozen.

## API overview

| Area | Endpoints |
|------|-----------|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Wallet / KYC | `GET /wallet`, `POST /kyc`, `GET /kyc`, `PUT /admin/kyc/{id}/approve`, `PUT /admin/kyc/{id}/reject`, `GET /admin/kyc`, `PUT /admin/wallets/{id}/freeze`, `PUT /admin/wallets/{id}/unfreeze`, `GET /admin/wallets` |
| PIN | `POST /wallet/pin`, `PUT /wallet/pin/change`, `POST /wallet/pin/reset` |
| OTP | `POST /otp/send`, `POST /otp/verify` (purposes: `pin_reset`, `transfer`, `bank_account`, `scheduled_payment`) |
| Add money | `POST /wallet/add-money` |
| Transfers | `POST /transfers`, `GET /transfers/{ref}` |
| Merchant | `GET /merchants/me/qr`, `POST /payments/merchant`, `GET /merchants/me/payments`, `POST /payments/{ref}/refund` |
| Money requests | `POST /money-requests`, `GET /money-requests`, `PUT /money-requests/{id}/pay`, `/decline`, `/cancel` |
| Bank accounts | `POST /bank-accounts`, `GET /bank-accounts`, `DELETE /bank-accounts/{id}` |
| Withdrawals | `POST /withdrawals`, `GET /withdrawals` |
| Fraud review | `GET /admin/flagged-transactions`, `PUT /admin/transactions/{ref}/approve`, `PUT /admin/transactions/{ref}/reject` |
| History | `GET /transactions` (filters `type`, `status`, `min_amount`, `max_amount`, `from_date`, `to_date`, `sort_by`, `order`, `skip`, `limit`), `GET /transactions/{ref}` |
| Statements | `GET /statements?month=YYYY-MM&format=pdf|csv` |
| Reports | `GET /reports/admin-dashboard`, `/ledger-summary`, `/merchant-sales`, `/my-spending` |
| Scheduled payments | `POST/GET /scheduled-payments`, `GET/PUT/DELETE /scheduled-payments/{id}` |
| Bills | `POST/GET /bill-payments`, `GET /bill-payments/{id}` |
| Razorpay | `POST /wallet/razorpay-order`, `POST /wallet/razorpay-confirm`, `POST /webhooks/razorpay` |
| Notifications | `GET /notifications` |
| WebSocket | `WS /ws/wallet?token=<JWT>` |

### Idempotency

Send `Idempotency-Key: <uuid>` on: add-money, transfers, merchant payments, refunds, paying a money request, withdrawals, bill payments and Razorpay confirm.

- same key + same body: the stored response is replayed with header `Idempotent-Replayed: true` (no money moves again)
- same key + different body: `422`
- same key while the first request is still processing: `409`
- keys expire after 24 hours (daily cleanup job)

### Rules worth knowing

| Rule | Value |
|------|-------|
| KYC None / Minimum / Full max balance | ₹10,000 / ₹50,000 / ₹2,00,000 |
| KYC daily limit | ₹10,000 / ₹25,000 / ₹1,00,000 |
| KYC monthly limit | ₹20,000 / ₹1,00,000 / ₹5,00,000 |
| OTP required for transfers above | ₹5,000 |
| Transfer placed On Hold for admin review | above ₹20,000, or more than 5 transfers in a minute |
| Platform fee / cashback | 1 % / 2 % capped at ₹50, credited after 24 h |
| Refund window | 7 days (full or partial, fee refunded proportionally) |
| Withdrawal | Full KYC for users, minimum ₹100, settled by the 5 minute job |
| Simulated failures | bank account ending `0000` fails a withdrawal (and is reversed); mobile / consumer identifier ending `0000` fails a bill |

### Ledger accounts

User Wallet, Merchant Wallet, Bank Settlement, Cashback Pool, Fees, Withdrawal Clearing and Hold. A transfer debits the sender's wallet account and credits the receiver's; a held transfer credits **Hold** instead until an admin approves (credit receiver) or rejects (reverse to the sender). Entries are never updated or deleted (ORM guard plus best-effort MySQL triggers); a correction is always a new reversing transaction. `GET /reports/ledger-summary` and the daily reconciliation job verify that total debits equal total credits and that every wallet balance equals its ledger balance.

## Background jobs

| Job | Schedule |
|-----|----------|
| Cashback credit | hourly |
| Withdrawal processing | every 5 minutes |
| Money request expiry (48 h) | hourly |
| OTP cleanup | daily 02:00 UTC |
| Idempotency key cleanup | daily 02:30 UTC |
| Ledger reconciliation (admins notified on mismatch) | daily 03:00 UTC |
| Scheduled payment execution | every minute |

With several Uvicorn workers only the worker that obtains the MySQL advisory lock `digital_wallet_scheduler` starts the scheduler. Every job is also idempotent (row locks with `SKIP LOCKED` and status transitions). Set `SCHEDULER_ENABLED=false` to disable the scheduler in a process.

## E-mail

E-mails (OTP, login alert, transfers, KYC, freeze, withdrawals, ...) are sent with `smtplib` from FastAPI `BackgroundTasks` after the database commit. A failing SMTP server is logged and never rolls back a financial operation. With empty `SMTP_HOST` nothing is sent.

## Razorpay (test mode)

Fill `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` with **test** keys.

1. `POST /wallet/razorpay-order` creates an order
2. After checkout call `POST /wallet/razorpay-confirm` with the three Razorpay values. The signature is verified, the payment is fetched from Razorpay (and captured if only authorized) and the wallet is credited exactly once
3. Configure the webhook URL `https://<host>/webhooks/razorpay` (events `payment.captured`, `order.paid`, `payment.failed`). The raw body HMAC is verified and events are de-duplicated by event id, so a webhook and a confirm call racing each other cannot double credit

## WebSocket

Connect to `ws://localhost:8000/ws/wallet?token=<JWT>` (or send an `Authorization: Bearer` header). Invalid tokens are closed with code 1008. Messages are JSON such as `{"event": "payment_received", "amount": "100.00", "balance": "..."}`. Send `ping` to get `{"event": "pong"}`. Users only ever receive their own events.

## Security notes

- Passwords and PINs are bcrypt hashes; OTPs are HMAC hashes; bank account numbers are Fernet encrypted (derived from `JWT_SECRET_KEY`: change it before storing real data and never rotate it casually) and only masked values are returned
- Set a strong `JWT_SECRET_KEY`; the app refuses to start in `APP_ENV=production` with the default one
- OTPs are echoed in API responses (`debug_otp`) only when `APP_ENV` is not `production`
- No real secrets are committed; use `.env` (git-ignored)

## Honest status

The code in this archive was written without access to a MySQL server or to PyPI, so the application itself, the migration and the integration test-suite were **not executed by the author**. The 48 pure-Python unit tests (`tests/unit`) were run and pass. Run `alembic upgrade head` and `pytest` as described above; `tests/integration/test_migrations.py` checks that the migration and the models agree.
