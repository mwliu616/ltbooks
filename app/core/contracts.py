# LtBooks — core/contracts.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""HKFRS 15 合同服务层：建合同、设履约义务、分摊、确认收入、生成分录。"""
from datetime import date
from decimal import Decimal

from .db import query, query_one, transaction
from .hkfrs15 import (D, allocate, assess_contract, assess_obligations,
                      compute_transaction_price, contract_balances, recognise_po)
from .money import convert, dec, retention_until
from .numbering import next_no

ACCT_CONTRACT_ASSET = "1140"
ACCT_RECEIVABLE = "1130"
ACCT_CONTRACT_LIABILITY = "2120"
ACCT_REVENUE = "4100"


def _load(contract_id):
    c = query_one("SELECT * FROM revenue_contracts WHERE contract_id=%s", (contract_id,))
    if not c:
        raise ValueError("合同不存在")
    return c


def _pos(contract_id):
    return query("SELECT * FROM performance_obligations WHERE contract_id=%s ORDER BY seq",
                 (contract_id,))


def _items(contract_id):
    return query("SELECT * FROM contract_price_items WHERE contract_id=%s ORDER BY item_id",
                 (contract_id,))


def create_contract(entity_id, payload, actor):
    ref = str(payload.get("contractRef") or "").strip()
    cust = str(payload.get("customerName") or "").strip()
    if not cust:
        raise ValueError("客户名称不能为空")
    start = payload.get("startDate") or date.today().isoformat()

    c = {
        "contractRef": ref, "customerName": cust,
        "startDate": start, "endDate": payload.get("endDate"),
        "currency": (payload.get("currency") or "HKD").upper(),
        "statedPrice": dec(payload.get("statedPrice") or 0),
        "recognitionMode": (payload.get("recognitionMode") or "on_invoice"),
        # 纸面合同已签署时五要件即成立；调用方显式传 false 才视为不满足
        "approved": payload.get("approved", True) is not False,
        "rightsIdentifiable": payload.get("rightsIdentifiable", True) is not False,
        "paymentTerms": payload.get("paymentTerms", True) is not False,
        "commercialSubstance": payload.get("commercialSubstance", True) is not False,
        "probableCollection": payload.get("probableCollection", True) is not False,
        "contractName": str(payload.get("contractName") or "").strip() or None,
    }
    # 步骤 1 判定：不满足则不建为 active
    step1 = assess_contract({
        "approved": c["approved"], "rights_identifiable": c["rightsIdentifiable"],
        "payment_terms": c["paymentTerms"], "commercial_substance": c["commercialSubstance"],
        "probable_collection": c["probableCollection"],
    })

    with transaction() as conn:
        if not ref:
            from .numbering import next_no
            ref = next_no(conn, entity_id, start, "contract")
        c["contractRef"] = ref
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO revenue_contracts
                (entity_id, contract_ref, contract_name, customer_id, customer_name, start_date, end_date,
                 currency, recognition_mode, mode_note, approved, rights_identifiable,
                 payment_terms, commercial_substance, probable_collection, collectability_note,
                 stated_price, status, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (entity_id, ref, c["contractName"], payload.get("customerId"), cust, start, c["endDate"],
                 c["currency"], c["recognitionMode"], payload.get("modeNote"),
                 int(c["approved"]), int(c["rightsIdentifiable"]),
                 int(c["paymentTerms"]), int(c["commercialSubstance"]),
                 int(c["probableCollection"]), payload.get("collectabilityNote"),
                 c["statedPrice"], "active" if step1["passed"] else "draft", actor))
            cid = cur.lastrowid
            _write_payments(cur, entity_id, cid, c["currency"], c["statedPrice"],
                            payload.get("payments") or [], ref)
    return {"contractId": cid, "contractRef": ref, "status": "active" if step1["passed"] else "draft",
            "step1": step1}


