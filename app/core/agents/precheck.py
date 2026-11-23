# LtBooks — core/agents/precheck.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""人工台「提交前预判」：由对应岗位智能体先审一遍，再交人决定。

与 runtime.run 的区别：
  - 不调用工具、不写账，只吃表单事实并返回结构化 JSON；
  - 确定性的硬校验（科目方向、借贷平衡、期间锁定、核销上限）由代码先做，
    模型只在此基础上补充判断和说明，避免它心算或编造金额；
  - 模型不可用时仍返回规则预判，页面不会空白。
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from ..db import query, transaction
from . import llm, registry

WORKFLOWS = {
    "purchase_order": {"agent": "doc_analyst", "label": "采购订单", "direction": "purchase"},
    "sales_order": {"agent": "doc_analyst", "label": "销售订单", "direction": "sales"},
    "quote": {"agent": "doc_analyst", "label": "报价单", "direction": "sales"},
    "bill": {"agent": "accountant", "label": "采购账单", "direction": "purchase"},
    "invoice": {"agent": "accountant", "label": "销售发票", "direction": "sales"},
    "expense": {"agent": "accountant", "label": "费用单", "direction": "purchase"},
    "payment": {"agent": "cashier", "label": "付款", "direction": "payment"},
    "receipt": {"agent": "cashier", "label": "收款", "direction": "receipt"},
    "journal": {"agent": "accountant", "label": "手工日记账", "direction": "journal"},
    "credit_note": {"agent": "accountant", "label": "贷记单", "direction": "sales"},
    "post_bill": {"agent": "guard", "label": "账单过账", "direction": "post"},
    "post_invoice": {"agent": "guard", "label": "发票过账", "direction": "post"},
}

SCHEMA = """{"verdict":"ok|warn|block","summary":"一句话结论",
"findings":[{"level":"info|warn|block","text":"具体问题或确认项"}],
"confirm":["需要人确认的事项"]}"""


def _dec(v, default=Decimal("0")):
    if v is None or v == "":
        return default
    try:
        return Decimal(str(v).replace(",", "").strip())
    except (InvalidOperation, ValueError, AttributeError):
        return default


def _f(v):
    return float(_dec(v))


def _lines(p):
    out = []
    for i, ln in enumerate(p.get("lines") or [], 1):
        if not isinstance(ln, dict):
            continue
        desc = str(ln.get("description") or ln.get("desc") or "").strip()
        qty = _dec(ln.get("quantity", ln.get("qty", 1)), Decimal("1"))
        price = _dec(ln.get("unitPrice", ln.get("price", 0)))
        disc = _dec(ln.get("discount", ln.get("disc")), Decimal("0"))
        tax_rate = _dec(ln.get("taxRate", ln.get("tax")))
        amount = _dec(ln.get("amount"))
        if not amount:
            amount = (qty * price * (Decimal("100") - disc) / Decimal("100"))
        tax_amt = _dec(ln.get("taxAmount", ln.get("taxAmt")))
        if not tax_amt and tax_rate:
            tax_amt = amount * tax_rate / Decimal("100")
        code = str(ln.get("accountCode") or ln.get("account_code")
                   or ln.get("expenseAccountCode") or ln.get("revenueAccountCode") or "").strip()
        if not desc and not amount:
            continue
        out.append({"line": i, "description": desc, "quantity": qty, "unitPrice": price,
                    "amount": amount, "taxRate": tax_rate, "taxAmount": tax_amt, "accountCode": code})
    return out


def _account_map(entity_id):
    rows = query("""SELECT account_code, account_name, category, is_active
                      FROM accounts WHERE entity_id=%s""", (entity_id,))
    return {r["account_code"]: r for r in rows}


def _bank(entity_id, account_id):
    if not account_id:
        return None
    rows = query("""SELECT account_id, name, currency, account_code
                      FROM bank_accounts WHERE entity_id=%s AND account_id=%s""",
                 (entity_id, account_id))
    return rows[0] if rows else None


def _locked(entity_id, day):
    if not day:
        return False
    try:
        d = date.fromisoformat(str(day)[:10])
    except ValueError:
        return False
    rows = query("""SELECT status FROM period_locks
                     WHERE entity_id=%s AND period=%s""", (entity_id, d.strftime("%Y-%m")))
    return bool(rows and rows[0]["status"] in ("locked", "closed"))


