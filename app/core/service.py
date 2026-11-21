# LtBooks — core/service.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""业务服务：录入 → 确定性校验 → 智能体校验 → draft；过账、冲销、重估。"""
import json
from datetime import date, datetime
from pathlib import Path

import yaml

from config import RULES_DIR
from jsonenc import Encoder
from . import agent, reports
from .audit import GENESIS, append_record
from .bankrec import DISCLAIMER as BR_DISC
from .db import query, query_one, transaction
from .fx import normalize_policy, revalue_items, lookup_rate
from .hkfrs15 import assess
from .money import convert, dec, period_of, quantize_money, retention_until
from .numbering import next_no, peek_no
from .agents.runtime import guard_check

DISCLAIMER = "AI-assisted, subject to human review"
_rules_cache = None


def load_rules():
    global _rules_cache
    if _rules_cache is None:
        def load(name):
            with open(Path(RULES_DIR) / name, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        _rules_cache = {"hkfrs15": load("hkfrs15.yml"),
                        "fx_policy": load("fx_policy.yml"),
                        "tax_whitelist": load("tax_rate_whitelist.yml")}
    return _rules_cache


def load_entity(conn=None):
    sql = "SELECT * FROM entities WHERE status='active' ORDER BY entity_id LIMIT 1"
    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()
    return query_one(sql)


def _rates(conn, frm, to, through, days=10):
    """取汇率：窗口取「前 N 天到后 N 天」。

    只往前找会漏掉常见情形——发票 12 日开、信用卡 15 日结算，
    银行实际用的汇率 15 日才出现。窗口内前后都取，优先最近的一条。
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT rate_date, from_ccy, to_ccy, rate, source FROM fx_rates
                WHERE from_ccy=%s AND to_ccy=%s
                  AND rate_date BETWEEN DATE_SUB(%s, INTERVAL %s DAY)
                                    AND DATE_ADD(%s, INTERVAL %s DAY)
                ORDER BY ABS(DATEDIFF(rate_date, %s)) ASC, rate_date DESC""",
            (frm, to, through, days, through, days, through))
        return cur.fetchall()


