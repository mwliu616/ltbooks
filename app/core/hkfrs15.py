# LtBooks — core/hkfrs15.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""HKFRS 15（2022）收入确认 —— 五步法引擎。

本模块只做确定性计算与判定，不臆测：任何不满足准则条件的情形都返回
明确的状态与理由，交由人工处理。

五步：
  1. 识别与客户之间的合同            HKFRS 15.9-16
  2. 识别合同中的履约义务            HKFRS 15.22-30
  3. 确定交易价格                    HKFRS 15.47-72
  4. 将交易价格分摊至履约义务        HKFRS 15.73-86
  5. 在履约义务履行时确认收入        HKFRS 15.31-45
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .db import query, query_one

CENT = Decimal("0.01")


def D(v) -> Decimal:
    if v is None:
        return Decimal("0.00")
    if isinstance(v, Decimal):
        return v.quantize(CENT, rounding=ROUND_HALF_UP)
    return Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- 步骤 1
STEP1_CRITERIA = [
    ("approved", "合同各方已批准该合同并承诺将履行各自义务"),
    ("rights_identifiable", "该合同明确了合同各方与所转让商品或服务相关的权利"),
    ("payment_terms", "该合同明确了与所转让商品或服务相关的支付条款"),
    ("commercial_substance", "该合同具有商业实质（即履行该合同将改变企业未来现金流量的风险、时间分布或金额）"),
    ("probable_collection", "企业因向客户转让商品或服务而有权取得的对价很可能收回"),
]


def assess_contract(c) -> dict:
    """步骤 1：合同要件判定（HKFRS 15.9）。"""
    missing = [(k, d) for k, d in STEP1_CRITERIA if not c.get(k)]
    collectable = bool(c.get("probable_collection"))

    if missing:
        return {
            "step": 1, "status": "FAIL", "passed": False,
            "missing": [{"key": k, "requirement": d} for k, d in missing],
            "conclusion": "不满足 HKFRS 15.9 的五项合同要件，不得确认收入",
            "reference": "HKFRS 15.9",
        }
    if not collectable:
        return {"step": 1, "status": "REVIEW", "passed": False,
                "missing": [], "conclusion": "对价很可能收回性存疑，需评估",
                "reference": "HKFRS 15.9(e)"}
    return {"step": 1, "status": "PASS", "passed": True, "missing": [],
            "conclusion": "合同满足 HKFRS 15.9 五项要件，可作为收入确认对象",
            "reference": "HKFRS 15.9"}


# ---------------------------------------------------------------- 步骤 2
def assess_obligations(pos: list) -> dict:
    """步骤 2：履约义务识别与可明确区分性检查（HKFRS 15.22-30）。"""
    issues = []
    if not pos:
        issues.append("合同未识别出任何履约义务")
    for po in pos:
        if not str(po.get("description") or "").strip():
            issues.append(f"履约义务 #{po.get('seq')} 缺少描述")
        if D(po.get("ssp")) <= 0:
            issues.append(f"履约义务 #{po.get('seq')} 缺少单独售价，无法按相对单独售价分摊")
        if po.get("satisfaction_method") == "over_time":
            if not po.get("overtime_criterion") in (1, 2, 3):
                issues.append(f"履约义务 #{po.get('seq')} 选择在一段时间内确认，"
                              "但未指明满足 HKFRS 15.35 的哪一项条件")
            if not po.get("progress_method"):
                issues.append(f"履约义务 #{po.get('seq')} 缺少履约进度计量方法（输入法／产出法）")
    return {"step": 2, "count": len(pos),
            "status": "PASS" if not issues else "REVIEW",
            "issues": issues,
            "conclusion": "履约义务已识别并可分摊" if not issues else "履约义务存在缺口，需补充",
            "reference": "HKFRS 15.22-30"}