def _check_account(code, want_cats, amap, line_no, checks, suggested, label):
    if not code:
        checks.append({"level": "warn", "text": f"第 {line_no} 行未指定{label}，将回退到默认科目"})
        return
    meta = amap.get(code)
    if not meta:
        checks.append({"level": "block", "text": f"第 {line_no} 行科目 {code} 不存在"})
        return
    if not meta["is_active"]:
        checks.append({"level": "warn", "text": f"第 {line_no} 行科目 {code} 已停用"})
    if meta["category"] not in want_cats:
        want = "、".join(want_cats)
        checks.append({"level": "block",
                       "text": f"第 {line_no} 行选了 {code} {meta['account_name']}，"
                               f"但它是 {meta['category']} 类；这里应为 {want} 类"})
    else:
        suggested.append({"line": line_no, "code": code,
                          "name": meta["account_name"], "reason": "与单据方向匹配"})


def _load_doc(kind, entity_id, doc_id):
    if not doc_id:
        return None
    if kind == "bill":
        rows = query("""SELECT bill_id AS id, bill_no AS no, vendor_name AS party, date,
                               currency, status, review_status, created_by, approved_by,
                               expense_account_code, amount AS amount_original, tax_amount,
                               amount_functional
                          FROM bills WHERE entity_id=%s AND bill_id=%s""", (entity_id, doc_id))
        line_rows = query("""SELECT line_no, description, account_code, quantity, unit_price,
                                    amount, tax_amount
                               FROM bill_lines WHERE bill_id=%s ORDER BY line_no""", (doc_id,))
    else:
        rows = query("""SELECT invoice_id AS id, invoice_no AS no, supplier_name AS party, invoice_date AS date,
                               currency, status, review_status, created_by, approved_by,
                               revenue_account_code, amount_original, tax_original AS tax_amount,
                               amount_functional, recognition_pattern
                          FROM invoices WHERE entity_id=%s AND invoice_id=%s""", (entity_id, doc_id))
        line_rows = query("""SELECT line_no, description, revenue_account_code AS account_code,
                                    quantity, unit_price, amount, tax_amount
                               FROM invoice_lines WHERE invoice_id=%s ORDER BY line_no""", (doc_id,))
    if not rows:
        return None
    head = dict(rows[0])
    head["id"] = int(head["id"])
    head["lines"] = [dict(r) for r in line_rows]
    return head


def _journal_preview(workflow, p, lines, amap, entity_id, extra):
    cur = str(p.get("currency") or "HKD").upper()
    out = []

    def add(side, code, amount):
        if not amount:
            return
        meta = amap.get(code) or {}
        out.append({"side": side, "account": code,
                    "name": meta.get("account_name", ""), "amount": float(amount)})

    if workflow in ("bill", "purchase_order"):
        for ln in lines:
            add("debit", ln["accountCode"] or p.get("expenseAccountCode") or "6600", ln["amount"])
        tax = sum((ln["taxAmount"] for ln in lines), Decimal("0")) or _dec(p.get("taxAmount"))
        add("debit", "1160", tax)
        add("credit", "2110", sum((ln["amount"] for ln in lines), Decimal("0")) + tax)
    elif workflow in ("invoice", "sales_order"):
        net = sum((ln["amount"] for ln in lines), Decimal("0"))
        tax = sum((ln["taxAmount"] for ln in lines), Decimal("0")) or _dec(p.get("taxAmount"))
        add("debit", "1130", net + tax)
        if str(p.get("recognitionPattern") or "").lower() == "over_time":
            add("credit", "2120", net)
        else:
            for ln in lines:
                add("credit", ln["accountCode"] or p.get("revenueAccountCode") or "4100", ln["amount"])
        add("credit", "2140", tax)
    elif workflow == "payment":
        amount = _dec(p.get("amount"))
        add("debit", "2110", amount)
        add("credit", extra.get("bankCode") or "1121", amount)
    elif workflow == "receipt":
        amount = _dec(p.get("amount"))
        add("debit", extra.get("bankCode") or "1121", amount)
        add("credit", "1130", amount)
    elif workflow == "journal":
        for ln in p.get("lines") or []:
            add("debit", str(ln.get("accountCode") or ""), _dec(ln.get("debit")))
            add("credit", str(ln.get("accountCode") or ""), _dec(ln.get("credit")))
    elif workflow == "credit_note":
        net = _dec(p.get("amountOriginal") or p.get("amount"))
        tax = _dec(p.get("taxOriginal") or p.get("taxAmount"))
        is_cust = str(p.get("creditType") or "customer") != "vendor"
        acct = str(p.get("revenueAccountCode") or ("4100" if is_cust else "6200"))
        if is_cust:
            add("debit", acct, net)
            add("debit", "2140", tax)
            add("credit", "1130", net + tax)
        else:
            add("debit", "2110", net + tax)
            add("credit", acct, net)
            add("credit", "1160", tax)
    return {"currency": cur, "lines": out}