def append_audit(conn, ev):
    with conn.cursor() as cur:
        cur.execute("""SELECT seq_no, record_hash FROM audit_log
                        WHERE entity_id=%s ORDER BY seq_no DESC LIMIT 1""", (ev["entity_id"],))
        tail = cur.fetchall()
        prev = tail[0]["record_hash"] if tail else GENESIS
        seq = (tail[0]["seq_no"] + 1) if tail else 1
        # 时间戳必须在算哈希之前确定：若交给 NOW(3) 填充，
        # 哈希里的 created_at 与实际入库值不一致，链会当场断开。
        created_at = ev.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        # 智能体执行的动作统一记 actor_role=agent：审计里一眼分得清人和机器
        role = ev.get("actor_role")
        if role is None:
            role = "agent" if str(ev["actor"]).startswith("agent:") else "accountant"
        payload = {
            "entity_id": ev["entity_id"], "seq_no": seq, "actor": ev["actor"],
            "actor_role": role, "action": ev["action"],
            "object_type": ev.get("object_type"), "object_id": ev.get("object_id"),
            "detail": ev.get("detail"), "client_ip": ev.get("client_ip"),
            "created_at": created_at,
        }
        rec = append_record(payload, prev)
        cur.execute("""INSERT INTO audit_log
            (entity_id,seq_no,actor,actor_role,action,object_type,object_id,detail,client_ip,prev_hash,record_hash,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (rec["entity_id"], rec["seq_no"], rec["actor"], rec["actor_role"], rec["action"],
             rec["object_type"], rec["object_id"],
             json.dumps(rec["detail"], ensure_ascii=False, cls=Encoder) if rec["detail"] is not None else None,
             rec["client_ip"], rec["prev_hash"], rec["record_hash"], rec["created_at"]))
        return {"seq_no": rec["seq_no"], "record_hash": rec["record_hash"]}


def add_pending(conn, item):
    with conn.cursor() as cur:
        # 同一条原因重复提交时不再堆叠：重跑重估/校验会不断产生相同待办，
        # 队列被淹没后人工无法处理。
        cur.execute("""SELECT review_id FROM pending_review
                        WHERE entity_id=%s AND kind=%s AND reason=%s AND status='open'
                          AND ref_table <=> %s AND ref_id <=> %s LIMIT 1""",
                    (item["entityId"], item["kind"], item["reason"],
                     item.get("refTable"), item.get("refId")))
        dup = cur.fetchone()
        if dup:
            return dup["review_id"]
        cur.execute("""INSERT INTO pending_review (entity_id,kind,ref_table,ref_id,reason,payload,severity,status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'open')""",
                    (item["entityId"], item["kind"], item.get("refTable"), item.get("refId"),
                     item["reason"], json.dumps(item.get("payload") or {}, ensure_ascii=False, cls=Encoder),
                     item.get("severity", "warning")))
        return cur.lastrowid


def load_audit_chain(entity_id, limit=20000):
    rows = query("""SELECT entity_id,seq_no,actor,actor_role,action,object_type,object_id,
                           detail,client_ip,prev_hash,record_hash,created_at
                      FROM audit_log WHERE entity_id=%s ORDER BY seq_no LIMIT %s""",
                 (entity_id, limit))
    out = []
    for r in rows:
        d = r["detail"]
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except Exception:
                d = None
        out.append(dict(r, detail=d, created_at=r["created_at"].isoformat(sep=" ", timespec="milliseconds") if hasattr(r["created_at"], "isoformat") else str(r["created_at"])))
    return out


# ---------------------------------------------------------------- 发票
def create_invoice(payload, actor="system", invoice_id=None):
    """新建发票；invoice_id 不为空时改为更新一张草稿（编号不变）。"""
    rules = load_rules()
    policy = normalize_policy(rules["fx_policy"])
    wl = rules["tax_whitelist"]

    with transaction() as conn:
        entity = load_entity(conn)
        if not entity:
            raise ValueError("没有启用的实体")

        existing = None
        if invoice_id is not None:
            with conn.cursor() as cur:
                cur.execute("""SELECT * FROM invoices
                                WHERE invoice_id=%s AND entity_id=%s FOR UPDATE""",
                            (int(invoice_id), entity["entity_id"]))
                existing = cur.fetchone()
            if not existing:
                raise ValueError("发票不存在")
            if existing["status"] != "draft":
                raise ValueError("只有草稿发票可以编辑；已过账发票请先冲销")

        ccy = str(payload.get("currency") or "HKD").upper()

        # 明细行：有则按「数量 × 单价」汇总，金额由系统算，避免手填总额与明细对不上
        raw_lines = payload.get("lines") or []
        norm_lines = []
        for i, ln in enumerate(raw_lines, start=1):
            desc = str(ln.get("description") or "").strip()
            if not desc:
                continue
            qty = dec(ln.get("quantity")) if ln.get("quantity") not in (None, "") else dec(1)
            price = dec(ln.get("unitPrice")) if ln.get("unitPrice") not in (None, "") else dec(0)
            if qty is None or price is None:
                raise ValueError(f"第 {i} 行数量或单价非法")
            # 行折扣与金额、税额一起提交，编辑时可按同一口径重算。
            line_discount = dec(ln.get("discountRate") or 0) or dec(0)
            if line_discount < 0 or line_discount > 100:
                raise ValueError(f"第 {i} 行折扣率必须在 0–100 之间")
            amt_in = ln.get("amount")
            if "discountRate" in ln:
                line_amount = quantize_money(qty * price * (dec(1) - line_discount / dec(100)))[0]
            elif amt_in not in (None, ""):
                line_amount = quantize_money(amt_in)[0]
                if line_amount is None:
                    raise ValueError(f"第 {i} 行金额非法")
                if (price is None or price == 0) and qty:
                    price = (line_amount / qty).quantize(dec("0.0001"))
            else:
                line_amount = quantize_money(qty * price)[0]
                if line_amount is None:
                    raise ValueError(f"第 {i} 行金额无法计算")
            tax_rate = dec(ln.get("taxRate")) if ln.get("taxRate") not in (None, "") else None
            tax_in = ln.get("taxAmount")
            if tax_in not in (None, ""):
                tax_amt = quantize_money(tax_in)[0] or dec(0)
                if (tax_rate is None or tax_rate == 0) and line_amount:
                    tax_rate = (tax_amt / line_amount * 100).quantize(dec("0.0001"))
            else:
                tax_amt = quantize_money(line_amount * (tax_rate or 0) / 100)[0] if tax_rate else dec(0)
            norm_lines.append({
                "lineNo": i, "itemCode": (str(ln.get("itemCode") or "").strip() or None),
                "description": desc[:400],
                "accountCode": (str(ln.get("accountCode") or "").strip() or None),
                "unit": (str(ln.get("unit") or "").strip() or None)[:32] if ln.get("unit") else None,
                "quantity": qty, "unitPrice": price, "amount": line_amount,
                "taxRate": tax_rate, "taxAmount": tax_amt,
                "notes": (str(ln.get("notes") or "").strip() or None),
            })

        # 折扣：只能通过折扣调整金额，明细合价本身不可改
        discount_rate = dec(payload.get("discountRate") or 0) or dec(0)
        discount = dec(payload.get("discountOriginal") or 0)
        if discount is None or discount < 0:
            raise ValueError("折扣金额非法")
        if discount_rate is None or discount_rate < 0 or discount_rate > 100:
            raise ValueError("折扣率必须在 0–100 之间")

        if norm_lines:
            line_sum = sum((l["amount"] for l in norm_lines), dec(0))
            line_tax = sum((l["taxAmount"] for l in norm_lines), dec(0))
            # 整单折扣：按折扣率重算金额，没填率才用手填的金额
            if discount_rate:
                discount = quantize_money(line_sum * discount_rate / dec(100))[0]
            if discount > line_sum:
                raise ValueError("折扣不能大于明细合价合计")
            amount = quantize_money(line_sum - discount)[0]
            # 税额按折扣后的比例同步，避免折扣部分仍在收税
            ratio = (amount / line_sum) if line_sum else dec(0)
            tax = quantize_money(line_tax * ratio)[0]
            amount_rounded = tax_rounded = None
        else:
            amount, amount_rounded = quantize_money(payload.get("amountOriginal"))
            tax, tax_rounded = quantize_money(payload.get("taxOriginal", 0))
        if amount is None or amount < 0:
            raise ValueError("amountOriginal 非法")
        if tax is None or tax < 0:
            raise ValueError("taxOriginal 非法")

        inv_date = payload.get("invoiceDate")
        recog = payload.get("revenueRecognitionDate") or inv_date
        if inv_date and payload.get("dueDate") and str(payload["dueDate"]) < str(inv_date):
            raise ValueError("到期日不能早于发票日期")
        gross = amount + tax
        implied = dec(0) if amount == 0 else (tax / amount)

        checks, severity = [], None
        fx_rate, fx_date, fx_tag = dec(1), inv_date, "identity"
        functional, tax_fn = amount, tax

        manual_func_inv = payload.get("amountFunctionalOverride")
        if ccy != entity["functional_currency"] and manual_func_inv not in (None, "", 0):
            # 人指定了折算金额：按它入账，隐含汇率记下来
            from decimal import Decimal as _D
            functional = quantize_money(manual_func_inv)[0]
            tax_fn = quantize_money(float(functional) * float(tax) / float(amount))[0] if amount else dec(0)
            if amount and amount > 0:
                fx_rate = (functional / amount).quantize(_D("0.0000000001"))
            fx_tag = "manual"
            checks.append({"step": "fx", "status": "PASS",
                           "reason": f"按人工指定的折算金额 {float(functional):,.2f} HKD 入账"})
        elif ccy != entity["functional_currency"]:
            rates = _rates(conn, ccy, entity["functional_currency"], recog)
            from .fx import lookup_rate
            look = lookup_rate([dict(r) for r in rates], recog, ccy, entity["functional_currency"], policy)
            if not look["ok"]:
                checks.append({"step": "fx", "status": "FAIL", "reason": look["reason"]})
                severity = "blocker"
                fx_rate = None
                functional = None
                tax_fn = None
            else:
                fx_rate = dec(look["rate"])
                fx_date = look["rateDate"]
                fx_tag = "ECB:fallback" if look["isFallback"] else "ECB"
                functional = convert(amount, fx_rate)
                tax_fn = convert(tax, fx_rate)

        allowed = wl.get("allowed_rates") or []
        tol = dec(wl.get("tolerance", "0.0001"))
        rate_ok = any(abs(dec(r) - implied) <= tol for r in allowed)
        if not rate_ok and amount > 0:
            checks.append({"step": "tax_rate", "status": "FAIL",
                           "reason": f"反推税率 {float(implied)*100:.4f}% 不在白名单 "
                                     f"[{', '.join(str(int(float(r)*100))+'%' for r in allowed)}] 内"})
            severity = severity or "blocker"
        else:
            checks.append({"step": "tax_rate", "status": "PASS",
                           "reason": f"反推税率 {float(implied)*100:.4f}% 在白名单内"})

        po = str(payload.get("performanceObligationStatus") or "undetermined")
        rev = assess(rules["hkfrs15"], po, payload.get("recognitionPattern"),
                     payload.get("hasUnconditionalRightToPayment"), amount, payload.get("confidence"))
        checks.append({"step": "hkfrs15",
                       "status": "PASS" if rev["decision"] == "determined" else "REVIEW",
                       "reason": (f"{po} → 借 {rev['debit']['logical']} / 贷 {rev['credit']['logical']}"
                                  f"（规则 v{rev['ruleVersion']}）")
                                 if rev["decision"] == "determined" else rev["reason"]})
        if rev["decision"] != "determined":
            severity = severity or "warning"

        basis_amount = functional if functional is not None else (
            amount if ccy == entity["functional_currency"] else None)
        # HKFRS15 没匹配到规则时（例如手填的销售发票只写了摘要），
        # 也要给出默认的应收 / 收入科目，否则校验层看到「分录没有任何行」会永久阻断过账。
        debit_code = (rev.get("debit") or {}).get("code") or "1130"
        credit_code = (rev.get("credit") or {}).get("code") or "4100"
        if not (rev.get("credit") or {}).get("code"):
            rev = dict(rev)
            rev["credit"] = {**(rev.get("credit") or {}), "code": credit_code}
        lines = []
        if basis_amount is not None:
            lines.append({"accountCode": debit_code, "debit": float(basis_amount)})
            lines.append({"accountCode": credit_code, "credit": float(basis_amount)})

        chk = agent.check_entry({
            "entryId": None, "preparedBy": actor, "reviewedBy": payload.get("reviewedBy"),
            "requiredDocuments": payload.get("requiredDocuments") or [],
            "documents": payload.get("documents") or [],
            "lines": lines,
        })
        checks.append({"step": "agent", "tool": agent.TOOL_CHECK, "status": chk["verdict"],
                       "reason": "机械校验通过（不构成过账授权）" if chk["verdict"] == "PASS"
                                 else "；".join(chk["blockedReasons"] + chk["reviewReasons"])})
        if chk["verdict"] == "FAIL":
            severity = "blocker"

        rounding_notes = []
        if amount_rounded:
            rounding_notes.append(f"金额已四舍五入到分：{payload.get('amountOriginal')} → {amount}")
        if tax_rounded:
            rounding_notes.append(f"税额已四舍五入到分：{payload.get('taxOriginal')} → {tax}")
        # 编号允许自定义；若用的正是系统预览号，就把序号推进一格，
        # 否则每张都拿同一个预览号，序号永远停在 001。
        if existing:
            invoice_no = existing["invoice_no"]
        else:
            supplied_no = (payload.get("invoiceNo") or "").strip()
            try:
                peeked = peek_no(conn, entity["entity_id"], inv_date, "invoice")
            except Exception:
                peeked = ""
            if supplied_no and supplied_no != peeked:
                # 用户自己改了编号：原样采用（重号由唯一约束拦下）
                invoice_no = supplied_no
            else:
                # 系统编号：序号可能落后于实际已用号（历史数据、已作废单据），
                # 逐个试到未被占用为止，避免撞 uk_invoices_no_supplier。
                invoice_no = None
                for _ in range(500):
                    cand = next_no(conn, entity["entity_id"], inv_date, "invoice")
                    with conn.cursor() as _c:
                        _c.execute("""SELECT 1 FROM invoices
                                       WHERE entity_id=%s AND invoice_no=%s LIMIT 1""",
                                   (entity["entity_id"], cand))
                        if _c.fetchone() is None:
                            invoice_no = cand
                            break
                if invoice_no is None:
                    raise ValueError("无法分配发票编号，请手工指定")
        retention = retention_until(recog, inv_date)
        with conn.cursor() as cur:
            cust_name = str(payload.get("supplierName") or payload.get("customerName") or "").strip()
            if existing:
                cur.execute("""UPDATE invoices SET
                    supplier_name=%s, customer_id=%s, subject=%s, order_number=%s,
                    payment_terms=%s, salesperson=%s, billing_address=%s, shipping_address=%s,
                    customer_notes=%s, terms_conditions=%s, invoice_date=%s, due_date=%s,
                    revenue_recognition_date=%s, currency=%s, amount_original=%s,
                    tax_original=%s, gross_original=%s, discount_original=%s,
                    discount_rate=%s, tax_rate_implied=%s, amount_functional=%s,
                    tax_functional=%s, fx_rate=%s, fx_rate_date=%s, fx_rate_policy=%s,
                    performance_obligation_status=%s, recognition_pattern=%s,
                    revenue_account_code=%s, contract_asset_amount=%s,
                    contract_liability_amount=%s, confidence=%s, source_file_path=%s,
                    matched_rule_id=%s, retention_until=%s,
                    review_status='draft', approved_by=NULL, approved_at=NULL,
                    approval_note=NULL
                  WHERE invoice_id=%s AND entity_id=%s AND status='draft'""",
                    (cust_name, payload.get("customerId"),
                     payload.get("subject"), payload.get("orderNumber"), payload.get("paymentTerms"),
                     payload.get("salesperson"), payload.get("billingAddress"),
                     payload.get("shippingAddress"), payload.get("customerNotes"),
                     payload.get("termsConditions"),
                     inv_date, payload.get("dueDate"), recog, ccy, amount, tax, gross, discount,
                     discount_rate, implied, functional or 0, tax_fn or 0, fx_rate or 1,
                     fx_date, fx_tag, po, payload.get("recognitionPattern"),
                     (rev.get("credit") or {}).get("code"),
                     float(basis_amount) if rev["contractAssetApplied"] and basis_amount is not None else 0,
                     float(basis_amount) if rev["contractLiabilityApplied"] and basis_amount is not None else 0,
                     payload.get("confidence"), payload.get("sourceFilePath"),
                     rev.get("matchedRule"), retention,
                     invoice_id, entity["entity_id"]))
                cur.execute("DELETE FROM invoice_lines WHERE invoice_id=%s AND entity_id=%s",
                            (invoice_id, entity["entity_id"]))
                # 内容已变，旧的待复核结论作废，按新校验结果重新生成。
                cur.execute("""UPDATE pending_review SET status='resolved',
                                      resolved_by=%s, resolved_at=NOW(3)
                                WHERE entity_id=%s AND ref_table='invoices'
                                  AND ref_id=%s AND status='open'""",
                            (actor, entity["entity_id"], invoice_id))
            else:
                cur.execute("""INSERT INTO invoices
                    (entity_id,invoice_no,supplier_name,customer_id,subject,order_number,payment_terms,
                     salesperson,billing_address,shipping_address,customer_notes,terms_conditions,
                     invoice_date,due_date,revenue_recognition_date,
                     currency,amount_original,tax_original,gross_original,discount_original,discount_rate,tax_rate_implied,
                     amount_functional,tax_functional,fx_rate,fx_rate_date,fx_rate_policy,
                     performance_obligation_status,recognition_pattern,revenue_account_code,
                     contract_asset_amount,contract_liability_amount,confidence,source_file_path,
                     matched_rule_id,status,created_by,retention_until)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s)""",
                    (entity["entity_id"], invoice_no,
                     cust_name, payload.get("customerId"),
                     payload.get("subject"), payload.get("orderNumber"), payload.get("paymentTerms"),
                     payload.get("salesperson"), payload.get("billingAddress"),
                     payload.get("shippingAddress"), payload.get("customerNotes"),
                     payload.get("termsConditions"),
                     inv_date, payload.get("dueDate"), recog, ccy, amount, tax, gross, discount, discount_rate, implied,
                     functional or 0, tax_fn or 0, fx_rate or 1, fx_date, fx_tag,
                     po, payload.get("recognitionPattern"),
                     (rev.get("credit") or {}).get("code"),
                     float(basis_amount) if rev["contractAssetApplied"] and basis_amount is not None else 0,
                     float(basis_amount) if rev["contractLiabilityApplied"] and basis_amount is not None else 0,
                     payload.get("confidence"), payload.get("sourceFilePath"),
                     rev.get("matchedRule"), actor, retention))
                invoice_id = cur.lastrowid

            for ln in norm_lines:
                cur.execute("""INSERT INTO invoice_lines
                    (entity_id, invoice_id, line_no, item_code, description, unit,
                     quantity, unit_price, amount, tax_rate, tax_amount, notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (entity["entity_id"], invoice_id, ln["lineNo"], ln["itemCode"],
                     ln["description"], ln["unit"], ln["quantity"], ln["unitPrice"],
                     ln["amount"], ln["taxRate"], ln["taxAmount"], ln["notes"]))

            # 可选的合同关联：发票建立时即归入合同，也可之后在合同页补关联
            contract_id = payload.get("contractId")
            if contract_id and not existing:
                cur.execute("""SELECT contract_id, customer_name FROM revenue_contracts
                                WHERE contract_id=%s AND entity_id=%s""",
                            (int(contract_id), entity["entity_id"]))
                ct = cur.fetchone()
                if not ct:
                    raise ValueError("合同不存在")
                if str(ct["customer_name"]).strip() != str(cust_name).strip():
                    raise ValueError(
                        f"合同客户为「{ct['customer_name']}」，与本发票客户「{cust_name}」不一致，"
                        "不能关联")
                # 收入合同模块已下线：发票不再回写合同关联，
                # 需要挂合同就作为发票附件上传扫描件（invoice_files）。

        pending_ids = []
        if severity:
            primary = next((c for c in checks if c["status"] == "FAIL"),
                           next((c for c in checks if c["status"] == "REVIEW"), None))
            kind = ("tax_rate_invalid" if primary and primary["step"] == "tax_rate"
                    else "fx_missing" if primary and primary["step"] == "fx" else "invoice")
            pending_ids.append(add_pending(conn, {
                "entityId": entity["entity_id"], "kind": kind, "refTable": "invoices",
                "refId": invoice_id, "reason": (primary or {}).get("reason", "需要人工复核"),
                "severity": severity, "payload": {"checks": checks, "agentCheck": chk}}))

        append_audit(conn, {"entity_id": entity["entity_id"], "actor": actor,
                            "action": "invoice.update" if existing else "invoice.create",
                            "object_type": "invoices",
                            "object_id": str(invoice_id),
                            "detail": {"invoice_no": invoice_no,
                                       "amount": float(amount), "tax": float(tax),
                                       "currency": ccy, "verdict": chk["verdict"]}})

        return {
            "invoiceId": invoice_id, "invoiceNo": invoice_no,
            "status": "draft", "currency": ccy,
            "amountOriginal": float(amount), "taxOriginal": float(tax), "grossOriginal": float(gross),
            "fxRate": float(fx_rate) if fx_rate is not None else None,
            "fxRateDate": fx_date, "fxRatePolicy": fx_tag,
            "amountFunctional": float(functional) if functional is not None else None,
            "performanceObligationStatus": po,
            "revenueAccountCode": (rev.get("credit") or {}).get("code"),
            "checks": checks, "agentCheck": chk, "pendingReviewIds": pending_ids,
            "roundingNotes": rounding_notes,
            "canPost": chk["verdict"] == "PASS" and severity is None,
            "disclaimer": DISCLAIMER,
            "note": "草稿已更新；校验结果不构成过账授权" if existing else "草稿已保存；校验结果不构成过账授权",
        }