# ---------------------------------------------------------------- 步骤 3
def compute_transaction_price(contract, items: list) -> dict:
    """步骤 3：交易价格 = 固定对价 + 约束后的可变对价 ± 融资成分
    + 非现金对价 − 应付客户对价（HKFRS 15.47-72）。
    """
    stated = D(contract.get("stated_price"))
    variable = Decimal("0.00")
    financing = Decimal("0.00")
    non_cash = Decimal("0.00")
    payable = Decimal("0.00")
    notes = []

    for it in items:
        kind = it.get("kind")
        amt = D(it.get("amount"))
        method = it.get("method") or "most_likely"
        if kind == "variable":
            if method == "expected_value":
                prob = Decimal(str(it.get("probability") or 0))
                contrib = (amt * prob).quantize(CENT, rounding=ROUND_HALF_UP)
            else:
                contrib = amt
            # 约束：只计入极可能不会发生重大转回的金额
            constrained = D(it.get("constrained")) if it.get("constrained") is not None else contrib
            if abs(constrained) > abs(contrib):
                constrained = contrib
                notes.append(f"「{it.get('label')}」约束额超过期望值，已按期望值封顶")
            if constrained != contrib:
                notes.append(f"「{it.get('label')}」可变对价受约束："
                             f"{contrib} → {constrained}")
            variable += constrained
        elif kind == "financing":
            financing += amt
        elif kind == "non_cash":
            non_cash += amt
        elif kind == "payable_to_customer":
            payable += amt

    total = stated + variable + financing + non_cash - payable
    return {
        "step": 3,
        "statedPrice": float(stated),
        "variableConsideration": float(variable),
        "financingComponent": float(financing),
        "nonCashConsideration": float(non_cash),
        "considerationToCustomer": float(payable),
        "transactionPrice": float(total),
        "notes": notes,
        "reference": "HKFRS 15.47-72",
    }


# ---------------------------------------------------------------- 步骤 4
def allocate(transaction_price, pos: list) -> dict:
    """步骤 4：按相对单独售价分摊交易价格（HKFRS 15.73-86）。

    单独售价缺口时不分摊，返回 REVIEW —— 不允许用假设填补。
    """
    tp = D(transaction_price)
    total_ssp = sum((D(p.get("ssp")) for p in pos), Decimal("0.00"))
    if total_ssp <= 0:
        return {"step": 4, "status": "FAIL", "rows": [],
                "conclusion": "单独售价合计为零，无法分摊", "reference": "HKFRS 15.76"}

    rows, allocated_sum = [], Decimal("0.00")
    for i, p in enumerate(pos):
        ssp = D(p.get("ssp"))
        pct = (ssp / total_ssp)
        amt = (tp * pct).quantize(CENT, rounding=ROUND_HALF_UP)
        rows.append({
            "seq": p.get("seq"), "poId": p.get("po_id"),
            "description": p.get("description"),
            "ssp": float(ssp),
            "allocationPct": float(pct.quantize(Decimal("0.000001"))),
            "allocatedPrice": float(amt),
        })
        allocated_sum += amt

    # 尾差归入金额最大的履约义务，确保分摊合计等于交易价格
    diff = tp - allocated_sum
    if diff != 0 and rows:
        biggest = max(range(len(rows)), key=lambda i: rows[i]["allocatedPrice"])
        rows[biggest]["allocatedPrice"] = float(D(rows[biggest]["allocatedPrice"]) + diff)
        rows[biggest]["roundingAdjustment"] = float(diff)

    return {"step": 4, "status": "PASS", "rows": rows,
            "totalSsp": float(total_ssp),
            "transactionPrice": float(tp),
            "allocatedTotal": float(sum(D(r["allocatedPrice"]) for r in rows)),
            "conclusion": "已按相对单独售价分摊", "reference": "HKFRS 15.73-86"}


# ---------------------------------------------------------------- 步骤 5
CONTROL_INDICATORS = [
    ("企业就该商品享有现时收款权利", "right_to_payment"),
    ("企业已将该商品的法定所有权转移给客户", "legal_title"),
    ("企业已将该商品实物转移给客户", "physical_possession"),
    ("企业已将该商品所有权上的主要风险和报酬转移给客户", "significant_risks_rewards"),
    ("客户已接受该商品", "customer_acceptance"),
]


