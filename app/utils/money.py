"""Decimal helpers. Money is always Decimal, never float."""
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def to_decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value) -> Decimal:
    """Quantize to two decimal places using banker-neutral half-up rounding."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def percent_of(amount, rate) -> Decimal:
    return money(to_decimal(amount) * to_decimal(rate))


def has_valid_scale(value: Decimal) -> bool:
    """True when the value has at most two decimal places."""
    return value == value.quantize(CENT)


def to_paise(value) -> int:
    return int((to_decimal(value) * 100).to_integral_value(rounding=ROUND_HALF_UP))