def mark_reconciled(entity_id, *, invoice_id=None, bill_id=None, payment_id=None, actor="system"):
    """把与单据关联的分录标为已对账，纳入财务报表。"""
    conds, params = [], []
    if invoice_id:
        conds.append("(source_type='invoice' AND source_id=%s)")
        params.append(invoice_id)
    if bill_id:
        conds.append("(source_type='bill' AND source_id=%s)")
        params.append(bill_id)
    if payment_id:
        conds.append("(source_type='payment' AND source_id=%s)")
        params.append(payment_id)
    if not conds:
        return 0
    sql = (f"UPDATE journal_entries SET report_ready=1, reconciled_at=NOW(3), reconciled_by=%s "
           f"WHERE entity_id=%s AND report_ready=0 AND ({' OR '.join(conds)})")
    with transaction() as conn:
        with conn.cursor() as cur:
            n = cur.execute(sql, tuple([actor, entity_id] + params))
    return n


def clear_stale_fx_blockers(conn, cur, entity_id, ref_table, ref_id, ccy, functional, on_date, actor="system"):
    """汇率补齐后，把之前留下的「找不到汇率」阻断项自动关掉。

    没有这一步，补录汇率之后单据仍然卡着 —— 用户只能去复核台手工点掉，
    而理由已经不成立了。这里重新查一次，能查到就认为阻断解除。
    """
    cur.execute("""SELECT review_id, reason FROM pending_review
                    WHERE entity_id=%s AND ref_table=%s AND ref_id=%s
                      AND status='open' AND severity='blocker'
                      AND reason LIKE '找不到 %%→%% 的汇率%%'""",
                (entity_id, ref_table, ref_id))
    rows = cur.fetchall()
    if not rows:
        return 0
    rates = _rates(conn, str(ccy).upper(), str(functional).upper(), on_date)
    res = lookup_rate([dict(r) for r in rates], on_date, ccy, functional, _fx_policy())
    if not res.get("ok"):
        return 0
    ids = [int(r["review_id"]) for r in rows]
    cur.execute("""UPDATE pending_review SET status='resolved', resolved_by=%s, resolved_at=NOW(3)
                    WHERE review_id IN (%s)""" % ("%s", ",".join(["%s"] * len(ids))),
                tuple([actor] + ids))
    return len(ids)


