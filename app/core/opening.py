# LtBooks — core/opening.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""上年结转 / 期初余额导入。

为什么单独做：客户换系统时手上是一张「上年末科目余额表」——不是发票、不是银行流水，
既有的三种导入都不认得。这里把那张表读成一组科目余额，再用**一条期初分录**落账：

    借 各资产/负债科目（按方向）  ……
    贷 对应方向                 ……
    差额 → 留存收益（retained earnings 科目）

约束：
- 借贷必须平，否则不建分录（不会「先建了再想办法调平」）。
- 科目必须已在账套里存在；匹配不上就报出来，不猜。
- 分录来源标记 opening，可冲销；日期默认本年度第一天。
"""
from __future__ import annotations

import csv
import io
import re

from .db import query

# 列名关键词
COLS = {
    "code": ["科目代码", "科目編碼", "科目编码", "代码", "編號", "编号", "code", "account code", "account"],
    "name": ["科目名称", "科目名稱", "名称", "名稱", "account name", "description"],
    "debit": ["借方", "借方金额", "借方金額", "借", "debit", "dr"],
    "credit": ["贷方", "貸方", "贷方金额", "貸方金額", "贷", "credit", "cr"],
    "net": ["余额", "餘額", "期末余额", "期末餘額", "balance"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _num(s) -> float | None:
    t = str(s or "").strip().replace(",", "").replace(" ", "")
    if t in ("", "-", "—"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def looks_like_trial_balance(text: str) -> bool:
    """科目余额表：有「科目」列，且没有「日期/摘要」这类流水列。"""
    low = (text or "").lower()
    has_acct = any(k in low for k in ("科目代码", "科目編碼", "科目编码", "account code"))
    has_dc = ("借方" in low or "debit" in low) and ("贷方" in low or "credit" in low)
    has_txn = any(k in low for k in ("日期", "date", "摘要", "description", "交易"))
    return has_acct and has_dc and not has_txn


def _detect_header(row) -> dict | None:
    cells = [str(c or "").strip().lower() for c in row]
    mapping = {}
    for key, words in COLS.items():
        for i, c in enumerate(cells):
            if not c:
                continue
            if any(w.lower() in c for w in words):
                mapping[key] = i
                break
    if "code" in mapping and ("debit" in mapping or "credit" in mapping or "net" in mapping):
        return mapping
    return None


def parse_trial_balance(text: str, entity_id: int = 1) -> dict:
    """解析科目余额表 → 行 + 合计 + 告警。"""
    rows = []
    warnings = []
    raw = list(csv.reader(io.StringIO(text)))
    if not raw:
        return {"rows": [], "warnings": ["文件是空的"], "totals": {}}

    header_idx = None
    mapping = None
    for i, r in enumerate(raw[:15]):
        m = _detect_header(r)
        if m:
            header_idx, mapping = i, m
            break
    if mapping is None:
        return {"rows": [], "warnings": ["没找到表头（需要「科目代码 + 借方/贷方」这类列）"],
                "totals": {}}

    accounts = {str(a["account_code"]): dict(a) for a in
                query("SELECT account_code, account_name, category, normal_balance "
                      "FROM accounts WHERE entity_id=%s", (entity_id,))}
    by_name = {str(a["account_name"]).strip(): dict(a) for a in accounts.values()}

    dr = cr = 0.0
    for r in raw[header_idx + 1:]:
        if not any(str(c).strip() for c in r):
            continue
        code = _norm(r[mapping["code"]]) if mapping.get("code") is not None and mapping["code"] < len(r) else ""
        name = _norm(r[mapping["name"]]) if mapping.get("name") is not None and mapping["name"] < len(r) else ""
        d = _num(r[mapping["debit"]]) if mapping.get("debit") is not None and mapping["debit"] < len(r) else None
        c = _num(r[mapping["credit"]]) if mapping.get("credit") is not None and mapping["credit"] < len(r) else None
        net = _num(r[mapping["net"]]) if mapping.get("net") is not None and mapping["net"] < len(r) else None

        if d is None and c is None and net is not None:
            d, c = (net, None) if net >= 0 else (None, -net)
        if d is None and c is None:
            continue
        if not code and not name:
            continue

        acct = accounts.get(code) or by_name.get(name)
        rows.append({
            "code": code or (acct["account_code"] if acct else ""),
            "name": name or (acct["account_name"] if acct else ""),
            "debit": round(d or 0, 2),
            "credit": round(c or 0, 2),
            "matched": bool(acct),
        })
        dr += d or 0
        cr += c or 0

    if not rows:
        warnings.append("没读到任何科目行，请确认导出的是「科目余额表」而不是流水")
    diff = round(dr - cr, 2)
    if rows and abs(diff) > 0.005:
        warnings.append(f"借方合计 {dr:,.2f} ≠ 贷方合计 {cr:,.2f}，差 {diff:,.2f}")
    unmatched = [r for r in rows if not r["matched"]]
    if unmatched:
        warnings.append(f"{len(unmatched)} 个科目在账套里找不到（如 {unmatched[0]['code'] or unmatched[0]['name']}）")

    return {"rows": rows, "warnings": warnings,
            "totals": {"debit": round(dr, 2), "credit": round(cr, 2),
                       "difference": diff, "count": len(rows),
                       "unmatched": len(unmatched)}}