def _build(workflow, p, entity_id, doc_id):
    spec = WORKFLOWS[workflow]
    checks, suggested = [], []
    amap = _account_map(entity_id)
    extra = {}

    if workflow in ("post_bill", "post_invoice"):
        kind = "bill" if workflow == "post_bill" else "invoice"
        doc = _load_doc(kind, entity_id, doc_id)
        if not doc:
            raise ValueError("单据不存在")
        p = {
            "date": str(doc["date"]), "currency": doc["currency"], "party": doc["party"],
            "status": doc["status"], "reviewStatus": doc["review_status"],
            "createdBy": doc["created_by"], "approvedBy": doc["approved_by"],
            "lines": [{"description": r["description"], "accountCode": r["account_code"],
                       "quantity": r["quantity"], "unitPrice": r["unit_price"],
                       "amount": r["amount"], "taxAmount": r["tax_amount"]}
                      for r in doc["lines"]],
            "recognitionPattern": doc.get("recognition_pattern"),
            "amount": float(doc.get("amount_original") or 0),
        }
        lines = _lines(p)
        if doc["status"] != "draft":
            checks.append({"level": "block", "text": f"单据状态为 {doc['status']}，不能再过账"})
        if (doc["review_status"] or "draft") != "approved":
            checks.append({"level": "block", "text": "尚未完成复核批准，不能过账"})
        if doc["approved_by"] and doc["created_by"] and doc["approved_by"] == doc["created_by"]:
            checks.append({"level": "warn",
                           "text": "复核人与录单人是同一人，违反四眼原则（管理员账号可豁免）"})
        if _locked(entity_id, doc["date"]):
            checks.append({"level": "block", "text": f"期间 {str(doc['date'])[:7]} 已锁定"})
        want = ["expense", "cogs"] if kind == "bill" else ["revenue"]
        for ln in lines:
            _check_account(ln["accountCode"], want, amap, ln["line"], checks, suggested,
                           "费用科目" if kind == "bill" else "收入科目")
        return {"document": {"workflow": workflow, "label": spec["label"],
                             "party": p["party"], "date": p["date"],
                             "currency": p["currency"], "amount": p["amount"],
                             "status": p["status"], "reviewStatus": p["reviewStatus"]},
                "lines": [{**ln, "amount": float(ln["amount"]),
                           "quantity": float(ln["quantity"]),
                           "unitPrice": float(ln["unitPrice"]),
                           "taxRate": float(ln["taxRate"]),
                           "taxAmount": float(ln["taxAmount"])} for ln in lines],
                "checks": checks, "accounts": suggested,
                "journal": _journal_preview(kind, p, lines, amap, entity_id, extra)}

    lines = _lines(p)
    needs_lines = workflow in ("purchase_order", "sales_order", "quote", "bill", "invoice")
    if needs_lines and not lines:
        checks.append({"level": "block", "text": "还没有明细行，先填一行再预判"})
    day = (p.get("date") or p.get("orderDate") or p.get("invoiceDate") or p.get("entryDate")
           or p.get("quoteDate") or p.get("creditDate"))
    if not day:
        checks.append({"level": "warn", "text": "未填写日期"})
    elif _locked(entity_id, day):
        checks.append({"level": "block", "text": f"期间 {str(day)[:7]} 已锁定"})

    if workflow in ("purchase_order", "sales_order"):
        if not str(p.get("partyName") or p.get("party") or "").strip():
            checks.append({"level": "warn", "text": "未选择往来单位；订单仍可保存，但后续转单要补"})
        want = ["revenue"] if workflow == "sales_order" else ["expense", "cogs"]
        for ln in lines:
            _check_account(ln["accountCode"], want, amap, ln["line"], checks, suggested,
                           "收入科目" if workflow == "sales_order" else "费用科目")
        extra["direction"] = spec["direction"]

    elif workflow == "quote":
        if not str(p.get("partyName") or p.get("party") or "").strip():
            checks.append({"level": "warn", "text": "未选择客户；报价单仍可保存"})
        for ln in lines:
            if ln["accountCode"]:
                _check_account(ln["accountCode"], ["revenue"], amap, ln["line"], checks, suggested, "收入科目")
        checks.append({"level": "info", "text": "报价单只登记、不生成总账分录；客户接受后再转发票"})

    elif workflow == "bill":
        if not str(p.get("vendorName") or p.get("party") or "").strip():
            checks.append({"level": "block", "text": "未选择供应商"})
        header = str(p.get("expenseAccountCode") or "").strip()
        for ln in lines:
            code = ln["accountCode"] or header
            _check_account(code, ["expense", "cogs"], amap, ln["line"], checks, suggested, "费用科目")
        inv_no = str(p.get("vendorInvoiceNo") or "").strip()
        if inv_no:
            dup = query("""SELECT bill_no FROM bills
                            WHERE entity_id=%s AND vendor_invoice_no=%s AND status<>'cancelled'
                            LIMIT 1""", (entity_id, inv_no))
            if dup:
                checks.append({"level": "warn",
                               "text": f"供应商发票号 {inv_no} 已用于 {dup[0]['bill_no']}，确认是否重复录入"})

    elif workflow == "invoice":
        if not str(p.get("customerName") or p.get("party") or "").strip():
            checks.append({"level": "block", "text": "未选择客户"})
        for ln in lines:
            _check_account(ln["accountCode"], ["revenue"], amap, ln["line"], checks, suggested, "收入科目")
        if str(p.get("recognitionPattern") or "").lower() == "over_time":
            checks.append({"level": "warn",
                           "text": "履约方式为时段确认：开票会先贷记 2120 合同负债，收入按进度另行确认，"
                                   "不会在开票时一次确认"})

    elif workflow == "expense":
        if _dec(p.get("amount")) <= 0:
            checks.append({"level": "block", "text": "金额必须大于 0"})
        _check_account(str(p.get("expenseAccountCode") or "").strip(), ["expense", "cogs"],
                       amap, 1, checks, suggested, "费用科目")
        checks.append({"level": "info",
                       "text": "费用单是备查与附件载体，不直接生成总账分录；需要入账请关联或另建账单"})
        if not p.get("receiptPath"):
            checks.append({"level": "warn", "text": "没有上传票据附件，税前扣除可能缺凭证"})

    elif workflow in ("payment", "receipt"):
        amount = _dec(p.get("amount"))
        if amount <= 0:
            checks.append({"level": "block", "text": "金额必须大于 0"})
        b = _bank(entity_id, p.get("bankAccountId"))
        if not b:
            checks.append({"level": "block", "text": "未选择银行账户"})
        else:
            extra["bankCode"] = b["account_code"]
            if str(b["currency"]).upper() != str(p.get("currency") or "HKD").upper():
                checks.append({"level": "warn",
                               "text": f"{'付款' if workflow == 'payment' else '收款'}币种 {p.get('currency')}"
                                       f" 与银行账户 {b['name']}（{b['currency']}）不一致，"
                                       "核销时需按结算日汇率折算"})
        allocs = p.get("allocations") or []
        alloc_sum = sum((_dec(a.get("amount")) for a in allocs if isinstance(a, dict)), Decimal("0"))
        if not allocs:
            checks.append({"level": "warn", "text": "没有勾选待核销单据；未分配金额会进预收/预付科目"})
        elif alloc_sum > amount:
            checks.append({"level": "block",
                           "text": f"核销合计 {alloc_sum} 超过登记金额 {amount}"})
        elif alloc_sum < amount:
            diff = amount - alloc_sum
            checks.append({"level": "warn",
                           "text": f"有 {diff} 未分配，将作为"
                                   + ("预付（1150）" if workflow == "payment" else "预收（2120）")})
        if str(p.get("currency") or "").upper() != "HKD":
            checks.append({"level": "warn", "text": "外币收付款：请确认已按结算日汇率登记"})
        if workflow == "payment" and not (p.get("vendorId") or p.get("vendorName")):
            checks.append({"level": "warn", "text": "未指定收款方（供应商）"})
        if workflow == "receipt" and not (p.get("customerId") or p.get("customerName")):
            checks.append({"level": "warn", "text": "未指定付款方（客户）"})

    elif workflow == "credit_note":
        is_cust = str(p.get("creditType") or "customer") != "vendor"
        if not str(p.get("partyName") or p.get("party") or "").strip():
            checks.append({"level": "block", "text": "未选择往来单位"})
        if _dec(p.get("amountOriginal") or p.get("amount")) <= 0:
            checks.append({"level": "block", "text": "金额必须大于 0"})
        if not str(p.get("reason") or "").strip():
            checks.append({"level": "warn", "text": "未填写贷记原因，审计时难以解释"})
        code = str(p.get("revenueAccountCode") or "").strip()
        if is_cust:
            _check_account(code or "4100", ["revenue"], amap, 1, checks, suggested, "收入科目")
        else:
            _check_account(code or "6200", ["expense", "cogs"], amap, 1, checks, suggested, "费用科目")
        if not (p.get("sourceInvoiceId") or p.get("sourceBillId")):
            checks.append({"level": "warn",
                           "text": "未关联原单；过账后不会自动冲减原单未收/未付余额"})

    elif workflow == "journal":
        total_dr = sum((_dec(ln.get("debit")) for ln in p.get("lines") or [] if isinstance(ln, dict)),
                       Decimal("0"))
        total_cr = sum((_dec(ln.get("credit")) for ln in p.get("lines") or [] if isinstance(ln, dict)),
                       Decimal("0"))
        if total_dr != total_cr:
            checks.append({"level": "block", "text": f"借贷不平：借方 {total_dr}，贷方 {total_cr}"})
        elif total_dr == 0:
            checks.append({"level": "warn", "text": "借贷都是 0，分录没有金额"})
        for i, ln in enumerate(p.get("lines") or [], 1):
            if not isinstance(ln, dict):
                continue
            dr, cr = _dec(ln.get("debit")), _dec(ln.get("credit"))
            if dr and cr:
                checks.append({"level": "block", "text": f"第 {i} 行借贷同时有值"})
            _check_account(str(ln.get("accountCode") or ""),
                           ["asset", "liability", "equity", "revenue", "cogs", "expense"],
                           amap, i, checks, suggested, "科目")

    if not any(c["level"] in ("warn", "block") for c in checks):
        checks.append({"level": "info", "text": "规则校验通过，未发现硬性问题"})

    payload_lines = [{**ln, "amount": float(ln["amount"]), "quantity": float(ln["quantity"]),
                      "unitPrice": float(ln["unitPrice"]), "taxAmount": float(ln["taxAmount"]),
                      "taxRate": float(ln["taxRate"])}
                     for ln in lines]
    doc_amount = (_dec(p.get("amount")) or _dec(p.get("amountOriginal"))
                  or sum((ln["amount"] for ln in lines), Decimal("0")))
    if workflow == "journal":
        doc_amount = sum((_dec(l.get("debit")) for l in p.get("lines") or [] if isinstance(l, dict)),
                         Decimal("0"))
    document = {"workflow": workflow, "label": spec["label"],
                "party": p.get("partyName") or p.get("party") or p.get("vendorName")
                         or p.get("customerName") or "",
                "date": day, "currency": str(p.get("currency") or "HKD").upper(),
                "amount": float(doc_amount)}
    if workflow in ("payment", "receipt"):
        document["bank"] = str(p.get("bankName") or "")
        document["allocations"] = [{"docId": a.get("docId"), "amount": _f(a.get("amount"))}
                                   for a in (p.get("allocations") or []) if isinstance(a, dict)]
    if workflow == "expense":
        document["accountCode"] = str(p.get("expenseAccountCode") or "")
    if workflow == "credit_note":
        document["creditType"] = "vendor" if str(p.get("creditType")) == "vendor" else "customer"
        document["reason"] = str(p.get("reason") or "")
        document["sourceLinked"] = bool(p.get("sourceInvoiceId") or p.get("sourceBillId"))
    return {"document": document,
            "lines": payload_lines, "checks": checks, "accounts": suggested,
            "journal": _journal_preview(workflow, p, lines, amap, entity_id, extra)}


