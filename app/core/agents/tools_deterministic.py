# LtBooks — core/agents/tools_deterministic.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""守门人工具的确定性内核（Python 移植）。

与 DSH 版本逐条对应：
  journal_check                ← lib/journal.mjs
  variance_bridge              ← lib/variance.mjs
  reconciliation_snapshot      ← lib/recon.mjs（简化版，保留关键判定）
  sql_readonly                 ← lib/sql.mjs

铁律：
  - 只做机械校验，不做准则判断、不推断科目、不写任何存储
  - PASS 仅表示机械校验通过，永远不等于授权过账
"""
from __future__ import annotations

from .money import from_cents, is_finite_number, over_precise, sum_cents

NEVER = "NEVER_AUTHORIZES_POSTING"
DISCLAIMER = "AI-assisted, subject to human review"


def _arr(v):
    return v if isinstance(v, list) else []


def _s(v):
    return isinstance(v, str) and v.strip() != ""


# ---------------------------------------------------------------- 分录校验
def journal_check(entry) -> dict:
    src = entry if isinstance(entry, dict) else {}
    lines = _arr(src.get("lines"))

    structure, review = [], []
    debits, credits = [], []

    if not lines:
        structure.append("分录没有任何行（lines 为空）")

    for i, ln in enumerate(lines, start=1):
        pos = f"第 {i} 行"
        if not isinstance(ln, dict):
            structure.append(f"{pos}不是对象")
            continue

        account = ln.get("accountCode", ln.get("account"))
        if not _s(account):
            structure.append(f"{pos}缺少科目代码（accountCode）")

        debit, credit = ln.get("debit"), ln.get("credit")
        has_d = debit is not None
        has_c = credit is not None
        if not has_d and not has_c:
            structure.append(f"{pos}借贷两栏都为空")
            continue

        for side, val in (("借方", debit), ("贷方", credit)):
            if val is None:
                continue
            if not is_finite_number(val):
                structure.append(f"{pos}{side}金额不是有限数值")
            elif val < 0:
                structure.append(f"{pos}{side}金额为负数（应改用相反方向录入）")
            elif val == 0:
                review.append(f"{pos}{side}金额为 0，行可能多余")
            elif over_precise(val):
                review.append(f"{pos}{side}金额超过两位小数")

        if is_finite_number(debit) and is_finite_number(credit) and debit > 0 and credit > 0:
            structure.append(f"{pos}借贷两栏同时有正数金额")
        if is_finite_number(debit) and is_finite_number(credit) and debit == 0 and credit == 0:
            structure.append(f"{pos}借贷两栏都是 0")

        debits.append(debit if is_finite_number(debit) else 0)
        credits.append(credit if is_finite_number(credit) else 0)

    d_cents = sum_cents(debits)
    c_cents = sum_cents(credits)
    diff = None if d_cents is None or c_cents is None else d_cents - c_cents
    balanced = diff == 0

    # 文档缺口
    required = [x for x in _arr(src.get("requiredDocuments")) if _s(x)]
    provided = [str(d.get("type") or "").strip()
                for d in _arr(src.get("documents")) if isinstance(d, dict)]
    provided = [x for x in provided if x]
    missing = [t for t in required if t not in provided]
    if not required:
        doc_status = "NOT_EVALUATED"
        review.append("未提供 requiredDocuments，无法判定文档完整性")
    elif missing:
        doc_status = "GAPS"
        for t in missing:
            review.append(f"缺少支持性文档：{t}")
    else:
        doc_status = "COMPLETE"

    # 职责分离
    prep = src.get("preparedBy").strip() if _s(src.get("preparedBy")) else None
    rev = src.get("reviewedBy").strip() if _s(src.get("reviewedBy")) else None
    if prep and rev:
        seg = "NOT_SEPARATED" if prep == rev else "SEPARATED"
    else:
        seg = "UNCONFIGURED"
    if seg == "NOT_SEPARATED":
        review.append("制单人与审核人为同一人，职责未分离")
    if seg == "UNCONFIGURED":
        review.append("制单人或审核人未配置，职责分离无法确认")

    # 外币折算
    fc = src.get("currency").strip().upper() if _s(src.get("currency")) else None
    func = src.get("functionalCurrency").strip().upper() if _s(src.get("functionalCurrency")) else None
    rate = src.get("exchangeRate")
    needs = bool(fc and func and fc != func)
    if needs and not is_finite_number(rate):
        review.append(f"外币 {fc} 未提供折算汇率（exchangeRate）")
    if (not needs) and fc and func and fc == func and is_finite_number(rate) and rate != 1:
        review.append("本位币分录却提供了非 1 的汇率")

    functional_totals = None
    if needs and is_finite_number(rate) and d_cents is not None and c_cents is not None:
        functional_totals = {
            "debit": from_cents(round(d_cents * rate)),
            "credit": from_cents(round(c_cents * rate)),
            "rate": rate,
        }

    blocked = list(structure)
    if not balanced:
        blocked.append("借贷不平衡")

    verdict = "FAIL" if blocked else ("REVIEW" if review else "PASS")

    return {
        "task": "journal_entry_check",
        "entryId": src.get("entryId").strip() if _s(src.get("entryId")) else None,
        "entryDate": src.get("entryDate").strip() if _s(src.get("entryDate")) else None,
        "currency": fc,
        "functionalCurrency": func,
        "lineCount": len(lines),
        "debitTotal": from_cents(d_cents),
        "creditTotal": from_cents(c_cents),
        "difference": from_cents(diff),
        "balanced": balanced,
        "functionalTotals": functional_totals,
        "structure": {"ok": not structure, "issues": structure},
        "documents": {"status": doc_status, "required": required,
                      "provided": provided, "missing": missing},
        "segregation": {"preparedBy": prep, "reviewedBy": rev, "status": seg},
        "verdict": verdict,
        "blockedReasons": blocked,
        "reviewReasons": review,
        "authorization": NEVER,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- 差异桥接
def variance_bridge(bridge) -> dict:
    src = bridge if isinstance(bridge, dict) else {}
    blockers, review = [], []

    base_cents = sum_cents([src.get("base")])
    if base_cents is None:
        blockers.append("base 不是有限数值")
    actual_cents = sum_cents([src.get("actual")])
    if actual_cents is None:
        blockers.append("actual 不是有限数值")

    rows, driver_cents = [], 0
    for i, d in enumerate(_arr(src.get("drivers")), start=1):
        pos = f"第 {i} 个驱动因素"
        if not isinstance(d, dict):
            blockers.append(f"{pos}不是对象")
            continue
        amt = d.get("amount")
        if not is_finite_number(amt):
            blockers.append(f"{pos} amount 不是有限数值")
            continue
        if over_precise(amt):
            review.append(f"{pos}金额超过两位小数")
        c = round(amt * 100)
        driver_cents += c
        rows.append({"label": str(d.get("label") or pos), "amount": from_cents(c)})

    expected = None
    residual = None
    if base_cents is not None and actual_cents is not None:
        expected = base_cents + driver_cents
        residual = actual_cents - expected

    verdict = "FAIL" if blockers else ("REVIEW" if review or (residual not in (None, 0)) else "PASS")

    return {
        "task": "variance_bridge",
        "base": from_cents(base_cents),
        "drivers": rows,
        "driverTotal": from_cents(driver_cents),
        "expected": from_cents(expected),
        "actual": from_cents(actual_cents),
        # 残差显式暴露，绝不分摊、吸收或隐藏
        "residual": from_cents(residual),
        "residualExplained": residual == 0,
        "verdict": verdict,
        "blockedReasons": blockers,
        "reviewReasons": review,
        "authorization": NEVER,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- 对账快照
def reconciliation_snapshot(snap) -> dict:
    """账面 vs 银行：列未达项，算差额，给结论。差额必须显式暴露。"""
    src = snap if isinstance(snap, dict) else {}
    blockers, review = [], []

    book = sum_cents([src.get("bookBalance")])
    bank = sum_cents([src.get("bankBalance")])
    if book is None:
        blockers.append("bookBalance 不是有限数值")
    if bank is None:
        blockers.append("bankBalance 不是有限数值")

    outstanding = []
    out_cents = 0
    for i, item in enumerate(_arr(src.get("outstandingItems")), start=1):
        if not isinstance(item, dict):
            blockers.append(f"第 {i} 个未达项不是对象")
            continue
        amt = item.get("amount")
        if not is_finite_number(amt):
            blockers.append(f"第 {i} 个未达项金额不是有限数值")
            continue
        c = round(amt * 100)
        out_cents += c
        outstanding.append({"label": str(item.get("label") or f"未达项 {i}"),
                            "amount": from_cents(c)})

    adjusted = None
    gap = None
    if book is not None and bank is not None:
        adjusted = book + out_cents          # 账面调整后
        gap = bank - adjusted                # 仍存在的差额

    if gap not in (None, 0):
        review.append(f"调整后仍差 {from_cents(gap)}，需人工查原因")
    if not outstanding and gap in (None, 0):
        review.append("没有列出未达项，请确认是否真的对平")

    verdict = "FAIL" if blockers else ("REVIEW" if review else "PASS")

    return {
        "task": "reconciliation_snapshot",
        "bookBalance": from_cents(book),
        "outstandingItems": outstanding,
        "outstandingTotal": from_cents(out_cents),
        "adjustedBook": from_cents(adjusted),
        "bankBalance": from_cents(bank),
        "gap": from_cents(gap),
        "verdict": verdict,
        "blockedReasons": blockers,
        "reviewReasons": review,
        "authorization": NEVER,
        "disclaimer": DISCLAIMER,
    }
