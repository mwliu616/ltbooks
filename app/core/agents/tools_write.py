# LtBooks — core/agents/tools_write.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""智能体的「执行级」工具：会计与出纳可按岗位直接操作财务系统。

与 tools_deterministic / toolbox（只读）分开放，是因为这一层真的会写业务表，
必须一眼能看出来。

边界（2026-11 需求变更后）
----------------------------
- 会计、出纳可以**直接执行**建单、记账、冲销、收付款核销、银行匹配、锁账。
- 每一笔执行都用 `agent:<岗位>` 作为 actor 写审计链，和人的操作分得清。
- 运行时仍有三道闸：
    1. 只有当次会话开着「可直接执行」才把执行工具交给模型（可随时切回只提案）
    2. 单轮最多 MAX_WRITES 笔写操作，防止模型跑飞
    3. 金额/期间/科目由既有 service 函数校验，工具不做任何猜测
- 危险动作（记账、冲销、锁账）执行后会在界面用红色结果卡列出凭证号，
  人一眼能看到，需要时可以冲销回来。

依赖注入：`create_journal` / `create_payment` / `confirm_bank_match` 的实现
在 api.py 里（那里有完整的期初、汇率、银行账户校验），由 api.py 在启动时
调用 `bind()` 注册进来，避免 core 反向依赖 api。
"""
from __future__ import annotations

from ..db import query_one

# api 层注入的实现
_BOUND: dict[str, callable] = {}


def bind(name: str, fn) -> None:
    _BOUND[name] = fn


class WriteError(Exception):
    pass


def _actor(args: dict) -> str:
    """执行人：agent:<岗位>（提问的人放在括号里，审计能追到人）。"""
    by = str(args.get("_actor") or "agent")
    who = str(args.get("_requested_by") or "").strip()
    return f"agent:{by}" + (f"({who})" if who else "")


def _need(args: dict, *keys) -> None:
    for k in keys:
        if args.get(k) in (None, "", []):
            raise WriteError(f"缺少必填参数：{k}")


# ---------------------------------------------------------------- 往来单位 / 报价 / 贷记单 / CSV
def _update_party(args: dict) -> dict:
    fn = _BOUND.get("update_party")
    if fn is None:
        raise WriteError("往来单位通道未就绪")
    return fn(args)


def _manage_bank_rule(args: dict) -> dict:
    fn = _BOUND.get("manage_bank_rule")
    if fn is None:
        raise WriteError("银行规则通道未就绪")
    return fn(args)


def _set_fx_rate(args: dict) -> dict:
    fn = _BOUND.get("set_fx_rate")
    if fn is None:
        raise WriteError("汇率通道未就绪")
    return fn(args)


def _run_period_close(args: dict) -> dict:
    fn = _BOUND.get("run_period_close")
    if fn is None:
        raise WriteError("月结通道未就绪")
    return fn(args)


def _save_party(kind: str, args: dict) -> dict:
    fn = _BOUND.get(f"save_{kind}")
    if fn is None:
        raise WriteError("往来单位通道未就绪")
    return fn(args)


def _create_simple_doc(kind: str, args: dict) -> dict:
    fn = _BOUND.get(f"create_{kind}")
    if fn is None:
        raise WriteError(f"{kind} 通道未就绪")
    return fn(args)


def _export_csv(args: dict) -> dict:
    fn = _BOUND.get("export_csv")
    if fn is None:
        raise WriteError("CSV 导出通道未就绪")
    return fn(args)


# ---------------------------------------------------------------- 建单
def w_create_invoice(args):
    from ..service import create_invoice
    _need(args, "partyName")
    r = create_invoice({
        "supplierName": args["partyName"],
        "customerId": args.get("partyId"),
        "invoiceDate": args.get("date"),
        "dueDate": args.get("dueDate") or None,
        "currency": args.get("currency") or "HKD",
        "amountOriginal": float(args.get("amountOriginal") or 0),
        "taxOriginal": float(args.get("taxOriginal") or 0),
        "lines": args.get("lines") or [],
        "performanceObligationStatus": "fulfilled",
        "recognitionPattern": "point_in_time",
        "actor": _actor(args),
    }, _actor(args))
    return {"docType": "invoice", "docId": r.get("invoiceId"), "docNo": r.get("invoiceNo"),
            "status": "draft", "href": f"?p=invoice-view&id={r.get('invoiceId')}",
            "next": "草稿已建；需要入账请再调 post_document"}


def w_create_bill(args):
    from ..service import create_bill
    _need(args, "partyName")
    r = create_bill({
        "vendorName": args["partyName"],
        "vendorId": args.get("partyId"),
        "vendorInvoiceNo": args.get("docNo") or None,
        "date": args.get("date"),
        "dueDate": args.get("dueDate") or None,
        "currency": args.get("currency") or "HKD",
        "amount": float(args.get("amountOriginal") or 0),
        "taxAmount": float(args.get("taxOriginal") or 0),
        "expenseAccountCode": args.get("expenseAccountCode") or "6200",
        "lines": args.get("lines") or [],
        "actor": _actor(args),
    }, _actor(args))
    return {"docType": "bill", "docId": r.get("billId"), "docNo": r.get("billNo"),
            "status": "draft", "href": f"?p=bill-view&id={r.get('billId')}",
            "next": "草稿已建；需要入账请再调 post_document"}


def w_create_expense(args):
    from ..service import create_expense
    _need(args, "partyName")
    r = create_expense({
        "category": args["partyName"],
        "date": args.get("date"),
        "currency": args.get("currency") or "HKD",
        "amount": float(args.get("amountOriginal") or 0),
        "taxAmount": float(args.get("taxOriginal") or 0),
        "actor": _actor(args),
    }, _actor(args))
    return {"docType": "expense", "docId": r.get("expenseId"), "docNo": r.get("expenseNo"),
            "status": "draft", "href": "?p=expenses"}


def w_create_journal(args):
    _need(args, "entryDate", "lines")
    fn = _BOUND.get("create_journal")
    if fn is None:
        raise WriteError("分录通道未就绪")
    return fn({**args, "actor": _actor(args)})


# ---------------------------------------------------------------- 记账 / 冲销
def w_post_document(args):
    """记账。草稿先补齐「提交复核 → 批准」再过账（与界面的一键记账同一条路径），
    这样做完能立刻拿到凭证号；是否允许一人走完由 role 决定（非 admin 会被四眼拦住）。"""
    from ..service import post_bill, post_invoice
    _need(args, "kind", "docId")
    kind = str(args["kind"]).lower()
    doc_id = int(args["docId"])
    actor = _actor(args)
    role = str(args.get("_role") or "admin")
    table = ("invoices", "invoice", "invoice_no") if kind in ("invoice", "invoices") \
        else (("bills", "bill", "bill_no") if kind in ("bill", "bills") else (None, None, None))
    if table[0] is None:
        raise WriteError("kind 只能是 invoice / bill")
    tbl, key, no_col = table
    row = query_one(f"SELECT status, {no_col} AS no FROM {tbl} WHERE {key}_id=%s", (doc_id,))
    if not row:
        raise WriteError(f"单据 {doc_id} 不存在")
    if row["status"] != "draft":
        return {"ok": True, "skipped": f"状态为 {row['status']}，无需记账",
                "docNo": row["no"]}
    one_click = _BOUND.get("post_one_click")
    if one_click is not None:
        r = one_click("invoice" if kind.startswith("invoice") else "bill",
                      doc_id, actor, role)
        if not r.get("ok"):
            raise WriteError(str(r.get("error") or "记账失败"))
        return {"docType": "invoice" if kind.startswith("invoice") else "bill",
                "docId": doc_id, "docNo": row["no"],
                "entryNo": r.get("entryNo"), "entryId": r.get("entryId"),
                "steps": r.get("steps"), "status": "posted"}
    r = post_invoice(doc_id, actor) if kind.startswith("invoice") else post_bill(doc_id, actor)
    return {"docType": "invoice" if kind.startswith("invoice") else "bill",
            "docId": doc_id, "docNo": row["no"],
            "entryNo": r.get("entryNo"), "entryId": r.get("entryId"), "status": "posted"}


def w_reverse_entry(args):
    from ..service import reverse_entry
    _need(args, "entryId")
    r = reverse_entry(int(args["entryId"]), _actor(args), str(args.get("reason") or "智能体冲销"))
    return {"entryId": args["entryId"], "reversalEntryNo": r.get("entryNo"),
            "status": "reversed"}


# ---------------------------------------------------------------- 出纳
def w_create_payment(args):
    _need(args, "direction", "amount", "bankAccountId", "allocations")
    fn = _BOUND.get("create_payment")
    if fn is None:
        raise WriteError("收付款通道未就绪")
    payload = {**args, "actor": _actor(args)}
    r = fn(payload)
    return {"direction": r.get("direction"), "paymentNo": r.get("paymentNo"),
            "amount": r.get("amount"), "currency": r.get("currency"),
            "allocations": r.get("allocations"), "fxDifference": r.get("fxDifference"),
            "href": "?p=receipts" if r.get("direction") == "received" else "?p=payments&direction=made"}


def w_confirm_bank_match(args):
    _need(args, "lineId", "docId")
    fn = _BOUND.get("confirm_bank_match")
    if fn is None:
        raise WriteError("银行匹配通道未就绪")
    r = fn({**args, "actor": _actor(args)})
    return {"lineId": r.get("lineId"), "invoiceId": r.get("invoiceId"),
            "crossCurrency": r.get("crossCurrency"), "difference": r.get("difference"),
            "status": "matched"}


# ---------------------------------------------------------------- 期间
def w_lock_period(args):
    _need(args, "period")
    period = str(args["period"])
    status = str(args.get("status") or "locked")
    if status not in ("open", "locked", "closed"):
        raise WriteError("status 只能是 open / locked / closed")
    from ..db import transaction
    from ..service import append_audit
    actor = _actor(args)
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO period_locks (entity_id, period, status, locked_by, locked_at, note)
                           VALUES (1,%s,%s,%s,NOW(3),%s)
                           ON DUPLICATE KEY UPDATE status=VALUES(status),
                                                   locked_by=VALUES(locked_by),
                                                   locked_at=NOW(3), note=VALUES(note)""",
                        (period, status, actor, str(args.get("note") or "智能体执行")))
        append_audit(conn, {"entity_id": 1, "actor": actor, "actor_role": "agent",
                            "action": "period_lock.set", "object_type": "period_locks",
                            "object_id": period,
                            "detail": {"status": status, "via": "agent_tool"}})
    return {"period": period, "status": status}