def _fx_policy():
    rules = load_rules()
    return normalize_policy(rules["fx_policy"])


def post_invoice(invoice_id, actor="system"):
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM invoices WHERE invoice_id=%s", (invoice_id,))
            inv = cur.fetchone()
            if not inv:
                raise ValueError("发票不存在")
            if inv["status"] != "draft":
                raise ValueError(f"发票状态为 {inv['status']}，不可过账")
            if (inv.get("review_status") or "draft") != "approved":
                raise ValueError("发票未经复核批准，不可过账。请先提交复核并由复核人批准。")

            _ent = load_entity(conn)
            clear_stale_fx_blockers(conn, cur, _ent["entity_id"], "invoices", invoice_id,
                                    inv["currency"], _ent["functional_currency"],
                                    inv["revenue_recognition_date"] or inv["invoice_date"], actor)
            cur.execute("""SELECT review_id, reason FROM pending_review
                            WHERE ref_table='invoices' AND ref_id=%s AND status='open' AND severity='blocker'""",
                        (invoice_id,))
            blockers = cur.fetchall()
            if blockers:
                raise ValueError("存在阻断项，不可过账：" + "；".join(b["reason"] for b in blockers))

            entity = load_entity(conn)
            entry_date = inv["revenue_recognition_date"] or inv["invoice_date"]
            entry_no = next_no(conn, entity["entity_id"], entry_date, "journal")

            # 收入按不含税净额确认，税额单独挂「销项税额」，应收按含税总额入账。
            # 早期版本把税额并进收入或直接漏掉，导致应收与收入同时错报。
            net = dec(inv["amount_functional"]) or dec(inv["amount_original"])
            tax_fn = dec(inv["tax_functional"] or 0) or dec(0)
            debit = net + tax_fn
            credit_acct = inv["revenue_account_code"] or "4100"
            debit_acct = "1140" if dec(inv["contract_asset_amount"] or 0) > 0 else "1130"

            # 按履约进度确认的发票：开票只形成合同负债，收入另按进度确认，
            # 否则同一笔会确认两次收入。收入合同模块下线后，这个判断
            # 落到发票自己的 recognition_pattern 上。
            pattern = str(inv.get("recognition_pattern") or "").lower()
            progress_contract = pattern == "over_time"
            if progress_contract:
                credit_acct = "2120"   # 合同负债：已开票但尚未按进度确认收入

            cur.execute("""INSERT INTO journal_entries
                (entity_id,entry_no,entry_date,source_type,source_id,description,status,
                 report_ready,total_debit,total_credit,created_by,retention_until)
                VALUES (%s,%s,%s,'invoice',%s,%s,'draft',0,%s,%s,%s,%s)""",
                (entity["entity_id"], entry_no, entry_date, invoice_id,
                 f"发票 {inv['invoice_no']} 确认", debit, debit, actor, inv["retention_until"]))
            entry_id = cur.lastrowid

            cur.execute("""INSERT INTO journal_lines
                (entry_id,line_no,account_code,description,debit,credit,ccy,amount_original,rate,rate_date)
                VALUES (%s,1,%s,%s,%s,0,%s,%s,%s,%s)""",
                (entry_id, debit_acct, f"发票 {inv['invoice_no']}", debit,
                 inv["currency"], inv["gross_original"], inv["fx_rate"], inv["fx_rate_date"]))
            cur.execute("""INSERT INTO journal_lines
                (entry_id,line_no,account_code,description,debit,credit,ccy,amount_original,rate,rate_date)
                VALUES (%s,2,%s,%s,0,%s,%s,%s,%s,%s)""",
                (entry_id, credit_acct, f"发票 {inv['invoice_no']}", net,
                 inv["currency"], inv["amount_original"], inv["fx_rate"], inv["fx_rate_date"]))
            if tax_fn > 0:
                cur.execute("""INSERT INTO journal_lines
                    (entry_id,line_no,account_code,description,debit,credit,ccy,amount_original,rate,rate_date)
                    VALUES (%s,3,'2140',%s,0,%s,%s,%s,%s,%s)""",
                    (entry_id, f"销项税额 {inv['invoice_no']}", tax_fn,
                     inv["currency"], inv["tax_original"], inv["fx_rate"], inv["fx_rate_date"]))

            # 把发票附件复制到凭证：日记账/凭证页也要看得到原件
            cur.execute("""INSERT INTO doc_files
                (entity_id, doc_type, doc_id, file_name, file_type, file_size,
                 sha256_hash, storage_path, uploaded_by)
                SELECT entity_id, 'journal', %s, file_name, file_type, file_size,
                       sha256_hash, storage_path, uploaded_by
                  FROM doc_files
                 WHERE entity_id=%s AND doc_type='invoice' AND doc_id=%s""",
                        (entry_id, entity["entity_id"], invoice_id))

            cur.execute("""UPDATE journal_entries SET status='posted', posted_by=%s, posted_at=NOW(3)
                            WHERE entry_id=%s""", (actor, entry_id))
            cur.execute("UPDATE invoices SET status='posted', updated_at=NOW(3) WHERE invoice_id=%s", (invoice_id,))

            append_audit(conn, {"entity_id": entity["entity_id"], "actor": actor,
                                "action": "invoice.post", "object_type": "invoices",
                                "object_id": str(invoice_id),
                                "detail": {"entry_id": entry_id, "entry_no": entry_no,
                                           "debit": float(debit), "credit": float(debit)}})
            return {"invoiceId": invoice_id, "entryId": entry_id, "entryNo": entry_no,
                    "status": "posted", "debit": float(debit), "credit": float(debit)}