def _write_payments(cur, entity_id, contract_id, currency, total, payments, ref=""):
    """写收款计划。比例与金额二选一：填了就按填的存，没填按比例算。"""
    plans = []
    for i, p in enumerate(payments, start=1):
        label = str(p.get("label") or "").strip()[:200]
        pct = p.get("pct")
        amt = p.get("amount")
        pct = dec(pct) if pct not in (None, "") else None
        amt = dec(amt) if amt not in (None, "") else None
        override = 0
        if amt is None or amt == 0:
            amt = (total * (pct or dec(0)) / dec(100)).quantize(dec("0.01"))
        else:
            override = 1
            if pct is None and total:
                pct = (amt / total * dec(100)).quantize(dec("0.0001"))
        due = p.get("dueDate") or None
        if not label and not amt:
            continue
        plans.append((entity_id, contract_id, i, label or None, due, pct, amt, currency,
                      override, (str(p.get("note") or "").strip() or None)))
    for row in plans:
        cur.execute("""INSERT INTO contract_payments
            (entity_id, contract_id, seq, label, due_date, pct, amount, currency,
             amount_override, condition_note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", row)
    return len(plans)


def set_obligations(contract_id, pos, actor):
    """替换合同的履约义务（步骤 2），并重算步骤 3、4。"""
    _load(contract_id)
    if not pos:
        raise ValueError("至少需要一条履约义务")
    step2 = assess_obligations(pos)

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM performance_obligations WHERE contract_id=%s", (contract_id,))
            for i, p in enumerate(pos, start=1):
                cur.execute("""INSERT INTO performance_obligations
                    (contract_id, seq, description, ssp, satisfaction_method, overtime_criterion,
                     progress_method, progress_pct, revenue_account_code, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (contract_id, i, str(p.get("description") or "").strip(),
                     dec(p.get("ssp") or 0),
                     p.get("satisfactionMethod") or "point_in_time",
                     p.get("overtimeCriterion"),
                     p.get("progressMethod"),
                     dec(p.get("progressPct") or 0),
                     p.get("revenueAccountCode") or ACCT_REVENUE,
                     "satisfied" if p.get("status") == "satisfied" else
                     ("partially_satisfied" if dec(p.get("progressPct") or 0) > 0
                      else "unsatisfied")))
    return {"step2": step2, **recalculate(contract_id, actor)}


def set_price_items(contract_id, items, actor):
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM contract_price_items WHERE contract_id=%s", (contract_id,))
            for it in items or []:
                cur.execute("""INSERT INTO contract_price_items
                    (contract_id, kind, label, method, amount, probability, constrained,
                     constraint_reason)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (contract_id, it.get("kind"), str(it.get("label") or ""),
                     it.get("method") or "most_likely", dec(it.get("amount") or 0),
                     it.get("probability"), it.get("constrained"),
                     it.get("constraintReason")))
    return recalculate(contract_id, actor)


def recalculate(contract_id, actor="system"):
    """重算步骤 3（交易价格）与步骤 4（分摊），并落库。"""
    from .service import append_audit
    c = _load(contract_id)
    pos = _pos(contract_id)
    items = _items(contract_id)

    tp = compute_transaction_price(c, items)
    alloc = allocate(tp["transactionPrice"], pos) if pos else {"rows": [], "status": "FAIL"}

    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE revenue_contracts SET
                             variable_consideration=%s, financing_component=%s,
                             non_cash_consideration=%s, consideration_to_customer=%s,
                             transaction_price=%s
                           WHERE contract_id=%s""",
                        (tp["variableConsideration"], tp["financingComponent"],
                         tp["nonCashConsideration"], tp["considerationToCustomer"],
                         tp["transactionPrice"], contract_id))
            for r in alloc.get("rows", []):
                cur.execute("""UPDATE performance_obligations
                                  SET allocation_pct=%s, allocated_price=%s
                                WHERE po_id=%s""",
                            (r["allocationPct"], r["allocatedPrice"], r["poId"]))
        append_audit(conn, {"entity_id": c["entity_id"], "actor": actor,
                            "action": "hkfrs15.recalculate", "object_type": "revenue_contracts",
                            "object_id": str(contract_id),
                            "detail": {"transactionPrice": tp["transactionPrice"],
                                       "pos": len(pos)}})
    return {"step3": tp, "step4": alloc}


def recognise(contract_id, as_of, actor="system", post_journal=True):
    """步骤 5：计算并（可选）过账本期收入确认。"""
    from .service import append_audit
    c = _load(contract_id)
    if (c.get("recognition_mode") or "on_invoice") != "progress":
        raise ValueError(
            "本合同为「随开票确认」模式，收入在发票过账时确认，"
            "不应在合同下再次确认（会重复计收入）。如需按履约进度确认，请先切换确认模式。")
    pos = _pos(contract_id)
    if not pos:
        raise ValueError("合同没有履约义务")

    prev = {r["po_id"]: D(r["cumulative"]) for r in query(
        """SELECT po_id, cumulative FROM revenue_recognitions
            WHERE contract_id=%s AND as_of<%s ORDER BY as_of DESC""",
        (contract_id, as_of.isoformat()))}
    # 同一 PO 只保留最新一期
    latest_prev = {}
    for r in query("""SELECT po_id, cumulative FROM revenue_recognitions
                       WHERE contract_id=%s AND as_of<%s ORDER BY as_of DESC""",
                   (contract_id, as_of.isoformat())):
        latest_prev.setdefault(r["po_id"], D(r["cumulative"]))

    results, total_period = [], Decimal("0.00")
    for p in pos:
        out = recognise_po(p, as_of)
        cum = D(out["cumulative"])
        prev_amt = latest_prev.get(p["po_id"], Decimal("0.00"))
        period = cum - prev_amt
        results.append({**out, "previous": float(prev_amt), "periodAmount": float(period)})
        total_period += period

    entry_id = None
    if post_journal and total_period != 0:
        bal = contract_balances(contract_id, as_of)
        # progress 模式下：已开票金额记在合同负债，确认收入时先冲减合同负债；
        # 超出已开票的部分（先履约后开票）形成合同资产。
        prev_cum = sum((D(r["previous"]) for r in results), Decimal("0.00"))
        available_liab = max(Decimal("0.00"), D(bal["invoiced"]) - prev_cum)
        to_liability = min(abs(total_period), available_liab) if total_period > 0 else Decimal("0.00")
        to_asset = abs(total_period) - to_liability
        entry_date = as_of
        with transaction() as conn:
            with conn.cursor() as cur:
                entry_no = next_no(conn, c["entity_id"], entry_date, "journal")
                cur.execute("""INSERT INTO journal_entries
                    (entity_id, entry_no, entry_date, source_type, source_id, description,
                     status, total_debit, total_credit, created_by, retention_until)
                    VALUES (%s,%s,%s,'contract_revenue',%s,%s,'draft',%s,%s,%s,%s)""",
                    (c["entity_id"], entry_no, entry_date, contract_id,
                     f"HKFRS 15 收入确认 {c['contract_ref']} 截至 {entry_date}",
                     float(abs(total_period)), float(abs(total_period)), actor,
                     retention_until(entry_date, entry_date)))
                entry_id = cur.lastrowid
                # 按各履约义务指定的收入科目分列，而非全部计入 4100
                by_acct = {}
                for r_ in results:
                    amt = D(r_["periodAmount"])
                    if amt == 0:
                        continue
                    code = next((p2.get("revenue_account_code") or ACCT_REVENUE
                                 for p2 in pos if p2["po_id"] == r_["poId"]), ACCT_REVENUE)
                    by_acct[code] = by_acct.get(code, Decimal("0.00")) + amt

                if total_period > 0:
                    lines = []
                    if to_liability > 0:
                        lines.append((ACCT_CONTRACT_LIABILITY, to_liability, 0))
                    if to_asset > 0:
                        lines.append((ACCT_CONTRACT_ASSET, to_asset, 0))
                    for code, amt in by_acct.items():
                        if amt > 0:
                            lines.append((code, 0, amt))
                else:
                    lines = [(ACCT_CONTRACT_LIABILITY, 0, abs(total_period))]
                    for code, amt in by_acct.items():
                        if amt < 0:
                            lines.append((code, -amt, 0))
                for i, (acct, dr, cr) in enumerate(lines, start=1):
                    cur.execute("""INSERT INTO journal_lines
                        (entry_id, line_no, account_code, description, debit, credit, ccy)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (entry_id, i, acct, f"HKFRS 15 {c['contract_ref']}",
                         float(dr), float(cr), c["currency"]))
                # 行齐了再置为已过账：触发器禁止向已过账分录追加行，
                # 且过账必须同时写 posted_by / posted_at（审计要求）
                cur.execute("""UPDATE journal_entries
                                  SET status='posted', posted_by=%s, posted_at=NOW(3)
                                WHERE entry_id=%s""", (actor, entry_id))
        post_journal = True

    with transaction() as conn:
        with conn.cursor() as cur:
            for r in results:
                cur.execute("""INSERT INTO revenue_recognitions
                    (entity_id, contract_id, po_id, as_of, cumulative, period_amount, entry_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE cumulative=VALUES(cumulative),
                                            period_amount=VALUES(period_amount),
                                            entry_id=VALUES(entry_id)""",
                    (c["entity_id"], contract_id, r["poId"], as_of.isoformat(),
                     r["cumulative"], r["periodAmount"], entry_id))
            cur.execute("""UPDATE performance_obligations SET
                             status = CASE WHEN progress_pct >= 1 THEN 'satisfied'
                                           WHEN progress_pct > 0 THEN 'partially_satisfied'
                                           ELSE status END
                           WHERE contract_id=%s""", (contract_id,))
        append_audit(conn, {"entity_id": c["entity_id"], "actor": actor,
                            "action": "hkfrs15.recognise", "object_type": "revenue_contracts",
                            "object_id": str(contract_id),
                            "detail": {"asOf": as_of.isoformat(),
                                       "periodAmount": float(total_period),
                                       "entryId": entry_id}})

    return {"asOf": as_of.isoformat(), "results": results,
            "periodAmount": float(total_period), "entryId": entry_id,
            "balances": contract_balances(contract_id, as_of)}


def detail(contract_id, as_of=None):
    c = _load(contract_id)
    as_of = as_of or date.today()
    pos = _pos(contract_id)
    items = _items(contract_id)
    return {
        "contract": {k: (v.isoformat() if hasattr(v, "isoformat") else
                         (float(v) if isinstance(v, Decimal) else v))
                     for k, v in dict(c).items()},
        "obligations": [{k: (v.isoformat() if hasattr(v, "isoformat") else
                             (float(v) if isinstance(v, Decimal) else v))
                         for k, v in dict(p).items()} for p in pos],
        "priceItems": [{k: (float(v) if isinstance(v, Decimal) else v) for k, v in dict(i).items()}
                       for i in items],
        "step1": assess_contract(c),
        "step2": assess_obligations(pos),
        "balances": contract_balances(contract_id, as_of),
        "payments": payment_plan(contract_id),
    }


def payment_plan(contract_id):
    """合同的收款计划，附带每期是否到期未收。"""
    rows = query("""SELECT payment_plan_id, seq, label, due_date, pct, amount, currency,
                           amount_override, condition_note, received_date, received_amount,
                           invoice_id, status
                      FROM contract_payments WHERE contract_id=%s ORDER BY seq""", (contract_id,))
    today = date.today()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("pct", "amount", "received_amount"):
            if d.get(k) is not None:
                d[k] = float(dec(d[k]))
        for k in ("due_date", "received_date"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat()
        status = d.get("status") or "planned"
        if status in ("planned", "invoiced") and d.get("due_date") and d["due_date"] < today.isoformat():
            status = "overdue"
        d["effectiveStatus"] = status
        out.append(d)
    total = sum(dec(d["amount"]) for d in rows) if rows else dec(0)
    received = sum(dec(d["received_amount"] or 0) for d in rows) if rows else dec(0)
    return {"items": out, "total": float(total), "received": float(received),
            "outstanding": float(total - received), "count": len(out)}
