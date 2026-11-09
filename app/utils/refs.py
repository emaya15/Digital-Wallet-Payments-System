"""Reference / identifier generators."""
import secrets
import string
import uuid

_ALPHABET = string.ascii_uppercase + string.digits


def new_transaction_ref() -> str:
    return "TXN" + uuid.uuid4().hex[:16].upper()


def new_wallet_number() -> str:
    return "WLT" + "".join(secrets.choice(string.digits) for _ in range(12))


def new_merchant_code() -> str:
    return "MRC" + "".join(secrets.choice(_ALPHABET) for _ in range(8))


def new_bill_reference() -> str:
    return "BILL" + "".join(secrets.choice(_ALPHABET) for _ in range(12))
