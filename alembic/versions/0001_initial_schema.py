"""Initial schema: users, wallets, ledger, payments and supporting tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-02
"""
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

MONEY = sa.Numeric(12, 2)


def _ts():
    return [
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def _table(name, *items):
    op.create_table(name, *items, mysql_engine="InnoDB", mysql_default_charset="utf8mb4")


def upgrade() -> None:
    # ------------------------------------------------------------------ users
    _table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(15), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("business_name", sa.String(150), nullable=True),
        sa.Column("business_category", sa.String(100), nullable=True),
        sa.Column("merchant_code", sa.String(20), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)
    op.create_index("ix_users_role", "users", ["role"], unique=False)
    op.create_index("ix_users_merchant_code", "users", ["merchant_code"], unique=True)

    # ---------------------------------------------------------------- wallets
    _table(
        "wallets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("wallet_number", sa.String(20), nullable=False),
        sa.Column("balance", MONEY, nullable=False),
        sa.Column("kyc_level", sa.String(20), nullable=False),
        sa.Column("is_frozen", sa.Boolean(), nullable=False),
        sa.Column("freeze_reason", sa.String(255), nullable=True),
        sa.Column("frozen_by", sa.Integer(), nullable=True),
        sa.Column("frozen_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["frozen_by"], ["users.id"]),
    )
    op.create_index("ix_wallets_user_id", "wallets", ["user_id"], unique=True)
    op.create_index("ix_wallets_wallet_number", "wallets", ["wallet_number"], unique=True)

    # ------------------------------------------------------ transaction_pins
    _table(
        "transaction_pins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("pin_hash", sa.String(255), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("last_changed_at", sa.DateTime(), nullable=False),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.UniqueConstraint("wallet_id"),
    )
    op.create_index("ix_transaction_pins_user_id", "transaction_pins", ["user_id"], unique=True)

    # ------------------------------------------------------------ kyc_records
    _table(
        "kyc_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kyc_type", sa.String(20), nullable=False),
        sa.Column("pan_number", sa.String(10), nullable=True),
        sa.Column("id_proof_type", sa.String(30), nullable=False),
        sa.Column("id_proof_number", sa.String(40), nullable=False),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("rejection_reason", sa.String(255), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
    )
    op.create_index("ix_kyc_records_user_id", "kyc_records", ["user_id"], unique=False)
    op.create_index("ix_kyc_records_status", "kyc_records", ["status"], unique=False)

    # ----------------------------------------------------------- transactions
    _table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_ref", sa.String(30), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("fee", MONEY, nullable=False),
        sa.Column("sender_wallet_id", sa.Integer(), nullable=True),
        sa.Column("receiver_wallet_id", sa.Integer(), nullable=True),
        sa.Column("parent_transaction_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("payment_method", sa.String(30), nullable=True),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        sa.Column("sender_balance_after", MONEY, nullable=True),
        sa.Column("receiver_balance_after", MONEY, nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["sender_wallet_id"], ["wallets.id"]),
        sa.ForeignKeyConstraint(["receiver_wallet_id"], ["wallets.id"]),
        sa.ForeignKeyConstraint(["parent_transaction_id"], ["transactions.id"]),
    )
    op.create_index("ix_transactions_transaction_ref", "transactions", ["transaction_ref"], unique=True)
    op.create_index("ix_transactions_type", "transactions", ["type"], unique=False)
    op.create_index("ix_transactions_status", "transactions", ["status"], unique=False)
    op.create_index(
        "ix_transactions_sender_created", "transactions", ["sender_wallet_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_transactions_receiver_created", "transactions", ["receiver_wallet_id", "created_at"], unique=False
    )

    # -------------------------------------------------------- ledger_accounts
    _table(
        "ledger_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("account_type", sa.String(30), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.UniqueConstraint("wallet_id"),
    )
    op.create_index("ix_ledger_accounts_name", "ledger_accounts", ["name"], unique=True)
    op.create_index("ix_ledger_accounts_account_type", "ledger_accounts", ["account_type"], unique=False)

    # --------------------------------------------------------- ledger_entries
    _table(
        "ledger_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("entry_type", sa.String(10), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["ledger_accounts.id"]),
    )
    op.create_index("ix_ledger_entries_transaction_id", "ledger_entries", ["transaction_id"], unique=False)
    op.create_index(
        "ix_ledger_entries_account_created", "ledger_entries", ["account_id", "created_at"], unique=False
    )

    # ------------------------------------------------------------------- otps
    _table(
        "otps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_otps_expires_at", "otps", ["expires_at"], unique=False)
    op.create_index("ix_otps_user_purpose", "otps", ["user_id", "purpose"], unique=False)

    # ---------------------------------------------------------- bank_accounts
    _table(
        "bank_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_holder_name", sa.String(100), nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=False),
        sa.Column("account_number_encrypted", sa.String(500), nullable=False),
        sa.Column("account_last4", sa.String(4), nullable=False),
        sa.Column("ifsc", sa.String(11), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_bank_accounts_user_id", "bank_accounts", ["user_id"], unique=False)

    # ------------------------------------------------------------ withdrawals
    _table(
        "withdrawals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("reversal_transaction_id", sa.Integer(), nullable=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["reversal_transaction_id"], ["transactions.id"]),
    )
    op.create_index("ix_withdrawals_user_id", "withdrawals", ["user_id"], unique=False)
    op.create_index("ix_withdrawals_status", "withdrawals", ["status"], unique=False)

    # --------------------------------------------------------- money_requests
    _table(
        "money_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("payer_id", sa.Integer(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["payer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
    )
    op.create_index("ix_money_requests_payer_id", "money_requests", ["payer_id"], unique=False)
    op.create_index("ix_money_requests_status", "money_requests", ["status"], unique=False)
    op.create_index("ix_money_requests_expires_at", "money_requests", ["expires_at"], unique=False)
    op.create_index(
        "ix_money_requests_requester_payer", "money_requests", ["requester_id", "payer_id"], unique=False
    )

    #------------------------------------------------------ merchant_payments
    _table(
        "merchant_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("payer_user_id", sa.Integer(), nullable=False),
        sa.Column("merchant_user_id", sa.Integer(), nullable=False),
        sa.Column("merchant_code", sa.String(20), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("fee", MONEY, nullable=False),
        sa.Column("net_amount", MONEY, nullable=False),
        sa.Column("refunded_amount", MONEY, nullable=False),
        sa.Column("fee_refunded", MONEY, nullable=False),
        sa.Column("cashback_amount", MONEY, nullable=False),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["payer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["merchant_user_id"], ["users.id"]),
        sa.UniqueConstraint("transaction_id"),
    )
    op.create_index("ix_merchant_payments_payer_user_id", "merchant_payments", ["payer_user_id"], unique=False)
    op.create_index(
        "ix_merchant_payments_merchant_user_id", "merchant_payments", ["merchant_user_id"], unique=False
    )

    # ---------------------------------------------------------------- refunds
    _table(
        "refunds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("merchant_payment_id", sa.Integer(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("fee_refunded", MONEY, nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("refunded_by", sa.Integer(), nullable=False),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["merchant_payment_id"], ["merchant_payments.id"]),
        sa.ForeignKeyConstraint(["refunded_by"], ["users.id"]),
        sa.UniqueConstraint("transaction_id"),
    )
    op.create_index("ix_refunds_merchant_payment_id", "refunds", ["merchant_payment_id"], unique=False)

    # -------------------------------------------------------------- cashbacks
    _table(
        "cashbacks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("merchant_payment_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("credit_at", sa.DateTime(), nullable=False),
        sa.Column("credited_at", sa.DateTime(), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["merchant_payment_id"], ["merchant_payments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.UniqueConstraint("merchant_payment_id"),
    )
    op.create_index("ix_cashbacks_user_id", "cashbacks", ["user_id"], unique=False)
    op.create_index("ix_cashbacks_status", "cashbacks", ["status"], unique=False)
    op.create_index("ix_cashbacks_credit_at", "cashbacks", ["credit_at"], unique=False)

    # ------------------------------------------------------- idempotency_keys
    _table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("user_id", "key", name="uq_idempotency_user_key"),
    )
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"], unique=False)

    # ---------------------------------------------------------- fraud_reviews
    _table(
        "fraud_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("decision_reason", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.UniqueConstraint("transaction_id"),
    )
    op.create_index("ix_fraud_reviews_status", "fraud_reviews", ["status"], unique=False)

    # ---------------------------------------------------- scheduled_payments
    _table(
        "scheduled_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("receiver_user_id", sa.Integer(), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column("anchor_day", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["receiver_user_id"], ["users.id"]),
    )
    op.create_index("ix_scheduled_payments_user_id", "scheduled_payments", ["user_id"], unique=False)
    op.create_index("ix_scheduled_payments_next_run_at", "scheduled_payments", ["next_run_at"], unique=False)
    op.create_index("ix_scheduled_payments_status", "scheduled_payments", ["status"], unique=False)

    _table(
        "scheduled_payment_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scheduled_payment_id", sa.Integer(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["scheduled_payment_id"], ["scheduled_payments.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
    )
    op.create_index(
        "ix_scheduled_payment_executions_scheduled_payment_id",
        "scheduled_payment_executions",
        ["scheduled_payment_id"],
        unique=False,
    )

    # ---------------------------------------------------------- bill_payments
    _table(
        "bill_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("bill_type", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("customer_identifier", sa.String(30), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reference_number", sa.String(30), nullable=False),
        sa.Column("failure_reason", sa.String(255), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
    )
    op.create_index("ix_bill_payments_user_id", "bill_payments", ["user_id"], unique=False)
    op.create_index("ix_bill_payments_reference_number", "bill_payments", ["reference_number"], unique=True)

    # ---------------------------------------------------------- notifications
    _table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"], unique=False)

    # -------------------------------------------------------- razorpay tables
    _table(
        "razorpay_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("razorpay_order_id", sa.String(64), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(5), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("razorpay_payment_id", sa.String(64), nullable=True),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.UniqueConstraint("razorpay_payment_id"),
    )
    op.create_index("ix_razorpay_orders_user_id", "razorpay_orders", ["user_id"], unique=False)
    op.create_index("ix_razorpay_orders_razorpay_order_id", "razorpay_orders", ["razorpay_order_id"], unique=True)

    _table(
        "webhook_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_events_event_id", "webhook_events", ["event_id"], unique=True)

    _create_ledger_immutability_triggers()


def _create_ledger_immutability_triggers() -> None:
    """Defence in depth: the database itself rejects UPDATE / DELETE on ledger entries.

    Best effort: creating triggers needs the TRIGGER privilege (and, with binary
    logging, either SUPER or log_bin_trust_function_creators). When that is not
    available the ORM-level guard in app.models.ledger still applies.
    """
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    statements = [
        "CREATE TRIGGER trg_ledger_entries_no_update BEFORE UPDATE ON ledger_entries "
        "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Ledger entries are immutable'",
        "CREATE TRIGGER trg_ledger_entries_no_delete BEFORE DELETE ON ledger_entries "
        "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Ledger entries are immutable'",
    ]
    for statement in statements:
        try:
            op.execute(statement)
        except Exception as exc:  # pragma: no cover - depends on DB privileges
            logger.warning("Could not create ledger immutability trigger: %s", exc)


def _drop_ledger_immutability_triggers() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    for name in ("trg_ledger_entries_no_update", "trg_ledger_entries_no_delete"):
        try:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not drop trigger %s: %s", name, exc)


def downgrade() -> None:
    _drop_ledger_immutability_triggers()
    for table in (
        "webhook_events",
        "razorpay_orders",
        "notifications",
        "bill_payments",
        "scheduled_payment_executions",
        "scheduled_payments",
        "fraud_reviews",
        "idempotency_keys",
        "cashbacks",
        "refunds",
        "merchant_payments",
        "money_requests",
        "withdrawals",
        "bank_accounts",
        "otps",
        "ledger_entries",
        "ledger_accounts",
        "transactions",
        "kyc_records",
        "transaction_pins",
        "wallets",
        "users",
    ):
        op.drop_table(table)
