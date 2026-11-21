# LtBooks — core/agents/money.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""金额运算的唯一入口：整数分（cents）运算，避免二进制浮点误差。

与 DSH 守门人的 lib/money.mjs 行为一一对应：
  - 只接受有限数值，拒绝 NaN / Infinity / 字符串数字
  - 求和时任一分量非法就返回 None，绝不把坏数据静默当成 0
"""
from __future__ import annotations

import math
import re
from datetime import date


def is_finite_number(v) -> bool:
    """有限数值才算数；bool 不算（True 会被误当 1）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def to_cents(v):
    if not is_finite_number(v):
        return None
    return int(round(v * 100))


def from_cents(cents):
    if cents is None:
        return None
    return round(int(cents) / 100, 2)


def sum_cents(values):
    total = 0
    for v in values:
        c = to_cents(v)
        if c is None:
            return None
        total += c
    return total


def over_precise(v) -> bool:
    if not is_finite_number(v):
        return False
    return abs(v * 100 - round(v * 100)) > 1e-9


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def parse_date(v):
    if not isinstance(v, str):
        return None
    m = _DATE_RE.match(v.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def days_between(then, as_of):
    a, b = parse_date(then), parse_date(as_of)
    if not a or not b:
        return None
    return (b - a).days
