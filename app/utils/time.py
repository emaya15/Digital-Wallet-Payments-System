"""Time helpers.

All datetimes are stored as naive UTC. Business days / months (limits, reports,
statements) are evaluated in Indian Standard Time (UTC+05:30).
"""
import calendar
import re
from datetime import date, datetime, time, timedelta, timezone

IST_OFFSET = timedelta(hours=5, minutes=30)
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (what the database stores)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt: datetime) -> datetime:
    """Convert a naive UTC datetime to naive IST."""
    return dt + IST_OFFSET


def today_local() -> date:
    return to_local(utcnow()).date()


def local_date_start_utc(d: date) -> datetime:
    """UTC instant at which the IST calendar day ``d`` starts."""
    return datetime(d.year, d.month, d.day) - IST_OFFSET


def local_day_bounds(d: date):
    start = local_date_start_utc(d)
    return start, start + timedelta(days=1)


def local_datetime_to_utc(d: date, at: time) -> datetime:
    return datetime.combine(d, at) - IST_OFFSET


def month_bounds(year: int, month: int):
    """[start, end) in UTC of the IST calendar month."""
    start = local_date_start_utc(date(year, month, 1))
    if month == 12:
        end = local_date_start_utc(date(year + 1, 1, 1))
    else:
        end = local_date_start_utc(date(year, month + 1, 1))
    return start, end


def parse_month(value: str):
    """Parse ``YYYY-MM`` into (year, month). Raises ValueError when invalid."""
    match = _MONTH_RE.match(value or "")
    if not match:
        raise ValueError("month must be in YYYY-MM format")
    return int(match.group(1)), int(match.group(2))


def last_day_of_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(d: date, months: int, anchor_day: int = None) -> date:
    """Add ``months`` to ``d`` keeping ``anchor_day`` (clamped to month length)."""
    day = anchor_day or d.day
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day, last_day_of_month(year, month)))