def reverse_entry(entry_id, actor="system", reason=""):
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM journal_entries WHERE entry_id=%s", (entry_id,))
            orig = cur.fetchone()
            if not orig:
                raise ValueError("分录不存在")
            if orig["status"] != "posted":
                raise ValueError(f"分录状态为 {orig['status']}，只有 posted 可冲销")

            cur.execute("SELECT * FROM journal_lines WHERE entry_id=%s ORDER BY line_no", (entry_id,))
            lines = cur.fetchall()
            entry_no = next_no(conn, orig["entity_id"], date.today(), "journal")

            cur.execute("""INSERT INTO journal_entries
                (entity_id,entry_no,entry_date,source_type,source_id,description,status,
                 reversal_of_entry_id,total_debit,total_credit,created_by,retention_until)
                VALUES (%s,%s,CURDATE(),%s,%s,%s,'draft',%s,%s,%s,%s,%s)""",
                (orig["entity_id"], entry_no, orig["source_type"], orig["source_id"],
                 f"冲销 {orig['entry_no']}：{reason}", entry_id,
                 orig["total_credit"], orig["total_debit"], actor, orig["retention_until"]))
            rev_id = cur.lastrowid

            for i, l in enumerate(lines, start=1):
                cur.execute("""INSERT INTO journal_lines
                    (entry_id,line_no,account_code,description,debit,credit,ccy,amount_original,rate,rate_date)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (rev_id, i, l["account_code"], f"冲销：{l['description'] or ''}",
                     l["credit"], l["debit"], l["ccy"], l["amount_original"], l["rate"], l["rate_date"]))

            cur.execute("""UPDATE journal_entries SET status='posted', posted_by=%s, posted_at=NOW(3)
                            WHERE entry_id=%s""", (actor, rev_id))
            cur.execute("""UPDATE journal_entries SET status='reversed', reversed_by_entry_id=%s
                            WHERE entry_id=%s""", (rev_id, entry_id))

            append_audit(conn, {"entity_id": orig["entity_id"], "actor": actor,
                                "action": "journal.reverse", "object_type": "journal_entries",
                                "object_id": str(entry_id),
                                "detail": {"reversal_entry_id": rev_id, "entry_no": entry_no, "reason": reason}})
            return {"originalEntryId": entry_id, "reversalEntryId": rev_id,
                    "entryNo": entry_no, "status": "reversed"}


# ---------------------------------------------------------------- 账单/费用
def create_bill(payload, actor="system", bill_id=None):
    """新建账单；bill_id 不为空时更新草稿，保留原编号。"""
    rules = load_rules()
    policy = normalize_policy(rules["fx_policy"])
    wl = rules["tax_whitelist"]
    with transaction() as conn:
        entity = load_entity(conn)
        existing = None
        if bill_id is not None:
            with conn.cursor() as cur:
                cur.execute("""SELECT * FROM bills
                                WHERE bill_id=%s AND entity_id=%s FOR UPDATE""",
                            (int(bill_id), entity["entity_id"]))
                existing = cur.fetchone()
            if not existing:
                raise ValueError("采购发票不存在")
            if existing["status"] != "draft":
                raise ValueError("只有草稿采购发票可以编辑；已过账单据请用冲销或反向单据")
        ccy = str(payload.get("currency") or "HKD").upper()

        # 明细行：有则汇总，金额与税额由明细算出来，避免与手填总额对不上
        raw_lines = payload.get("lines") or []
        norm_lines = []
        for i, ln in enumerate(raw_lines, start=1):
            desc = str(ln.get("description") or "").strip()
            if not desc:
                continue
            qty = dec(ln.get("quantity")) if ln.get("quantity") not in (None, "") else dec(1)
            price = dec(ln.get("unitPrice")) if ln.get("unitPrice") not in (None, "") else dec(0)
            if qty is None or price is None:
                raise ValueError(f"第 {i} 行数量或单价非法")
            line_discount = dec(ln.get("discountRate") or 0) or dec(0)
            if line_discount < 0 or line_discount > 100:
                raise ValueError(f"第 {i} 行折扣率必须在 0–100 之间")
            amt_in = ln.get("amount")
            if "discountRate" in ln:
                line_amount = quantize_money(qty * price * (dec(1) - line_discount / dec(100)))[0]
            elif amt_in not in (None, ""):
                line_amount = quantize_money(amt_in)[0]
                if line_amount is None:
                    raise ValueError(f"第 {i} 行金额非法")
                if (price is None or price == 0) and qty:
                    price = (line_amount / qty).quantize(dec("0.0001"))
            else:
                line_amount = quantize_money(qty * price)[0]
            if line_amount is None:
                raise ValueError(f"第 {i} 行金额无法计算")
            tax_rate = dec(ln.get("taxRate")) if ln.get("taxRate") not in (None, "") else None
            tax_in = ln.get("taxAmount")
            if tax_in not in (None, ""):
                tax_amt = quantize_money(tax_in)[0] or dec(0)
                if (tax_rate is None or tax_rate == 0) and line_amount:
                    tax_rate = (tax_amt / line_amount * 100).quantize(dec("0.0001"))
            else:
                tax_amt = quantize_money(line_amount * (tax_rate or 0) / 100)[0] if tax_rate else dec(0)
            norm_lines.append({
                "lineNo": i, "itemCode": (str(ln.get("itemCode") or "").strip() or None),
                "description": desc[:400],
                "accountCode": (str(ln.get("accountCode") or "").strip() or None),
                "unit": (str(ln.get("unit") or "").strip() or None) if ln.get("unit") else None,
                "quantity": qty, "unitPrice": price, "amount": line_amount,
                "taxRate": tax_rate, "taxAmount": tax_amt,
                "notes": (str(ln.get("notes") or "").strip() or None),
            })

        discount_rate = dec(payload.get("discountRate") or 0) or dec(0)
        discount = dec(payload.get("discountOriginal") or 0)
        if discount is None or discount < 0:
            raise ValueError("折扣金额非法")
        if discount_rate is None or discount_rate < 0 or discount_rate > 100:
            raise ValueError("折扣率必须在 0–100 之间")

        if norm_lines:
            line_sum = sum((l["amount"] for l in norm_lines), dec(0))
            line_tax = sum((l["taxAmount"] for l in norm_lines), dec(0))
            # 整单折扣：按折扣率重算金额，没填率才用手填的金额
            if discount_rate:
                discount = quantize_money(line_sum * discount_rate / dec(100))[0]
            if discount > line_sum:
                raise ValueError("折扣不能大于明细合价合计")
            amount = quantize_money(line_sum - discount)[0]
            ratio = (amount / line_sum) if line_sum else dec(0)
            tax = quantize_money(line_tax * ratio)[0]
            amount_rounded = tax_rounded = None
        else:
            amount, amount_rounded = quantize_money(payload.get("amount"))
            tax, tax_rounded = quantize_money(payload.get("taxAmount", 0))
            if discount:
                amount = quantize_money(amount - discount)[0]
        rounding_notes = []
        if amount_rounded:
            rounding_notes.append(f"金额已四舍五入到分：{payload.get('amount')} → {amount}")
        if tax_rounded:
            rounding_notes.append(f"税额已四舍五入到分：{payload.get('taxAmount')} → {tax}")
        if amount is None or amount < 0:
            raise ValueError("amount 非法")
        gross = amount + tax
        implied = dec(0) if amount == 0 else tax / amount
        checks, severity = [], None

        fx_rate, fx_date, functional = dec(1), payload.get("date"), amount
        manual_func = payload.get("amountFunctionalOverride")
        if ccy != entity["functional_currency"] and manual_func not in (None, "", 0):
            # 人指定了折算金额：按它入账，并把隐含汇率记下来（审计可追溯）
            from decimal import Decimal as _D
            functional = quantize_money(manual_func)[0]
            if amount and amount > 0:
                fx_rate = (functional / amount).quantize(_D("0.0000000001"))
            checks.append({"step": "fx", "status": "PASS",
                           "reason": f"按人工指定的折算金额 {float(functional):,.2f} HKD 入账"})
        elif ccy != entity["functional_currency"]:
            from .fx import lookup_rate
            rates = [dict(r) for r in _rates(conn, ccy, entity["functional_currency"], payload.get("date"))]
            look = lookup_rate(rates, payload.get("date"), ccy, entity["functional_currency"], policy)
            if not look["ok"]:
                checks.append({"step": "fx", "status": "FAIL", "reason": look["reason"]})
                severity, fx_rate, functional = "blocker", None, None
            else:
                fx_rate = dec(look["rate"])
                fx_date = look["rateDate"]
                functional = convert(amount, fx_rate)

        allowed = wl.get("allowed_rates") or []
        tol = dec(wl.get("tolerance", "0.0001"))
        if not any(abs(dec(r) - implied) <= tol for r in allowed) and amount > 0:
            checks.append({"step": "tax_rate", "status": "FAIL",
                           "reason": f"反推税率 {float(implied)*100:.4f}% 不在白名单内"})
            severity = severity or "blocker"
        else:
            checks.append({"step": "tax_rate", "status": "PASS", "reason": "税率在白名单内"})

        acct = payload.get("expenseAccountCode") or "6600"
        lines = [] if functional is None else [
            {"accountCode": acct, "debit": float(functional)},
            {"accountCode": "2110", "credit": float(functional)},
        ]
        chk = agent.check_entry({"preparedBy": actor, "reviewedBy": payload.get("reviewedBy"),
                                 "requiredDocuments": payload.get("requiredDocuments") or [],
                                 "documents": payload.get("documents") or [], "lines": lines})
        checks.append({"step": "agent", "tool": agent.TOOL_CHECK, "status": chk["verdict"],
                       "reason": "机械校验通过（不构成过账授权）" if chk["verdict"] == "PASS"
                                 else "；".join(chk["blockedReasons"] + chk["reviewReasons"])})
        if chk["verdict"] == "FAIL":
            severity = "blocker"

        bill_date = payload.get("date")
        if bill_date and payload.get("dueDate") and str(payload["dueDate"]) < str(bill_date):
            raise ValueError("到期日不能早于账单日期")
        if existing:
            bill_no = existing["bill_no"]
        else:
            supplied_no = (payload.get("billNo") or "").strip()
            try:
                peeked = peek_no(conn, entity["entity_id"], bill_date, "bill")
            except Exception:
                peeked = ""
            if supplied_no and supplied_no != peeked:
                bill_no = supplied_no
            else:
                bill_no = None
                for _ in range(500):
                    cand = next_no(conn, entity["entity_id"], bill_date, "bill")
                    with conn.cursor() as _c:
                        _c.execute("""SELECT 1 FROM bills
                                       WHERE entity_id=%s AND bill_no=%s LIMIT 1""",
                                   (entity["entity_id"], cand))
                        if _c.fetchone() is None:
                            bill_no = cand
                            break
                if bill_no is None:
                    raise ValueError("无法分配账单编号，请手工指定")
        with conn.cursor() as cur:
            # 供应商可能尚未建档：先按名称匹配，匹配不到留空，绝不擅自新建主数据
            vendor_id = payload.get("vendorId")
            vendor_name = (payload.get("vendorName") or "").strip()
            if not vendor_id and vendor_name:
                cur.execute("""SELECT vendor_id FROM vendors
                                WHERE entity_id=%s AND vendor_name=%s LIMIT 1""",
                            (entity["entity_id"], vendor_name))
                hit = cur.fetchone()
                vendor_id = hit["vendor_id"] if hit else None

            payable_acct = str(payload.get("payableAccountCode") or "").strip() or None
            retention = retention_until(bill_date, bill_date)
            if existing:
                cur.execute("""UPDATE bills SET
                    vendor_invoice_no=%s, vendor_id=%s, vendor_name=%s,
                    subject=%s, order_number=%s, payment_terms=%s, vendor_address=%s,
                    vendor_notes=%s, terms_conditions=%s, date=%s, due_date=%s,
                    currency=%s, amount=%s, tax_amount=%s, gross_original=%s,
                    discount_original=%s, discount_rate=%s, tax_rate_implied=%s,
                    amount_functional=%s, fx_rate=%s, fx_rate_date=%s,
                    expense_account_code=%s, payable_account_code=%s, retention_until=%s,
                    review_status='draft', approved_by=NULL, approved_at=NULL, approval_note=NULL
                  WHERE bill_id=%s AND entity_id=%s AND status='draft'""",
                    (payload.get("vendorInvoiceNo"), vendor_id, vendor_name or None,
                     payload.get("subject"), payload.get("orderNumber"),
                     payload.get("paymentTerms"), payload.get("vendorAddress"),
                     payload.get("vendorNotes"), payload.get("termsConditions"),
                     bill_date, payload.get("dueDate"), ccy, amount, tax, gross,
                     discount, discount_rate, implied, functional or 0, fx_rate or 1,
                     fx_date, acct, payable_acct, retention,
                     bill_id, entity["entity_id"]))
                cur.execute("DELETE FROM bill_lines WHERE bill_id=%s AND entity_id=%s",
                            (bill_id, entity["entity_id"]))
                cur.execute("""UPDATE pending_review SET status='resolved',
                                      resolved_by=%s, resolved_at=NOW(3)
                                WHERE entity_id=%s AND ref_table='bills'
                                  AND ref_id=%s AND status='open'""",
                            (actor, entity["entity_id"], bill_id))
            else:
                cur.execute("""INSERT INTO bills
                    (entity_id, bill_no, vendor_invoice_no, vendor_id, vendor_name,
                     subject, order_number, payment_terms, vendor_address, vendor_notes, terms_conditions,
                     date, due_date,
                     currency, amount, tax_amount, gross_original, discount_original, discount_rate, tax_rate_implied,
                     amount_functional, fx_rate, fx_rate_date, expense_account_code,
                     payable_account_code,
                     status, created_by, retention_until)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s)""",
                            (entity["entity_id"], bill_no, payload.get("vendorInvoiceNo"),
                             vendor_id, vendor_name or None,
                             payload.get("subject"), payload.get("orderNumber"),
                             payload.get("paymentTerms"), payload.get("vendorAddress"),
                             payload.get("vendorNotes"), payload.get("termsConditions"),
                             bill_date, payload.get("dueDate"),
                             ccy, amount, tax, gross, discount, discount_rate, implied, functional or 0, fx_rate or 1, fx_date,
                             acct, payable_acct, actor, retention))
                bill_id = cur.lastrowid

            for ln in norm_lines:
                cur.execute("""INSERT INTO bill_lines
                    (entity_id, bill_id, line_no, item_code, description, account_code, unit,
                     quantity, unit_price, amount, tax_rate, tax_amount, notes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (entity["entity_id"], bill_id, ln["lineNo"], ln["itemCode"],
                     ln["description"], ln.get("accountCode"),
                     ln["unit"], ln["quantity"], ln["unitPrice"],
                     ln["amount"], ln["taxRate"], ln["taxAmount"], ln["notes"]))

        pending_ids = []
        if severity:
            primary = next((c for c in checks if c["status"] == "FAIL"), None)
            pending_ids.append(add_pending(conn, {
                "entityId": entity["entity_id"],
                "kind": "fx_missing" if primary and primary["step"] == "fx" else "invoice",
                "refTable": "bills", "refId": bill_id,
                "reason": (primary or {}).get("reason", "需人工复核"),
                "severity": severity, "payload": {"checks": checks, "agentCheck": chk}}))

        append_audit(conn, {"entity_id": entity["entity_id"], "actor": actor,
                            "action": "bill.update" if existing else "bill.create",
                            "object_type": "bills", "object_id": str(bill_id),
                            "detail": {"bill_no": bill_no, "amount": float(amount),
                                       "currency": ccy, "verdict": chk["verdict"]}})
        return {"billId": bill_id, "billNo": bill_no, "status": "draft", "currency": ccy,
                "amount": float(amount), "tax": float(tax), "grossOriginal": float(gross),
                "fxRate": float(fx_rate) if fx_rate else None, "fxRateDate": fx_date,
                "amountFunctional": float(functional) if functional is not None else None,
                "checks": checks, "agentCheck": chk, "pendingReviewIds": pending_ids,
                "roundingNotes": rounding_notes,
                "canPost": chk["verdict"] == "PASS" and severity is None,
                "disclaimer": DISCLAIMER}


