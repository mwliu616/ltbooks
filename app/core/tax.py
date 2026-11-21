# LtBooks — core/tax.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""香港利得税计算（按税务局 BIR51 报税表的结构）。

会计利润 → 加回不可扣税开支 → 减非应课税收入 → 经调整的应评税利润
        → 减资本免税额 → 应评税利润 → 两级制税率 → 应缴税款

金额一律用 Decimal；资格未确定时拒绝计税，不自行假定。
"""
import re
from datetime import date

from .db import query, query_one
from .money import dec

TIER_CAP = dec("2000000")     # 两级制首 200 万
TIER1_RATE = dec("0.0825")
TIER2_RATE = dec("0.165")

CATEGORY_LABEL = {
    "add_back": "加：不可扣税开支",
    "deduct": "减：非应课税收入",
    "capital_allowance": "减：资本免税额",
}


def year_of_assessment(period: str) -> str:
    """由基期推算课税年度：香港课税年度为 4 月 1 日至次年 3 月 31 日。
    若基期止于 3 月，课税年度为 (Y-1)/Y；否则为 Y/(Y+1)。"""
    y, m = int(period[:4]), int(period[5:7])
    if m <= 3:
        return f"{y-1}/{str(y)[2:]}"
    return f"{y}/{str(y+1)[2:]}"


def _profits_tax_rates():
    rows = query("""SELECT name, rate FROM tax_rates
                     WHERE tax_type='profits_tax'
                       AND (effective_to IS NULL OR effective_to >= CURDATE())""")
    first = second = None
    for r in rows:
        nm = str(r["name"] or "").lower()
        v = dec(r["rate"])
        if v is None:
            continue
        if "two-tier" in nm or "first" in nm:
            first = v
        elif "remainder" in nm or "flat" in nm:
            second = v
    return (first or TIER1_RATE), (second or TIER2_RATE)


def ya_range(ya: str) -> tuple:
    """把「2025/26」这种课税年度换成基期区间：2025-04-01 ~ 2026-03-31。"""
    m = re.fullmatch(r"(\d{4})\s*/\s*(\d{2,4})", str(ya or "").strip())
    if not m:
        raise ValueError("课税年度格式应为 2025/26")
    y = int(m.group(1))
    return f"{y}-04-01", f"{y + 1}-03-31"


def ya_of_date(d) -> str:
    """某一天属于哪个课税年度（4 月 1 日划年）：2026-03-31 → 2025/26。"""
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}/{(y + 1) % 100:02d}"


def compute(entity, period: str, accounting_profit=None, ya=None):
    """生成完整的利得税计算表。period 为基期止月（YYYY-MM）。

    会计利润按**基期**取（4/1–次年 3/31），不是全历史：
    否则跨年的凭证会被重复计算。
    """
    eid = entity["entity_id"]
    lines = query("""SELECT line_id, category, item_name, amount, basis_note
                       FROM tax_adjustment_lines
                      WHERE entity_id=%s AND period=%s
                      ORDER BY category, line_id""", (eid, period))

    add_back = [dict(r, amount=dec(r["amount"])) for r in lines if r["category"] == "add_back"]
    deduct = [dict(r, amount=dec(r["amount"])) for r in lines if r["category"] == "deduct"]
    capital = [dict(r, amount=dec(r["amount"])) for r in lines if r["category"] == "capital_allowance"]

    if accounting_profit is None:
        from .service import load_rules  # noqa: F401  仅为保持导入一致性
        from .reports import profit_and_loss
        if ya:
            _ys, _ye = ya_range(ya)
            accounting = dec(profit_and_loss(eid, _ys, _ye)["netProfit"])
        else:
            accounting = dec(profit_and_loss(eid)["netProfit"])
    else:
        accounting = dec(accounting_profit)
    if accounting is None:
        raise ValueError("会计利润非法")

    sum_add = sum((x["amount"] for x in add_back), dec(0))
    sum_ded = sum((x["amount"] for x in deduct), dec(0))
    sum_cap = sum((x["amount"] for x in capital), dec(0))

    _ys = _ye = None
    if ya:
        _ys, _ye = ya_range(ya)
    adjusted = accounting + sum_add - sum_ded
    assessable = adjusted - sum_cap

    status = entity["two_tier_status"]
    tier1_rate, tier2_rate = _profits_tax_rates()

    if status == "undetermined":
        return {
            "period": period, "yearOfAssessment": year_of_assessment(period),
            "computed": False, "twoTierStatus": status,
            "accountingProfit": float(accounting),
            "addBacks": [dict(x, amount=float(x["amount"])) for x in add_back],
            "deducts": [dict(x, amount=float(x["amount"])) for x in deduct],
            "capitalAllowances": [dict(x, amount=float(x["amount"])) for x in capital],
            "totalAddBack": float(sum_add), "totalDeduct": float(sum_ded),
            "totalCapitalAllowance": float(sum_cap),
            "adjustedAssessable": float(adjusted), "assessableProfit": float(assessable),
            "taxPayable": None,
            "reason": "实体两级制税率资格未确定（undetermined）；按规不得自行假定，须先确认资格",
            "note": "以下中间数据仅供核对，不含税额",
        }

    if status == "nominated":
        tier1_profit = min(assessable, TIER_CAP) if assessable > 0 else dec(0)
        tier2_profit = max(assessable - TIER_CAP, dec(0))
        tax = tier1_profit * tier1_rate + tier2_profit * tier2_rate
    else:  # not_nominated：全部按标准税率
        tier1_profit = dec(0)
        tier2_profit = max(assessable, dec(0))
        tax = tier2_profit * tier2_rate

    tax = tax.quantize(dec("0.01"))
    provisional = dec(0)
    last = query_one("""SELECT provisional_tax_paid FROM tax_adjustments
                         WHERE entity_id=%s AND period=%s ORDER BY adjustment_id DESC LIMIT 1""",
                     (eid, period))
    if last:
        provisional = dec(last["provisional_tax_paid"] or 0)

    return {
        "period": period,
        "yearOfAssessment": ya or year_of_assessment(period),
        "computed": True,
        "twoTierStatus": status,
        "twoTierApplied": status == "nominated",
        "accountingProfit": float(accounting),
        "addBacks": [dict(x, amount=float(x["amount"])) for x in add_back],
        "deducts": [dict(x, amount=float(x["amount"])) for x in deduct],
        "capitalAllowances": [dict(x, amount=float(x["amount"])) for x in capital],
        "totalAddBack": float(sum_add),
        "totalDeduct": float(sum_ded),
        "totalCapitalAllowance": float(sum_cap),
        "adjustedAssessable": float(adjusted),
        "assessableProfit": float(assessable),
        "tier1Cap": float(TIER_CAP),
        "tier1Rate": float(tier1_rate), "tier2Rate": float(tier2_rate),
        "tier1Profit": float(tier1_profit), "tier2Profit": float(tier2_profit),
        "taxPayable": float(tax),
        "provisionalTaxPaid": float(provisional),
        "balancePayable": float(tax - provisional),
        "lossCarriedForward": float(-assessable) if assessable < 0 else 0.0,
        "note": ("应评税利润为正，按两级制计税" if assessable > 0
                 else "应评税利润为负，属税务亏损，可无限期结转抵销未来年度利润"),
    }


def add_line(entity, period, category, item_name, amount, basis_note, actor="system"):
    if category not in ("add_back", "deduct", "capital_allowance"):
        raise ValueError("类别只能是 add_back / deduct / capital_allowance")
    if not item_name.strip():
        raise ValueError("必须填写项目名称")
    v = dec(amount)
    if v is None or v < 0:
        raise ValueError("金额必须是非负数")
    from .db import transaction
    from .service import append_audit
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO tax_adjustment_lines
                (entity_id, period, category, item_name, amount, basis_note, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (entity["entity_id"], period, category, item_name.strip()[:200],
                         v, (basis_note or "")[:500] or None, actor))
            lid = cur.lastrowid
            append_audit(conn, {"entity_id": entity["entity_id"], "actor": actor,
                                "action": "tax_line.create", "object_type": "tax_adjustment_lines",
                                "object_id": str(lid),
                                "detail": {"period": period, "category": category,
                                           "item": item_name, "amount": float(v)}})
    return lid


def delete_line(entity, line_id, actor="system"):
    from .db import transaction
    from .service import append_audit
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT * FROM tax_adjustment_lines
                            WHERE line_id=%s AND entity_id=%s""", (line_id, entity["entity_id"]))
            row = cur.fetchone()
            if not row:
                raise ValueError("调整项不存在")
            cur.execute("DELETE FROM tax_adjustment_lines WHERE line_id=%s", (line_id,))
            append_audit(conn, {"entity_id": entity["entity_id"], "actor": actor,
                                "action": "tax_line.delete", "object_type": "tax_adjustment_lines",
                                "object_id": str(line_id),
                                "detail": {"item": row["item_name"],
                                           "amount": float(dec(row["amount"]))}})
    return True
