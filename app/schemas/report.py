from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class SystemAccountBalance(BaseModel):
    account_type: str
    total_debits: Decimal
    total_credits: Decimal
    net_balance: Decimal


class AdminDashboardOut(BaseModel):
    report_date: date
    total_money_in_wallets: Decimal
    todays_transaction_count: int
    todays_transaction_volume: Decimal
    failed_transactions_today: int
    failed_transactions_total: int
    on_hold_transactions: int
    cashback_paid_total: Decimal
    system_accounts: list[SystemAccountBalance]
    total_ledger_debits: Decimal
    total_ledger_credits: Decimal
    ledger_balanced: bool


class WalletMismatch(BaseModel):
    wallet_id: int
    wallet_balance: Optional[str] = None
    ledger_balance: str


class LedgerSummaryOut(BaseModel):
    accounts: list[SystemAccountBalance]
    total_debits: Decimal
    total_credits: Decimal
    balanced: bool
    wallet_mismatches: list[WalletMismatch]
    reconciled: bool


class DailySales(BaseModel):
    date: date
    payments: int
    gross_sales: Decimal
    fees: Decimal
    net_sales: Decimal


class MerchantSalesOut(BaseModel):
    merchant_code: Optional[str] = None
    from_date: date
    to_date: date
    daily: list[DailySales]
    total_payments: int
    total_gross_sales: Decimal
    total_fees: Decimal
    total_net_sales: Decimal
    total_refunds: Decimal
    fees_refunded: Decimal


class SpendingByType(BaseModel):
    type: str
    count: int
    total: Decimal


class MySpendingOut(BaseModel):
    month: str
    total_spent: Decimal
    transaction_count: int
    by_type: list[SpendingByType]
    cashback_earned: Decimal
    total_received: Decimal