def create_expense(payload, actor="system", expense_id=None):
    """新建费用；expense_id 不为空时更新草稿，保留原编号。"""
    rules = load_rules()
    policy = normalize_policy(rules["fx_policy"])
    wl = rules["tax_whitelist"]
    with transaction() as conn:
        entity = load_entity(conn)
        existing = None
        if expense_id is not None:
            with conn.cursor() as cur:
                cur.execute("""SELECT * FROM expenses
                                WHERE expense_id=%s AND entity_id=%s FOR UPDATE""",
                            (int(expense_id), entity["entity_id"]))
                existing = cur.fetchone()
            if not existing:
                raise ValueError("费用单不存在")
            if existing["status"] != "draft":
                raise ValueError("只有草稿费用可以编辑；已过账费用请用冲销或反向单据")
        ccy = str(payload.get("currency") or "HKD").upper()
        amount, amount_rounded = quantize_money(payload.get("amount"))
        tax, tax_rounded = quantize_money(payload.get("taxAmount", 0))
        rounding_notes = []
        if amount_rounded:
            rounding_notes.append(f"金额已四舍五入到分：{payload.get('amount')} → {amount}")
        if tax_rounded:
            rounding_notes.append(f"税额已四舍五入到分：{payload.get('taxAmount')} → {tax}")
        if amount is None or amount < 0:
            raise ValueError("amount 非法")
        checks, severity = [], None
        fx_rate, fx_date, functional = dec(1), payload.get("date"), amount

        if ccy != entity["functional_currency"]:
            from .fx import lookup_rate
            rates = [dict(r) for r in _rates(conn, ccy, entity["functional_currency"], payload.get("date"))]
            look = lookup_rate(rates, payload.get("date"), ccy, entity["functional_currency"], policy)
            if not look["ok"]:
                checks.append({"step": "fx", "status": "FAIL", "reason": look["reason"]})
                severity, fx_rate, functional = "blocker", None, None
            else:
                fx_rate = dec(look["rate"])
                fx_date = look["rateDate"]
                functional = convert(amount, fx_rate)

        implied = dec(0) if amount == 0 else tax / amount
        allowed = wl.get("allowed_rates") or []
        tol = dec(wl.get("tolerance", "0.0001"))
        if not any(abs(dec(r) - implied) <= tol for r in allowed) and amount > 0:
            checks.append({"step": "tax_rate", "status": "FAIL",
                           "reason": f"反推税率 {float(implied)*100:.4f}% 不在白名单内"})
            severity = severity or "blocker"
        else:
            checks.append({"step": "tax_rate", "status": "PASS", "reason": "税率在白名单内"})

        acct = payload.get("expenseAccountCode") or "6600"
        lines = [] if functional is None else [
            {"accountCode": acct, "debit": float(functional)},
            {"accountCode": "1110", "credit": float(functional)},
        ]
        chk = agent.check_entry({"preparedBy": actor, "reviewedBy": payload.get("reviewedBy"),
                                 "requiredDocuments": payload.get("requiredDocuments") or [],
                                 "documents": payload.get("documents") or [], "lines": lines})
        checks.append({"step": "agent", "tool": agent.TOOL_CHECK, "status": chk["verdict"],
                       "reason": "机械校验通过（不构成过账授权）" if chk["verdict"] == "PASS"
                                 else "；".join(chk["blockedReasons"] + chk["reviewReasons"])})
        if chk["verdict"] == "FAIL":
            severity = "blocker"

        category = str(payload.get("category") or "").strip()
        if not category:
            raise ValueError("支出用途不能为空")
        if existing:
            expense_no = existing["expense_no"]
        else:
            supplied_no = (payload.get("expenseNo") or "").strip()
            try:
                peeked = peek_no(conn, entity["entity_id"], payload.get("date"), "expense")
            except Exception:
                peeked = ""
            if supplied_no and supplied_no != peeked:
                expense_no = supplied_no
            else:
                expense_no = None
                for _ in range(500):
                    cand = next_no(conn, entity["entity_id"], payload.get("date"), "expense")
                    with conn.cursor() as _c:
                        _c.execute("""SELECT 1 FROM expenses
                                       WHERE entity_id=%s AND expense_no=%s LIMIT 1""",
                                   (entity["entity_id"], cand))
                        if _c.fetchone() is None:
                            expense_no = cand
                            break
                if expense_no is None:
                    raise ValueError("无法分配费用编号，请手工指定")
        with conn.cursor() as cur:
            values = (payload.get("vendorId"), payload.get("billId"), payload.get("date"),
                      category, str(payload.get("projectName") or "").strip() or None,
                      str(payload.get("notes") or "").strip() or None,
                      str(payload.get("reviewedBy") or "").strip() or None, acct, amount, ccy, tax,
                      functional or 0, fx_rate or 1, fx_date, payload.get("receiptPath"),
                      retention_until(payload.get("date"), payload.get("date")))
            if existing:
                cur.execute("""UPDATE expenses SET vendor_id=%s, bill_id=%s, date=%s,
                    category=%s, project_name=%s, notes=%s, reviewed_by=%s, expense_account_code=%s,
                    amount=%s, currency=%s, tax_amount=%s, amount_functional=%s,
                    fx_rate=%s, fx_rate_date=%s, receipt_path=%s, retention_until=%s
                  WHERE expense_id=%s AND entity_id=%s AND status='draft'""",
                    values + (expense_id, entity["entity_id"]))
                cur.execute("""UPDATE pending_review SET status='resolved',
                                      resolved_by=%s, resolved_at=NOW(3)
                                WHERE entity_id=%s AND ref_table='expenses'
                                  AND ref_id=%s AND status='open'""",
                            (actor, entity["entity_id"], expense_id))
            else:
                cur.execute("""INSERT INTO expenses
                    (entity_id,expense_no,vendor_id,bill_id,date,category,project_name,notes,reviewed_by,
                     expense_account_code,amount,currency,tax_amount,amount_functional,fx_rate,
                     fx_rate_date,receipt_path,status,created_by,retention_until)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s,%s)""",
                    (entity["entity_id"], expense_no) + values[:-1] +
                    (actor, values[-1]))
                expense_id = cur.lastrowid

        pending_ids = []
        if severity:
            primary = next((c for c in checks if c["status"] == "FAIL"), None)
            pending_ids.append(add_pending(conn, {
                "entityId": entity["entity_id"],
                "kind": "fx_missing" if primary and primary["step"] == "fx" else "invoice",
                "refTable": "expenses", "refId": expense_id,
                "reason": (primary or {}).get("reason", "需人工复核"),
                "severity": severity, "payload": {"checks": checks, "agentCheck": chk}}))

        append_audit(conn, {"entity_id": entity["entity_id"], "actor": actor,
                            "action": "expense.update" if existing else "expense.create",
                            "object_type": "expenses", "object_id": str(expense_id),
                            "detail": {"expense_no": expense_no,
                                       "amount": float(amount), "currency": ccy,
                                       "verdict": chk["verdict"]}})
        return {"expenseId": expense_id, "expenseNo": expense_no,
                "status": "draft", "currency": ccy,
                "amount": float(amount), "fxRate": float(fx_rate) if fx_rate else None,
                "amountFunctional": float(functional) if functional is not None else None,
                "checks": checks, "agentCheck": chk, "pendingReviewIds": pending_ids,
                "roundingNotes": rounding_notes,
                "canPost": chk["verdict"] == "PASS" and severity is None,
                "disclaimer": DISCLAIMER}