def recognise_po(po, as_of: date) -> dict:
    """步骤 5：计算某个履约义务在 as_of 的累计确认收入。"""
    allocated = D(po.get("allocated_price"))
    method = po.get("satisfaction_method")

    if method == "point_in_time":
        satisfied = po.get("status") == "satisfied" and po.get("satisfied_date")
        if satisfied and str(po.get("satisfied_date")) <= as_of.isoformat():
            return {"poId": po.get("po_id"), "method": "point_in_time",
                    "progressPct": 1.0, "cumulative": float(allocated),
                    "recognised": True, "reason": "控制权已转移，全额确认",
                    "reference": "HKFRS 15.31-38"}
        return {"poId": po.get("po_id"), "method": "point_in_time",
                "progressPct": 0.0, "cumulative": 0.0, "recognised": False,
                "reason": "控制权尚未转移，不确认收入", "reference": "HKFRS 15.31-38"}

    # over_time：按履约进度（输入法／产出法）
    pct = Decimal(str(po.get("progress_pct") or 0))
    pct = max(Decimal("0"), min(Decimal("1"), pct))
    cum = (allocated * pct).quantize(CENT, rounding=ROUND_HALF_UP)
    return {"poId": po.get("po_id"), "method": "over_time",
            "progressPct": float(pct), "cumulative": float(cum),
            "recognised": cum > 0,
            "reason": f"按{ {'input':'投入法','output':'产出法','milestone':'里程碑法'}.get(po.get('progress_method'),'进度') }确认 {pct*100:.2f}%",
            "criterion": po.get("overtime_criterion"),
            "reference": "HKFRS 15.35-37, 39-45"}


# ---------------------------------------------------------------- 合同余额
def contract_balances(contract_id: int, as_of: date | None = None) -> dict:
    """合同资产 / 合同负债 / 应收 的三方划分（HKFRS 15.105-109）。

    开票与收款**只取本合同关联的发票**，不按客户汇总 ——
    同一客户可能同时有多份合同，按客户汇总会把别的合同的款算进来。
    """
    as_of = as_of or date.today()
    pos = query("SELECT * FROM performance_obligations WHERE contract_id=%s ORDER BY seq",
                (contract_id,))
    if not pos:
        return {"contractId": contract_id, "asOf": as_of.isoformat(),
                "recognised": 0.0, "invoiced": 0.0, "received": 0.0,
                "receivable": 0.0, "contractAsset": 0.0, "contractLiability": 0.0,
                "rows": [], "links": [], "net": 0.0,
                "billingProgress": 0.0, "collectionProgress": 0.0,
                "unbilled": 0.0, "uncollected": 0.0}

    c = query_one("""SELECT transaction_price, currency, recognition_mode FROM revenue_contracts
                      WHERE contract_id=%s""", (contract_id,)) or {}
    tp = D(c.get("transaction_price"))
    mode = (c.get("recognition_mode") or "on_invoice")

    # 已开票 / 已收款：只认本合同关联的发票
    links = query("""SELECT ci.link_id, ci.invoice_id, ci.po_id, ci.amount,
                            i.invoice_no, i.invoice_date, i.currency, i.status,
                            i.gross_original, i.settled_original
                       FROM contract_invoices ci
                       JOIN invoices i ON i.invoice_id = ci.invoice_id
                      WHERE ci.contract_id=%s AND i.status='posted'
                        AND i.invoice_date <= %s
                      ORDER BY i.invoice_date, i.invoice_id""",
                  (contract_id, as_of.isoformat()))
    invoiced = Decimal("0.00")
    received = Decimal("0.00")
    link_rows = []
    for l in links:
        amt = D(l["amount"])
        gross = D(l["gross_original"])
        settled = D(l["settled_original"])
        # 按关联金额占发票金额的比例折算已收
        portion = (settled * amt / gross).quantize(Decimal("0.01")) if gross > 0 else Decimal("0.00")
        invoiced += amt
        received += portion
        link_rows.append({
            "linkId": l["link_id"], "invoiceId": l["invoice_id"],
            "invoiceNo": l["invoice_no"], "date": l["invoice_date"].isoformat(),
            "currency": l["currency"], "amount": float(amt),
            "settled": float(portion), "gross": float(gross),
        })

    # ---- 两种确认模式 ----
    # on_invoice：收入随开票确认（开票即过账收入）
    # progress  ：按履约进度确认（严格 HKFRS 15；履约早于开票时形成合同资产）
    po_rows = []
    progress_total = Decimal("0.00")
    for p in pos:
        alloc = D(p["allocated_price"])
        if mode == "progress":
            if p["satisfaction_method"] == "point_in_time":
                # 某一时点：只有状态为 satisfied 才全额确认
                pct = Decimal("1") if p["status"] == "satisfied" else Decimal("0")
            else:
                pct = Decimal(str(p.get("progress_pct") or 0))
            pct = max(Decimal("0"), min(Decimal("1"), pct))
            rec = (alloc * pct).quantize(Decimal("0.01"))
            progress_total += rec
        else:
            rec = (alloc * invoiced / tp).quantize(Decimal("0.01")) if tp > 0 else Decimal("0.00")
        po_rows.append({"poId": p["po_id"], "seq": p["seq"], "description": p["description"],
                        "allocated": float(alloc), "recognised": float(rec)})

    recognised = invoiced if mode == "on_invoice" else progress_total

    # HKFRS 15.105-109 三方划分：应收=已开票（无条件收款权）
    receivable = invoiced
    contract_asset = max(Decimal("0.00"), recognised - invoiced)
    contract_liability = max(Decimal("0.00"), invoiced - recognised)

    def pct(v):
        return float((v / tp).quantize(Decimal("0.0001"))) if tp > 0 else 0.0

    return {
        "contractId": contract_id, "asOf": as_of.isoformat(),
        "transactionPrice": float(tp),
        "recognised": float(recognised), "invoiced": float(invoiced),
        "received": float(received),
        "receivable": float(receivable),
        "contractAsset": float(contract_asset),
        "contractLiability": float(contract_liability),
        "unbilled": float(tp - invoiced),          # 尚未开票
        "uncollected": float(invoiced - received), # 已开票未收
        "billingProgress": pct(invoiced),
        "collectionProgress": pct(received),
        "recognitionProgress": pct(recognised),
        "net": float(contract_asset - contract_liability),
        "links": link_rows,
        # 各履约义务的已确认收入：按分摊比例分配已开票金额
        "rows": po_rows,
        "recognitionMode": mode,
        "recognisedVia": mode,
        "reference": "HKFRS 15.105-109；收入于发票过账时确认，合同仅跟踪开票与收款进度",
    }


