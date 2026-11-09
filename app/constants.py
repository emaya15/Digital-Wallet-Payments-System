"""Business constants shared across the application."""
from decimal import Decimal


class Role:
    USER = "user"
    MERCHANT = "merchant"
    ADMIN = "admin"


class KycLevel:
    NONE = "None"
    MINIMUM = "Minimum"
    FULL = "Full"


KYC_RANK = {KycLevel.NONE: 0, KycLevel.MINIMUM: 1, KycLevel.FULL: 2}

# Wallet balance cap, daily and monthly outgoing limits per KYC level (INR).
KYC_LIMITS = {
    KycLevel.NONE: {
        "max_balance": Decimal("10000.00"),
        "daily_limit": Decimal("10000.00"),
        "monthly_limit": Decimal("20000.00"),
    },
    KycLevel.MINIMUM: {
        "max_balance": Decimal("50000.00"),
        "daily_limit": Decimal("25000.00"),
        "monthly_limit": Decimal("100000.00"),
    },
    KycLevel.FULL: {
        "max_balance": Decimal("200000.00"),
        "daily_limit": Decimal("100000.00"),
        "monthly_limit": Decimal("500000.00"),
    },
}


class KycStatus:
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class TxnType:
    ADD_MONEY = "Add Money"
    P2P = "P2P Transfer"
    MERCHANT_PAYMENT = "Merchant Payment"
    REFUND = "Refund"
    CASHBACK = "Cashback"
    WITHDRAWAL = "Withdrawal"
    WITHDRAWAL_REVERSAL = "Withdrawal Reversal"
    MONEY_REQUEST_PAYMENT = "Money Request Payment"
    BILL_PAYMENT = "Bill Payment"
    SCHEDULED_PAYMENT = "Scheduled Payment"
    REVERSAL = "Reversal"


ALL_TXN_TYPES = [
    TxnType.ADD_MONEY,
    TxnType.P2P,
    TxnType.MERCHANT_PAYMENT,
    TxnType.REFUND,
    TxnType.CASHBACK,
    TxnType.WITHDRAWAL,
    TxnType.WITHDRAWAL_REVERSAL,
    TxnType.MONEY_REQUEST_PAYMENT,
    TxnType.BILL_PAYMENT,
    TxnType.SCHEDULED_PAYMENT,
    TxnType.REVERSAL,
]

# Transaction types that count against the user's daily / monthly outgoing limits.
OUTGOING_LIMIT_TYPES = [
    TxnType.P2P,
    TxnType.MERCHANT_PAYMENT,
    TxnType.WITHDRAWAL,
    TxnType.MONEY_REQUEST_PAYMENT,
    TxnType.BILL_PAYMENT,
    TxnType.SCHEDULED_PAYMENT,
]

# Transfer-like types that go through fraud checks.
FRAUD_CHECKED_TYPES = [
    TxnType.P2P,
    TxnType.MONEY_REQUEST_PAYMENT,
    TxnType.SCHEDULED_PAYMENT,
]


class TxnStatus:
    PENDING = "Pending"
    SUCCESS = "Success"
    FAILED = "Failed"
    ON_HOLD = "On Hold"
    REJECTED = "Rejected"


ALL_TXN_STATUSES = [
    TxnStatus.PENDING,
    TxnStatus.SUCCESS,
    TxnStatus.FAILED,
    TxnStatus.ON_HOLD,
    TxnStatus.REJECTED,
]

# Statuses that still count towards limits (money has left or is committed).
LIMIT_COUNTED_STATUSES = [TxnStatus.SUCCESS, TxnStatus.ON_HOLD, TxnStatus.PENDING]


class AccountType:
    USER_WALLET = "User Wallet"
    MERCHANT_WALLET = "Merchant Wallet"
    BANK_SETTLEMENT = "Bank Settlement"
    CASHBACK_POOL = "Cashback Pool"
    FEES = "Fees"
    WITHDRAWAL_CLEARING = "Withdrawal Clearing"
    HOLD = "Hold"


SYSTEM_ACCOUNT_TYPES = [
    AccountType.BANK_SETTLEMENT,
    AccountType.CASHBACK_POOL,
    AccountType.FEES,
    AccountType.WITHDRAWAL_CLEARING,
    AccountType.HOLD,
]


class Side:
    DEBIT = "Debit"
    CREDIT = "Credit"


class OtpPurpose:
    PIN_RESET = "pin_reset"
    TRANSFER = "transfer"
    BANK_ACCOUNT = "bank_account"
    SCHEDULED_PAYMENT = "scheduled_payment"


OTP_PURPOSES = [
    OtpPurpose.PIN_RESET,
    OtpPurpose.TRANSFER,
    OtpPurpose.BANK_ACCOUNT,
    OtpPurpose.SCHEDULED_PAYMENT,
]

PAYMENT_METHODS = ["UPI", "Card", "Net Banking"]

# ----- Amount rules -----
ADD_MONEY_MIN = Decimal("10.00")
ADD_MONEY_MAX = Decimal("50000.00")
TRANSFER_MIN = Decimal("1.00")
TRANSFER_MAX = Decimal("100000.00")
OTP_REQUIRED_ABOVE = Decimal("5000.00")
FRAUD_AMOUNT_THRESHOLD = Decimal("20000.00")
FRAUD_BURST_COUNT = 5  # more than this many transfers in the window triggers a hold
FRAUD_BURST_WINDOW_SECONDS = 60
MIN_WITHDRAWAL = Decimal("100.00")
LOW_BALANCE_THRESHOLD = Decimal("100.00")

# ----- Merchant rules -----
PLATFORM_FEE_RATE = Decimal("0.01")
CASHBACK_RATE = Decimal("0.02")
CASHBACK_MAX = Decimal("50.00")
CASHBACK_DELAY_HOURS = 24
REFUND_WINDOW_DAYS = 7

# ----- Security rules -----
PIN_MAX_ATTEMPTS = 3
PIN_LOCK_MINUTES = 30
OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 3
OTP_RESEND_SECONDS = 60
IDEMPOTENCY_TTL_HOURS = 24

# ----- Misc rules -----
MAX_BANK_ACCOUNTS = 3
MONEY_REQUEST_EXPIRY_HOURS = 48
MAX_PENDING_REQUESTS_PER_PAYER = 5

BILL_TYPES = ["Mobile Recharge", "Electricity"]
MOBILE_OPERATORS = ["Airtel", "Jio", "Vi", "BSNL"]
ELECTRICITY_BOARDS = ["TNEB", "BESCOM", "MSEDCL", "KSEB", "TPDDL"]