def post_bill(bill_id, actor="system"):
    """采购发票过账：借 成本/费用（+ 进项税额），贷 应付账款。

    这是「支出」方向的记法——与销售发票的「借 应收 → 贷 收入」正好相反。
    """
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM bills WHERE bill_id=%s", (bill_id,))
            b = cur.fetchone()
            if not b:
                raise ValueError("采购发票不存在")
            if b["status"] != "draft":
                raise ValueError(f"采购发票状态为 {b['status']}，不可过账")
            if (b.get("review_status") or "draft") != "approved":
                raise ValueError("采购发票未经复核批准，不可过账。请先提交复核并由复核人批准。")

            entity = load_entity(conn)

            # 外币单据：建单时可能还没有汇率，被记为阻断项；过账前再试一次。
            # 汇率后来补齐了就该放行，否则用户只能删单重建。
            if (str(b["currency"]).upper() != str(entity["functional_currency"]).upper()
                    and not dec(b["amount_functional"])):
                from .fx import lookup_rate, normalize_policy
                policy = normalize_policy(load_rules()["fx_policy"])
                rates = [dict(r) for r in _rates(conn, b["currency"],
                                                 entity["functional_currency"], str(b["date"]))]
                look = lookup_rate(rates, str(b["date"]), b["currency"],
                                   entity["functional_currency"], policy)
                if look["ok"]:
                    fx_rate = dec(look["rate"])
                    functional = convert(dec(b["gross_original"]), fx_rate)
                    cur.execute("""UPDATE bills
                                      SET fx_rate=%s, fx_rate_date=%s, amount_functional=%s
                                    WHERE bill_id=%s""",
                                (float(fx_rate), look["rateDate"], float(functional), bill_id))
                    cur.execute("""UPDATE pending_review SET status='resolved',
                                       resolved_at=NOW(3), resolution='汇率已补齐，过账时自动解除'
                                    WHERE ref_table='bills' AND ref_id=%s AND status='open'
                                      AND reason LIKE '%%汇率%%'""", (bill_id,))
                    cur.execute("SELECT * FROM bills WHERE bill_id=%s", (bill_id,))
                    b = cur.fetchone()

            cur.execute("""SELECT review_id, reason FROM pending_review
                            WHERE ref_table='bills' AND ref_id=%s AND status='open'
                              AND severity='blocker'""", (bill_id,))
            blockers = cur.fetchall()
            if blockers:
                raise ValueError("存在阻断项，不可过账：" + "；".join(x["reason"] for x in blockers))

            entry_date = b["date"]
            entry_no = next_no(conn, entity["entity_id"], entry_date, "journal")

            net = dec(b["amount_functional"])
            tax = dec(b["tax_amount"] or 0)
            rate = dec(b["fx_rate"] or 1)
            tax_fn = (tax * rate).quantize(dec("0.01")) if rate else tax
            gross = net + tax_fn
            cc = b["currency"]
            ccy_name = entity["functional_currency"]

            cur.execute("""INSERT INTO journal_entries
                (entity_id,entry_no,entry_date,source_type,source_id,description,status,
                 report_ready,total_debit,total_credit,created_by,retention_until)
                VALUES (%s,%s,%s,'bill',%s,%s,'draft',0,%s,%s,%s,%s)""",
                        (entity["entity_id"], entry_no, entry_date, bill_id,
                         f"采购发票 {b['bill_no']} — {b['vendor_name'] or ''}", gross, gross,
                         actor, b["retention_until"]))
            entry_id = cur.lastrowid

            acct = b["expense_account_code"] or "6600"
            # 明细行带科目（一张单多个费用科目）→ 按科目汇总成多条借方
            per_acct = query("""SELECT account_code, SUM(amount) AS amt
                                  FROM bill_lines
                                 WHERE bill_id=%s AND account_code IS NOT NULL AND account_code<>''
                                 GROUP BY account_code ORDER BY account_code""", (bill_id,))
            if per_acct:
                lines = [(str(r["account_code"]), dec(r["amt"])) for r in per_acct]
                _diff = net - sum((a for _, a in lines), dec(0))
                if abs(float(_diff)) >= 0.005:
                    lines.append((acct, _diff))
            else:
                lines = [(acct, net)]
            if tax_fn and tax_fn > 0:
                lines.append(("1160", tax_fn))       # 进项税额（资产）
            line_no = 1
            for code, amt in lines:
                if amt == 0:
                    continue
                cur.execute("""INSERT INTO journal_lines
                    (entry_id,line_no,account_code,description,debit,credit,ccy,amount_original,rate,rate_date)
                    VALUES (%s,%s,%s,%s,%s,0,%s,%s,%s,%s)""",
                            (entry_id, line_no, code,
                             f"{b['bill_no']} {b['vendor_name'] or ''}".strip(), amt, cc,
                             b["amount"] if code == acct else tax,
                             rate, b["fx_rate_date"]))
                line_no += 1

            cur.execute("""INSERT INTO journal_lines
                (entry_id,line_no,account_code,description,debit,credit,ccy,amount_original,rate,rate_date)
                VALUES (%s,%s,%s,%s,0,%s,%s,%s,%s,%s)""",
                        (entry_id, line_no,
                         (str(b.get("payable_account_code") or "").strip()
                          or ("2111" if cc != ccy_name else "2110")),
                         f"应付 {b['vendor_name'] or ''}".strip(), gross, cc,
                         b["gross_original"], rate, b["fx_rate_date"]))

            # 把账单附件复制到凭证：日记账/凭证页也要看得到原件
            cur.execute("""INSERT INTO doc_files
                (entity_id, doc_type, doc_id, file_name, file_type, file_size,
                 sha256_hash, storage_path, uploaded_by)
                SELECT entity_id, 'journal', %s, file_name, file_type, file_size,
                       sha256_hash, storage_path, uploaded_by
                  FROM doc_files
                 WHERE entity_id=%s AND doc_type='bill' AND doc_id=%s""",
                        (entry_id, entity["entity_id"], bill_id))

            cur.execute("""UPDATE journal_entries SET status='posted', posted_by=%s, posted_at=NOW(3)
                            WHERE entry_id=%s""", (actor, entry_id))
            cur.execute("UPDATE bills SET status='posted', updated_at=NOW(3) WHERE bill_id=%s",
                        (bill_id,))

            append_audit(conn, {"entity_id": entity["entity_id"], "actor": actor,
                                "action": "bill.post", "object_type": "bills",
                                "object_id": str(bill_id),
                                "detail": {"entry_id": entry_id, "entry_no": entry_no,
                                           "net": float(net), "tax": float(tax_fn),
                                           "gross": float(gross), "account": acct}})
            return {"billId": bill_id, "entryId": entry_id, "entryNo": entry_no,
                    "status": "posted", "net": float(net), "tax": float(tax_fn),
                    "gross": float(gross), "expenseAccount": acct}