def _verdict(checks):
    if any(c["level"] == "block" for c in checks):
        return "block"
    if any(c["level"] == "warn" for c in checks):
        return "warn"
    return "ok"


def _merge(base_checks, ai):
    checks = list(base_checks)
    for f in (ai.get("findings") or [])[:12]:
        if not isinstance(f, dict):
            continue
        level = str(f.get("level") or "info").lower()
        if level not in ("info", "warn", "block"):
            level = "info"
        text = str(f.get("text") or "").strip()
        if text:
            checks.append({"level": level, "text": text})
    return checks


def _audit(entity_id, agent, actor, workflow, facts, output, verdict, tokens, model, error):
    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO ai_run
                    (entity_id, agent, trigger_by, scene, input, tools_used, output,
                     verdict, tokens, latency_ms, model, error)
                    VALUES (%s,%s,%s,%s,%s,'[]',%s,%s,%s,0,%s,%s)""",
                    (entity_id, agent, actor, f"precheck:{workflow}",
                     json.dumps(facts, ensure_ascii=False)[:60000],
                     (output or "")[:60000], verdict, tokens, model, (error or "")[:400]))
    except Exception:
        pass


def run(workflow, payload, *, entity_id, doc_id=None, actor="owner", lang="zh_cn"):
    if workflow not in WORKFLOWS:
        raise ValueError("未知的预判流程")
    spec = WORKFLOWS[workflow]
    agent = spec["agent"]
    facts = _build(workflow, payload or {}, entity_id, doc_id)
    checks = facts["checks"]
    source, model, tokens, ai_error = "rules", None, 0, None
    summary = "规则校验完成，请人工确认后提交"
    confirm = []

    if llm.available():
        sys_prompt = registry.prompt(agent) + """