# ---------------------------------------------------------------- 工具定义
WRITE_TOOLS = {
    "create_customer": {
        "desc": "新建客户档案。用户说「新增一个客户 X」时用。",
        "schema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "客户名称"},
            "email": {"type": "string"},
            "currency": {"type": "string", "description": "默认币种，默认 HKD"},
            "paymentTermsDays": {"type": "integer", "description": "账期天数，默认 30"},
        }, "required": ["name"]},
        "fn": lambda a: _save_party("customer", a),
        "danger": "create",
    },
    "create_vendor": {
        "desc": "新建供应商档案。用户说「新增一个供应商 X」时用。",
        "schema": {"type": "object", "properties": {
            "name": {"type": "string", "description": "供应商名称"},
            "email": {"type": "string"},
            "currency": {"type": "string"},
            "paymentTermsDays": {"type": "integer"},
        }, "required": ["name"]},
        "fn": lambda a: _save_party("vendor", a),
        "danger": "create",
    },
    "create_quote": {
        "desc": "开一张报价单（不进总账）。用户说「给 X 报个价」时用。",
        "schema": {"type": "object", "properties": {
            "partyName": {"type": "string", "description": "客户名称"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "currency": {"type": "string"},
            "lines": {"type": "array", "items": {"type": "object"},
                      "description": "明细：[{description, quantity, unitPrice}]"},
        }, "required": ["partyName", "lines"]},
        "fn": lambda a: _create_simple_doc("quote", a),
        "danger": "create",
    },
    "create_credit_note": {
        "desc": "开一张贷记单（红字单）。用户说「退货 / 折让 / 冲一张发票」时用。",
        "schema": {"type": "object", "properties": {
            "creditType": {"type": "string", "enum": ["customer", "vendor"]},
            "partyName": {"type": "string"},
            "date": {"type": "string"},
            "currency": {"type": "string"},
            "amountOriginal": {"type": "number"},
            "reason": {"type": "string"},
        }, "required": ["partyName", "amountOriginal"]},
        "fn": lambda a: _create_simple_doc("credit", a),
        "danger": "create",
    },
    "export_csv": {
        "desc": "导出明细 CSV（发票/账单/凭证/银行流水），带 SHA-256，返回下载链接。",
        "schema": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["invoices", "bills", "journal", "bank_lines"]},
            "purpose": {"type": "string", "description": "导出目的（审计要求）"},
            "recipient": {"type": "string", "description": "接收方"},
        }, "required": ["kind"]},
        "fn": lambda a: _export_csv(a),
        "danger": "create",
    },
    "update_party": {
        "desc": "修改客户/供应商资料，或停用/启用。用户说「把客户 X 的电话改成…」「停用供应商 Y」时用。",
        "schema": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["customer", "vendor"]},
            "name": {"type": "string", "description": "要改的客户/供应商名称（按名称匹配）"},
            "newName": {"type": "string", "description": "改成的新名称，可不填"},
            "email": {"type": "string"},
            "currency": {"type": "string"},
            "paymentTermsDays": {"type": "integer"},
            "status": {"type": "string", "enum": ["active", "inactive"],
                       "description": "停用填 inactive"},
        }, "required": ["kind", "name"]},
        "fn": lambda a: _update_party(a),
        "danger": "create",
    },
    "create_order": {
        "desc": "开销售订单或采购订单（只登记，不进总账）。用户说「给 X 下个订单」时用。",
        "schema": {"type": "object", "properties": {
            "direction": {"type": "string", "enum": ["sales", "purchase"]},
            "partyName": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "currency": {"type": "string"},
            "lines": {"type": "array", "items": {"type": "object"},
                      "description": "[{description, quantity, unitPrice}]"},
        }, "required": ["direction", "partyName", "lines"]},
        "fn": lambda a: _create_simple_doc("order", a),
        "danger": "create",
    },
    "manage_bank_rule": {
        "desc": "银行自动匹配规则：列出、新建、删除。用户说「加一条规则：摘要含 X 就记到 Y」时用。",
        "schema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "create", "delete"]},
            "ruleId": {"type": "integer"},
            "name": {"type": "string"},
            "matchText": {"type": "string", "description": "摘要里出现的文字"},
            "counterAccount": {"type": "string", "description": "对方科目编码"},
            "matchField": {"type": "string", "enum": ["any", "description", "reference"]},
        }, "required": ["action"]},
        "fn": lambda a: _manage_bank_rule(a),
        "danger": "create",
    },
    "set_fx_rate": {
        "desc": "手工补录汇率（审计常用）。用户说「美元今天 7.8」时用。",
        "schema": {"type": "object", "properties": {
            "fromCcy": {"type": "string", "description": "来源币种，如 USD"},
            "toCcy": {"type": "string", "description": "目标币种，默认 HKD"},
            "rate": {"type": "number"},
            "rateDate": {"type": "string", "description": "YYYY-MM-DD"},
        }, "required": ["fromCcy", "rate", "rateDate"]},
        "fn": lambda a: _set_fx_rate(a),
        "danger": "create",
    },
    "run_period_close": {
        "desc": ("执行月结步骤。用户明确说「做月结」「把这个月结掉」时才用；只看六步状态必须用只读工具 period_close_status。"
                 "action=run 跑一步（step=recon 银行对账 / fx 汇率 / "
                 "revalue 重估 / ar_ap 应收应付核对 / accrual 计提 / lock 锁账；all 只跑可自动的三步）。"),
        "schema": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["run"]},
            "period": {"type": "string", "description": "YYYY-MM"},
            "step": {"type": "string", "enum": ["all", "recon", "fx", "revalue", "ar_ap", "accrual", "lock"]},
        }, "required": ["action"]},
        "fn": lambda a: _run_period_close(a),
        "danger": "execute",
    },
    "create_invoice": {
        "desc": "建一张销售发票（草稿）。用户说「开一张发票给 X」时用。",
        "schema": {
            "type": "object",
            "properties": {
                "partyName": {"type": "string", "description": "客户名称"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "dueDate": {"type": "string"},
                "currency": {"type": "string"},
                "amountOriginal": {"type": "number", "description": "不含税金额"},
                "taxOriginal": {"type": "number"},
                "lines": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["partyName", "date", "amountOriginal"],
        },
        "fn": w_create_invoice,
        "danger": "create",
    },
    "create_bill": {
        "desc": "建一张采购发票/账单（草稿）。用户说「记一张采购单」时用。",
        "schema": {
            "type": "object",
            "properties": {
                "partyName": {"type": "string", "description": "供应商名称"},
                "date": {"type": "string"},
                "dueDate": {"type": "string"},
                "currency": {"type": "string"},
                "amountOriginal": {"type": "number"},
                "taxOriginal": {"type": "number"},
                "docNo": {"type": "string", "description": "对方单号"},
                "expenseAccountCode": {"type": "string"},
                "lines": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["partyName", "date", "amountOriginal"],
        },
        "fn": w_create_bill,
        "danger": "create",
    },
    "create_expense": {
        "desc": "登记一笔费用（草稿）。",
        "schema": {
            "type": "object",
            "properties": {
                "partyName": {"type": "string", "description": "费用类别或供应商"},
                "date": {"type": "string"},
                "currency": {"type": "string"},
                "amountOriginal": {"type": "number"},
                "taxOriginal": {"type": "number"},
            },
            "required": ["partyName", "date", "amountOriginal"],
        },
        "fn": w_create_expense,
        "danger": "create",
    },
    "create_journal": {
        "desc": "手工记账分录（草稿）。借贷必须平衡。",
        "schema": {
            "type": "object",
            "properties": {
                "entryDate": {"type": "string"},
                "description": {"type": "string"},
                "currency": {"type": "string"},
                "lines": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"accountCode": {"type": "string"},
                                   "debit": {"type": "number"},
                                   "credit": {"type": "number"},
                                   "description": {"type": "string"}},
                    "required": ["accountCode"]}},
            },
            "required": ["entryDate", "lines"],
        },
        "fn": w_create_journal,
        "danger": "create",
    },
    "post_document": {
        "desc": "把一张草稿发票/账单入账（生成凭证）。这是记账动作。",
        "schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["invoice", "bill"]},
                "docId": {"type": "integer"},
            },
            "required": ["kind", "docId"],
        },
        "fn": w_post_document,
        "danger": "post",
    },
    "reverse_entry": {
        "desc": "冲销一张已入账的凭证（生成反向分录，原凭证不动）。必须写原因。",
        "schema": {
            "type": "object",
            "properties": {
                "entryId": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["entryId", "reason"],
        },
        "fn": w_reverse_entry,
        "danger": "reverse",
    },
    "create_payment": {
        "desc": "登记收款/付款并核销单据（生成收付款凭证）。",
        "schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["received", "made"]},
                "date": {"type": "string"},
                "amount": {"type": "number"},
                "currency": {"type": "string"},
                "bankAccountId": {"type": "integer"},
                "allocations": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"docId": {"type": "integer"},
                                   "amount": {"type": "number"}},
                    "required": ["docId", "amount"]}},
            },
            "required": ["direction", "date", "amount", "bankAccountId", "allocations"],
        },
        "fn": w_create_payment,
        "danger": "cash",
    },
    "confirm_bank_match": {
        "desc": "确认一条银行流水与某张发票的匹配（跨币种必须写理由）。",
        "schema": {
            "type": "object",
            "properties": {
                "lineId": {"type": "integer"},
                "docId": {"type": "integer"},
                "rule": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["lineId", "docId"],
        },
        "fn": w_confirm_bank_match,
        "danger": "cash",
    },
    "lock_period": {
        "desc": "锁定/解锁会计期间。锁定后该期间不能再写分录，影响面大。",
        "schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "YYYY-MM"},
                "status": {"type": "string", "enum": ["open", "locked", "closed"]},
                "note": {"type": "string"},
            },
            "required": ["period"],
        },
        "fn": w_lock_period,
        "danger": "lock",
    },
}

MAX_WRITES_PER_TURN = 8


def names() -> list:
    return list(WRITE_TOOLS.keys())


def openai_tools(names_list) -> list:
    out = []
    for n in names_list:
        t = WRITE_TOOLS.get(n)
        if not t:
            continue
        out.append({"type": "function",
                    "function": {"name": n, "description": t["desc"],
                                 "parameters": t["schema"]}})
    return out


def call(name: str, args: dict) -> dict:
    t = WRITE_TOOLS.get(name)
    if t is None:
        raise WriteError(f"不是可执行工具：{name}")
    return t["fn"](args or {})