# ---------------------------------------------------------------- 期末重估
def run_revaluation(period, actor="system"):
    rules = load_rules()
    policy = normalize_policy(rules["fx_policy"])
    with transaction() as conn:
        entity = load_entity(conn)
        with conn.cursor() as cur:
            cur.execute("""SELECT entry_id, entry_no, total_debit FROM journal_entries
                            WHERE entity_id=%s AND source_type='fx_reval' AND period=%s
                              AND status IN ('posted','reversed')""", (entity["entity_id"], period))
            existing = cur.fetchall()
            if existing:
                return {"period": period, "alreadyRun": True,
                        "existingEntries": [{"entryId": e["entry_id"], "entryNo": e["entry_no"],
                                             "totalDebit": float(e["total_debit"])} for e in existing],
                        "revalued": [], "entries": [], "pending": [], "skipped": [], "blockers": [],
                        "entriesWritten": [], "pendingReviewIds": [],
                        "totalGainLossFunctional": None, "complete": True,
                        "note": f"期间 {period} 已完成重估（{len(existing)} 张分录）；幂等保护，未重复计提",
                        "disclaimer": DISCLAIMER}

            from .money import period_end_date
            period_end = period_end_date(period)
            with conn.cursor() as cur:
                cur.execute("""SELECT rate_date, from_ccy, to_ccy, rate, source FROM fx_rates
                                WHERE to_ccy=%s AND rate_date<=%s
                                  AND rate_date>=DATE_SUB(%s, INTERVAL 60 DAY)""",
                            (entity["functional_currency"], period_end, period_end))
                rates = [dict(r) for r in cur.fetchall()]

            items = []
            with conn.cursor() as cur:
                cur.execute("""SELECT invoice_id, currency, (gross_original-settled_original) AS bal,
                                      amount_functional AS carry
                                 FROM invoices WHERE entity_id=%s AND status='posted'
                                   AND currency<>%s AND (gross_original-settled_original)<>0""",
                            (entity["entity_id"], entity["functional_currency"]))
                for r in cur.fetchall():
                    items.append({"kind": "trade_receivable", "refId": r["invoice_id"],
                                  "accountCode": "1131", "currency": r["currency"],
                                  "balanceOriginal": float(r["bal"]), "carryingFunctional": float(r["carry"])})

                cur.execute("""SELECT bill_id, currency, (gross_original-settled_original) AS bal,
                                      amount_functional AS carry
                                 FROM bills WHERE entity_id=%s AND status='posted'
                                   AND currency<>%s AND (gross_original-settled_original)<>0""",
                            (entity["entity_id"], entity["functional_currency"]))
                for r in cur.fetchall():
                    items.append({"kind": "trade_payable", "refId": r["bill_id"],
                                  "accountCode": "2111", "currency": r["currency"],
                                  "balanceOriginal": -float(r["bal"]), "carryingFunctional": -float(r["carry"])})

                cur.execute("""SELECT account_id, account_code, currency, current_balance,
                                      current_balance_functional FROM bank_accounts
                                WHERE entity_id=%s AND status='active' AND currency<>%s""",
                            (entity["entity_id"], entity["functional_currency"]))
                for r in cur.fetchall():
                    items.append({"kind": "foreign_bank_account", "refId": r["account_id"],
                                  "accountCode": r["account_code"], "currency": r["currency"],
                                  "balanceOriginal": float(r["current_balance"]),
                                  "carryingFunctional": float(r["current_balance_functional"])})

        result = revalue_items(rules["fx_policy"], period, period_end, rates, items)

        written = []
        for idx, e in enumerate(result["entries"], start=1):
            entry_no = next_no(conn, entity["entity_id"], period_end, "reval")
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO journal_entries
                    (entity_id,entry_no,entry_date,source_type,source_id,description,status,
                     total_debit,total_credit,created_by,retention_until)
                    VALUES (%s,%s,%s,'fx_reval',%s,%s,'draft',%s,%s,%s,%s)""",
                    (entity["entity_id"], entry_no, period_end, e["sourceId"], e["description"],
                     e["totalDebit"], e["totalCredit"], actor,
                     retention_until(period_end, period_end)))
                entry_id = cur.lastrowid
                for i, l in enumerate(e["lines"], start=1):
                    cur.execute("""INSERT INTO journal_lines
                        (entry_id,line_no,account_code,description,debit,credit,ccy,amount_original,rate,rate_date)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (entry_id, i, l["accountCode"], e["description"], l["debit"], l["credit"],
                         l["ccy"], l["amountOriginal"], l["rate"], l["rateDate"]))
                cur.execute("""UPDATE journal_entries SET status='posted', posted_by=%s, posted_at=NOW(3)
                                WHERE entry_id=%s""", (actor, entry_id))

                rec = next((x for x in result["revalued"]
                            if x["kind"] == "foreign_bank_account" and x["refId"] == e["sourceId"]), None)
                if rec:
                    cur.execute("""UPDATE bank_accounts
                        SET current_balance_functional=%s, last_reval_rate=%s, last_reval_date=%s
                        WHERE account_id=%s""",
                        (rec["revaluedFunctional"], rec["rate"], rec["rateDate"], e["sourceId"]))
            written.append({"entryId": entry_id, "entryNo": entry_no,
                            "description": e["description"], "totalDebit": e["totalDebit"]})

        pending_ids = []
        for p in result["pending"]:
            pending_ids.append(add_pending(conn, {
                "entityId": entity["entity_id"], "kind": "fx_missing",
                "refTable": "bank_accounts", "refId": p.get("refId"),
                "reason": p["reason"], "severity": "warning", "payload": p}))

        append_audit(conn, {"entity_id": entity["entity_id"], "actor": actor,
                            "action": "fx.revalue", "object_type": "period", "object_id": period,
                            "detail": {"entries": len(written),
                                       "totalGainLoss": result["totalGainLossFunctional"],
                                       "pending": len(result["pending"]),
                                       "complete": result["complete"]}})

        out = dict(result)
        out.update({"entriesWritten": written, "pendingReviewIds": pending_ids})
        return out