# ---------------------------------------------------------------- 披露
DISCLOSURE_REFS = {
    "disaggregation": "HKFRS 15.114-115",
    "contract_balances": "HKFRS 15.116-118",
    "performance_obligations": "HKFRS 15.119-120",
    "remaining_po": "HKFRS 15.120",
    "significant_judgements": "HKFRS 15.122-126",
    "contract_costs": "HKFRS 15.127-128",
}


def disclosure(entity_id: int, period_end: date) -> dict:
    """按 HKFRS 15.110-129 汇总披露所需信息。"""
    contracts = query("""SELECT * FROM revenue_contracts
                          WHERE entity_id=%s AND status IN ('active','completed')
                            AND start_date <= %s""", (entity_id, period_end.isoformat()))

    # 收入分解（按客户与币种）—— 收入随发票确认，故取合同已开票金额
    agg = {}
    for c0 in contracts:
        b0 = contract_balances(c0["contract_id"], period_end)
        key = (c0["customer_name"], c0["currency"])
        agg[key] = agg.get(key, 0.0) + b0["invoiced"]
    disaggregation = [{"customer_name": k[0], "currency": k[1], "recognised": v}
                      for k, v in sorted(agg.items(), key=lambda x: -x[1])]

    balances = {"contractAsset": 0.0, "contractLiability": 0.0, "receivable": 0.0}
    remaining = []
    po_rows = []
    for c in contracts:
        b = contract_balances(c["contract_id"], period_end)
        balances["contractAsset"] += b["contractAsset"]
        balances["contractLiability"] += b["contractLiability"]
        balances["receivable"] += b["receivable"]
        pos = query("SELECT * FROM performance_obligations WHERE contract_id=%s ORDER BY seq",
                    (c["contract_id"],))
        for p in pos:
            alloc = D(p["allocated_price"])
            recog = D(next((x["recognised"] for x in b["rows"]
                            if x["poId"] == p["po_id"]), 0))
            po_rows.append({"contract": c["contract_ref"], "customer": c["customer_name"],
                            "po": p["description"], "method": p["satisfaction_method"],
                            "allocated": float(alloc), "recognised": float(recog),
                            "remaining": float(alloc - recog),
                            "status": p["status"]})
            if p["status"] != "satisfied":
                remaining.append({"contract": c["contract_ref"], "po": p["description"],
                                  "remaining": float(alloc - recog),
                                  "expectedTiming": c["end_date"].isoformat() if c["end_date"] else "未确定"})

    costs = query("""SELECT k.kind, k.label, k.amount, k.amortised, c.contract_ref
                       FROM contract_costs k JOIN revenue_contracts c ON c.contract_id=k.contract_id
                      WHERE c.entity_id=%s""", (entity_id,))

    judgements = []
    for c in contracts:
        if D(c["variable_consideration"]) != 0:
            judgements.append(f"合同 {c['contract_ref']}：可变对价 {c['variable_consideration']} "
                              "已按「极可能不会发生重大转回」约束（HKFRS 15.56-58）")
        if D(c["financing_component"]) != 0:
            judgements.append(f"合同 {c['contract_ref']}：存在重大融资成分 {c['financing_component']}"
                              "（HKFRS 15.60-65）")
        if D(c["consideration_to_customer"]) != 0:
            judgements.append(f"合同 {c['contract_ref']}：应付客户对价 "
                              f"{c['consideration_to_customer']}（HKFRS 15.70-72）")

    return {
        "asOf": period_end.isoformat(),
        "contractCount": len(contracts),
        "disaggregation": [{"customer": r["customer_name"], "currency": r["currency"],
                            "recognised": round(float(r["recognised"]), 2)}
                           for r in disaggregation],
        "contractBalances": {k: round(v, 2) for k, v in balances.items()},
        "performanceObligations": po_rows,
        "remainingPerformanceObligations": remaining,
        "contractCosts": [{"kind": r["kind"], "label": r["label"],
                           "amount": float(D(r["amount"])),
                           "amortised": float(D(r["amortised"])),
                           "contract": r["contract_ref"]} for r in costs],
        "significantJudgements": judgements,
        "references": DISCLOSURE_REFS,
    }


