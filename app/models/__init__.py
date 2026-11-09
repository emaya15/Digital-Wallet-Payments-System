"""Import every model so Base.metadata is complete (needed by Alembic and the ORM)."""
from app.models.bank_account import BankAccount
from app.models.bill_payment import BillPayment
from app.models.cashback import Cashback
from app.models.fraud import FraudReview
from app.models.idempotency import IdempotencyKey
from app.models.kyc import KYC
from app.models.ledger import LedgerAccount, LedgerEntry, LedgerImmutableError
from app.models.merchant_payment import MerchantPayment
from app.models.money_request import MoneyRequest
from app.models.notification import Notification
from app.models.otp import OTP
from app.models.pin import TransactionPin
from app.models.razorpay import RazorpayOrder, WebhookEvent
from app.models.refund import Refund
from app.models.scheduled_payment import ScheduledPayment, ScheduledPaymentExecution
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.models.withdrawal import Withdrawal

__all__ = [
    "BankAccount",
    "BillPayment",
    "Cashback",
    "FraudReview",
    "IdempotencyKey",
    "KYC",
    "LedgerAccount",
    "LedgerEntry",
    "LedgerImmutableError",
    "MerchantPayment",
    "MoneyRequest",
    "Notification",
    "OTP",
    "TransactionPin",
    "RazorpayOrder",
    "WebhookEvent",
    "Refund",
    "ScheduledPayment",
    "ScheduledPaymentExecution",
    "Transaction",
    "User",
    "Wallet",
    "Withdrawal",
]