你现在做「提交前预判」。只审查下面的事实，不调用工具、不查账、不写账。
事实里的金额与科目都是系统算好的，直接引用，不得心算、改数或编造。
任务：判断这张单据现在提交会不会出问题，并指出人需要确认的点。
输出严格 JSON（不要 markdown）：
""" + SCHEMA + """
判定口径：确定违反会计准则或系统硬规则 → block；需要人判断/有风险 → warn；没问题 → ok。
最多 8 条 findings，每条不超过 60 字，必须引用具体科目或金额。
rulesFindings 是系统已做的确定性校验；不要原样复述，只补充它没覆盖的判断。
跨币种收付款是正常业务，币种不一致用 warn 并提醒折算，不要判 block。
只有订单、账单、发票有明细行；收付款、费用单、贷记单、手工凭证以金额/分录为准，
lines 为空是正常的，不要因此判定缺明细。
"""
        user = json.dumps({"workflow": workflow, "title": spec["label"],
                           "facts": {"document": facts["document"], "lines": facts["lines"],
                                     "rulesFindings": checks, "journalPreview": facts["journal"],
                                     "language": lang}},
                          ensure_ascii=False)
        try:
            r = llm.chat([{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": user}],
                         temperature=0.1, max_tokens=900, json_mode=True)
            tokens = r["tokens"]
            model = r["model"]
            ai = json.loads((r["message"].get("content") or "{}").strip())
            checks = _merge(checks, ai)
            summary = str(ai.get("summary") or summary).strip()[:300]
            confirm = [str(x)[:120] for x in (ai.get("confirm") or []) if str(x).strip()][:8]
            source = "ai"
        except Exception as exc:                    # 模型不可用 / 输出不合法 → 规则预判
            ai_error = str(exc)[:300]

    verdict = _verdict(checks)
    result = {"ok": True, "workflow": workflow, "label": spec["label"],
              "agent": agent, "agentLabel": registry.labels().get(agent, agent),
              "verdict": verdict, "summary": summary, "findings": checks,
              "accounts": facts["accounts"], "journalPreview": facts["journal"],
              "confirm": confirm, "source": source, "model": model, "tokens": tokens,
              "disclaimer": "AI-assisted, subject to human review"}
    if ai_error:
        result["llmError"] = ai_error
    _audit(entity_id, agent, actor, workflow, facts, json.dumps(result, ensure_ascii=False),
           {"ok": "PASS", "warn": "REVIEW", "block": "FAIL"}[verdict], tokens, model, ai_error)
    return result