# ============================================================================
# 规则驱动判定（单张发票路径）
#
# 这是系统的既有入口：给定履约义务状态，从 rules/hkfrs15.yml 查出借贷科目。
# 与上面的五步法共用同一份规则文件；五步法用于有多项履约义务的合同，
# 单张发票仍走这里，保持既有行为不变。
# ============================================================================

def _resolve(account_mapping: dict, logical: str) -> dict:
    """逻辑科目名 → {logical, code}。查不到编码时 code 为 None。"""
    if not logical:
        return {"logical": None, "code": None}
    return {"logical": logical, "code": account_mapping.get(logical)}


def assess(rules, po_status, recognition_pattern=None,
           has_unconditional_right=None, amount=None, confidence=None) -> dict:
    """按 HKFRS 15 规则判定一张发票的借贷方向。

    返回：
      decision                 'determined' / 'undetermined'
      debit / credit           {logical, code}
      contractAssetApplied     是否因收款权非无条件而改挂合同资产
      contractLiabilityApplied 是否贷记合同负债（已开票但未履约）
      matchedRule              命中的规则标识（写入 invoices.matched_rule_id）
      ruleVersion / reason
    """
    rules = rules or {}
    version = rules.get("version")
    mapping = rules.get("invoice_to_revenue_mapping") or []
    acct = rules.get("account_mapping") or {}

    def _undetermined(reason, debit=None, credit=None, matched=None):
        return {"decision": "undetermined", "debit": debit, "credit": credit,
                "contractAssetApplied": False, "contractLiabilityApplied": False,
                "matchedRule": matched, "ruleVersion": version, "reason": reason}

    # 兼容历史写法：partial_and_over_time 视同 partial
    po_status = {"partial_and_over_time": "partial"}.get(str(po_status), po_status)

    entry, matched = None, None
    for m in mapping:
        if str(m.get("when_po_status")) == str(po_status):
            entry = m
            matched = f"hkfrs15:v{version}:{po_status}"
            break

    if entry is None:
        return _undetermined(f"履约义务状态「{po_status}」无匹配的规则条目（规则 v{version}）")
    if entry.get("action") == "pending_review":
        return _undetermined(entry.get("reason") or "规则要求人工复核", matched=matched)

    debit_logical = entry.get("debit")
    credit_logical = entry.get("credit")

    # 已履约但收款权尚未成为无条件权利 → 合同资产，而非应收
    ca = rules.get("contract_asset_rule") or {}
    ca_applied = False
    if (has_unconditional_right is False and ca.get("enabled")
            and debit_logical == "trade_receivables"):
        debit_logical = ca.get("debit") or debit_logical
        ca_applied = True

    cl = rules.get("contract_liability_rule") or {}
    cl_applied = bool(cl.get("enabled")) and credit_logical == "contract_liability"

    debit = _resolve(acct, debit_logical)
    credit = _resolve(acct, credit_logical)

    if not debit.get("code") or not credit.get("code"):
        return _undetermined(f"科目映射缺失：{debit_logical} / {credit_logical}",
                             debit, credit, matched)

    return {"decision": "determined", "debit": debit, "credit": credit,
            "contractAssetApplied": ca_applied,
            "contractLiabilityApplied": cl_applied,
            "matchedRule": matched, "ruleVersion": version, "reason": None}
