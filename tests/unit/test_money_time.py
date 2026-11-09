from datetime import date, datetime, time
from decimal import Decimal

import pytest

from app.utils.money import has_valid_scale, money, percent_of, to_paise
from app.utils.time import (
    add_months,
    local_date_start_utc,
    local_datetime_to_utc,
    month_bounds,
    parse_month,
)


def test_money_rounding_half_up():
    assert money("10.005") == Decimal("10.01")
    assert money("10.004") == Decimal("10.00")
    assert money(5) == Decimal("5.00")


def test_percent_of_platform_fee_and_cashback():
    assert percent_of(Decimal("1000"), Decimal("0.01")) == Decimal("10.00")
    assert percent_of(Decimal("333.33"), Decimal("0.01")) == Decimal("3.33")
    assert percent_of(Decimal("1000"), Decimal("0.02")) == Decimal("20.00")


def test_scale_check_and_paise():
    assert has_valid_scale(Decimal("10.25"))
    assert not has_valid_scale(Decimal("10.255"))
    assert to_paise(Decimal("499.99")) == 49999
    assert to_paise("10") == 1000


def test_parse_month():
    assert parse_month("2026-10") == (2026, 10)
    for bad in ["2026-13", "2026-1", "26-10", "", "2026/10"]:
        with pytest.raises(ValueError):
            parse_month(bad)


def test_ist_boundaries():
    # IST midnight is 18:30 UTC of the previous day.
    assert local_date_start_utc(date(2026, 10, 1)) == datetime(2026, 9, 30, 18, 30)
    start, end = month_bounds(2026, 10)
    assert start == datetime(2026, 9, 30, 18, 30)
    assert end == datetime(2026, 10, 31, 18, 30)
    start, end = month_bounds(2026, 12)
    assert end == datetime(2026, 12, 31, 18, 30)
    assert local_datetime_to_utc(date(2026, 10, 5), time(9, 0)) == datetime(2026, 10, 5, 3, 30)


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1, anchor_day=31) == date(2026, 2, 28)
    assert add_months(date(2026, 2, 28), 1, anchor_day=31) == date(2026, 3, 31)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)
    assert add_months(date(2026, 11, 30), 3, anchor_day=30) == date(2027, 2, 28)
