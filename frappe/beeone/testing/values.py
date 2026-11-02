"""Numbers, dates and tags used by test data."""
import random
import string
import time
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal


def money(x):
    """Round like money (2 places, half up)."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def qty(x):
    """Round a quantity (3 places, half up)."""
    return float(Decimal(str(x)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def make_tag(n=6, alphabet=string.ascii_lowercase + string.digits):
    return "".join(random.choice(alphabet) for _ in range(n))


uid = make_tag


def today():
    return date.today().isoformat()


def add_days(date_str, n):
    return (datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date() + timedelta(days=n)).isoformat()


def month_start(date_str):
    return str(date_str)[:8] + "01"


def wait_until(fn, timeout=30, step=0.5):
    end = time.time() + timeout
    while True:
        value = fn()
        if value:
            return value
        if time.time() > end:
            raise AssertionError(f"wait_until: the condition was not met in {timeout} s")
        time.sleep(step)
