"""Tariff arithmetic. Payment collection is deliberately separate from entitlements."""

import re
from calendar import monthrange
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation

FREE_JOBS_PER_WINDOW = 2
SUBSCRIPTION_HOURS = 40
SUBSCRIPTION_PRICE_RUB = 250
MAX_PACK_HOURS = 4

# Marginal price per hour: each additional hour is a little cheaper.
HOURLY_RATES_RUB = (50, 40, 35, 30)


def calendar_month_start(timestamp: float) -> float:
    """UTC start of the calendar month containing a timestamp."""
    date = datetime.fromtimestamp(timestamp, UTC)
    return date.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()


def calendar_month_later(timestamp: float) -> float:
    """Same UTC time next month, clamping dates missing in the next month."""
    date = datetime.fromtimestamp(timestamp, UTC)
    year = date.year + (date.month == 12)
    month = 1 if date.month == 12 else date.month + 1
    day = min(date.day, monthrange(year, month)[1])
    return date.replace(year=year, month=month, day=day).timestamp()


def parse_pack_minutes(text: str) -> int:
    """Accept 1–4 hours, including fractions that represent whole minutes."""
    match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(?:ч(?:ас(?:а|ов)?)?|h(?:our|ours)?)?\s*",
                         text, flags=re.IGNORECASE)
    if not match:
        raise ValueError("Enter a number of hours from 1 to 4")
    try:
        hours = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Enter a number of hours from 1 to 4") from exc
    if not hours.is_finite():
        raise ValueError("Enter a finite number of hours")
    minutes = hours * 60
    if not (Decimal(60) <= minutes <= Decimal(240)) or minutes != minutes.to_integral_value():
        raise ValueError("Enter 1–4 hours with whole-minute precision")
    return int(minutes)


def pack_price_rub(minutes: int) -> int:
    if not 60 <= minutes <= 240:
        raise ValueError("Pack must contain 1–4 hours")
    remaining = minutes
    price = Decimal(0)
    for rate in HOURLY_RATES_RUB:
        block = min(remaining, 60)
        price += Decimal(block * rate) / 60
        remaining -= block
        if remaining == 0:
            break
    return int(price.to_integral_value(rounding=ROUND_CEILING))


def format_hours(minutes: int) -> str:
    if minutes % 60 == 0:
        return str(minutes // 60)
    if minutes % 3 == 0:
        return format((Decimal(minutes) / 60).normalize(), "f")
    return f"{minutes // 60}:{minutes % 60:02d}"
