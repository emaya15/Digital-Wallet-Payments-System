"""Pure validation / masking helpers (no framework dependencies)."""
import re

_PHONE_RE = re.compile(r"^(?:\+91|91|0)?([6-9]\d{9})$")
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_ACCOUNT_RE = re.compile(r"^\d{9,18}$")
_PIN_RE = re.compile(r"^\d{4}$")

_COMMON_PINS = {"2580", "1004", "2000", "0852", "1590"}


def normalize_phone(raw: str) -> str:
    """Return the 10 digit Indian mobile number or raise ValueError."""
    cleaned = re.sub(r"[\s\-()]", "", raw or "")
    match = _PHONE_RE.match(cleaned)
    if not match:
        raise ValueError("Invalid phone number. Use a 10 digit Indian mobile number.")
    return match.group(1)


def is_valid_pan(pan: str) -> bool:
    return bool(_PAN_RE.match(pan or ""))


def is_valid_ifsc(ifsc: str) -> bool:
    return bool(_IFSC_RE.match(ifsc or ""))


def is_valid_account_number(number: str) -> bool:
    if not _ACCOUNT_RE.match(number or ""):
        return False
    return len(set(number)) > 1  # reject 000000000 / 111111111 style numbers


def is_valid_pin_format(pin: str) -> bool:
    return bool(_PIN_RE.match(pin or ""))


def is_simple_pin(pin: str) -> bool:
    """Reject trivially guessable four digit PINs.

    Rejected: repeated digits (1111), any constant-step run (1234, 4321, 2468,
    1357), repeated pairs (1212, 1122) and a few well known keypad patterns.
    """
    if not is_valid_pin_format(pin):
        return True
    digits = [int(c) for c in pin]
    steps = {digits[i + 1] - digits[i] for i in range(3)}
    if len(steps) == 1:
        return True
    if pin[:2] == pin[2:]:
        return True
    if pin[0] == pin[1] and pin[2] == pin[3]:
        return True
    return pin in _COMMON_PINS


def validate_password_strength(password: str) -> str:
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must contain at least one letter and one digit.")
    return password


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 4:
        return "XXXX"
    return phone[:2] + "X" * (len(phone) - 4) + phone[-2:]


def mask_account_number(last4: str) -> str:
    return "XXXXXXXX" + (last4 or "")


def mask_pan(pan: str) -> str:
    if not pan:
        return ""
    return "X" * (len(pan) - 4) + pan[-4:]
