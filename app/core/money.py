# LtBooks — core/money.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""金额运算：全部用 Decimal，避免二进制浮点误差。
非法输入返回 None（绝不静默当 0）。"""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def dec(v):
    """转 Decimal；非法返回 None。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, Decimal):
            return v
        return Decimal(str(v))
    except Exception:
        return None


def money(v):
    """两位小数。"""
    d = dec(v)
    return None if d is None else d.quantize(CENT, rounding=ROUND_HALF_UP)


def to_cents(v):
    d = money(v)
    return None if d is None else int(d * 100)


def from_cents(c):
    return None if c is None else (Decimal(int(c)) / 100).quantize(CENT)


def convert(amount, rate):
    """原币 → 功能货币。rate<=0 或非法返回 None。"""
    a = dec(amount)
    r = dec(rate)
    if a is None or r is None or r <= 0:
        return None
    return (a * r).quantize(CENT, rounding=ROUND_HALF_UP)


def fx_difference(amount, old_rate, new_rate):
    a = convert(amount, old_rate)
    b = convert(amount, new_rate)
    if a is None or b is None:
        return None
    return (b - a).quantize(CENT)


def sum_money(values):
    total = Decimal("0")
    for v in values:
        d = dec(v)
        if d is None:
            return None
        total += d
    return total.quantize(CENT, rounding=ROUND_HALF_UP)


def within_tolerance(a, b, tol="0.01"):
    x, y, t = dec(a), dec(b), dec(tol)
    if x is None or y is None or t is None:
        return None
    return abs(x - y) <= t


def parse_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def days_between(a, b):
    da, db = parse_date(a), parse_date(b)
    if not da or not db:
        return None
    return (db - da).days


def period_end_date(period):
    if not isinstance(period, str) or len(period) < 7:
        return None
    try:
        y, m = int(period[:4]), int(period[5:7])
    except ValueError:
        return None
    if not 1 <= m <= 12:
        return None
    nxt = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    return nxt - timedelta(days=1)


def period_of(d):
    dd = parse_date(d)
    return None if dd is None else dd.strftime("%Y-%m")


def add_years(d, years):
    dd = parse_date(d)
    if dd is None:
        return None
    try:
        return dd.replace(year=dd.year + years)
    except ValueError:  # 2/29
        return dd.replace(year=dd.year + years, day=28)


def retention_until(completion=None, created=None):
    base = parse_date(completion) or parse_date(created)
    return None if base is None else add_years(base, 7)


def j(v):
    """Decimal/date → JSON 友好。"""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    if isinstance(v, list):
        return [j(x) for x in v]
    if isinstance(v, dict):
        return {k: j(x) for k, x in v.items()}
    return v


def quantize_money(v):
    """把金额规整到分（HALF_UP），并告知是否发生了舍入。

    返回 (Decimal, rounded)。非法输入返回 (None, False)。
    显式量化而不是依赖数据库隐式四舍五入 —— 后者不告知用户余额被改动了。
    """
    d = dec(v)
    if d is None:
        return None, False
    q = d.quantize(CENT, rounding=ROUND_HALF_UP)
    return q, (q != d)
