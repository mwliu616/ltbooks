# LtBooks — core/agents/toolbox.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""工具注册表。

每个工具：名称、说明、JSON Schema、权限级、handler。
权限级：
  read    只读，全部智能体可用
  suggest 生成建议/草稿（仍不写账）
  execute 执行记账类写操作 —— **本注册表不注册任何 execute 工具**，这是硬约束。
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

from ..db import query, query_one


def _jsonable(v):
    """把 date / Decimal 之类转成可 JSON 化的值，工具结果要回给模型。"""
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v
from .tools_deterministic import journal_check, reconciliation_snapshot, variance_bridge

# api 层注入的只读实现（需要完整校验逻辑，不好搬进 core）
_BOUND: dict = {}


def bind(name: str, fn) -> None:
    _BOUND[name] = fn


READ_ONLY_TABLES = {
    "accounts", "invoices", "invoice_lines", "bills", "bill_lines", "expenses",
    "journal_entries", "journal_lines", "customers", "vendors", "bank_accounts",
    "bank_lines", "payments_received", "payments_made", "settlements",
    "fx_rates", "pending_review", "audit_log", "entities", "revenue_contracts",
    "contract_payments", "period_locks", "tax_rates", "compliance_items",
}
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|replace|"
    r"information_schema|mysql\.|performance_schema|sys\.|load_file|outfile|"
    r"sleep|benchmark)\b", re.I)


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- handlers
def _sql_readonly(args):
    sql = str(args.get("sql") or "").strip().rstrip(";")
    if not re.match(r"^(select|with)\b", sql, re.I):
        raise ToolError("只允许 SELECT 查询")
    if _FORBIDDEN.search(sql) or "--" in sql or "/*" in sql:
        raise ToolError("查询包含不允许的关键字或注释")
    tables = set(t.lower() for t in re.findall(r"(?:from|join)\s+([a-zA-Z_][\w]*)", sql, re.I))
    bad = tables - READ_ONLY_TABLES
    if bad:
        raise ToolError(f"表不在白名单：{', '.join(sorted(bad))}")
    if not re.search(r"\blimit\b", sql, re.I):
        sql += " LIMIT 200"
    rows = query(sql)
    out = _jsonable([dict(r) for r in rows])[:200]
    return {"rows": out, "count": len(rows)}


def _account_search(args):
    kw = str(args.get("keyword") or "").strip()
    like = f"%{kw}%"
    rows = query("""SELECT account_code, account_name, name_en, category, normal_balance
                      FROM accounts
                     WHERE entity_id=%s AND is_active=1
                       AND (account_code LIKE %s OR account_name LIKE %s OR name_en LIKE %s)
                     ORDER BY account_code LIMIT 30""", (1, like, like, like))
    return {"accounts": _jsonable([dict(r) for r in rows])}


def _account_history(args):
    """同对方在这个系统里历史用的是哪个科目 —— 分类官的主要依据。"""
    party = str(args.get("party") or "").strip()
    if not party:
        return {"history": [], "note": "未提供对方名称"}
    like = f"%{party}%"
    rows = query("""SELECT l.account_code, a.account_name, COUNT(*) AS n
                      FROM journal_lines l
                      JOIN journal_entries e ON e.entry_id=l.entry_id
                      JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=1
                      LEFT JOIN invoices i ON i.invoice_id=e.source_id AND e.source_type='invoice'
                      LEFT JOIN bills b ON b.bill_id=e.source_id AND e.source_type='bill'
                     WHERE e.entity_id=1 AND e.status='posted'
                       AND (i.supplier_name LIKE %s OR b.vendor_name LIKE %s)
                       AND l.debit > 0
                     GROUP BY l.account_code, a.account_name
                     ORDER BY n DESC LIMIT 5""", (like, like))
    return {"party": party, "history": _jsonable([dict(r) for r in rows])}


def _party_match(args):
    name = str(args.get("name") or "").strip()
    kind = str(args.get("kind") or "customer")
    table, col = ("customers", "customer_name") if kind == "customer" else ("vendors", "vendor_name")
    like = f"%{name}%"
    rows = query(f"""SELECT {col} AS name, 1 AS entity FROM {table}
                      WHERE entity_id=%s AND {col} LIKE %s LIMIT 10""", (1, like))
    exact = [r for r in rows if str(r["name"]).strip() == name]
    return {"kind": kind, "query": name,
            "exact": [dict(r) for r in exact],
            "similar": [dict(r) for r in rows if r not in exact]}


def _export_pdf(args):
    """报表 PDF：由 api 层渲染并给出下载地址（工具本身不碰数据）。"""
    fn = _BOUND.get("export_pdf")
    if fn is None:
        raise ToolError("PDF 导出通道未就绪")
    return fn(str(args.get("kind") or "pnl"),
              args.get("from") or "", args.get("to") or "",
              args.get("lang") or "")


def _financial_analysis(args):
    """完整财务分析与 PDF/DOCX：由 api 层取真实报表、导出并审计。"""
    fn = _BOUND.get("financial_analysis")
    if fn is None:
        raise ToolError("财务分析通道未就绪")
    return fn(args)


def _workbench_todo(args):
    """读取真实待办队列；section 只筛选展示，不改变任何业务数据。"""
    fn = _BOUND.get("workbench_todo")
    if fn is None:
        raise ToolError("待办队列通道未就绪")
    return fn(args)


def _period_close_status(args):
    """只读月结六步状态；执行月结仍须使用单独的写工具。"""
    fn = _BOUND.get("period_close_status")
    if fn is None:
        raise ToolError("月结状态通道未就绪")
    return fn(args)


def _document_detail(args):
    """按单号读取单据及明细，不返回人工页面链接。"""
    fn = _BOUND.get("document_detail")
    if fn is None:
        raise ToolError("单据详情通道未就绪")
    return fn(args)


def _reconciliation_detail(args):
    """读取指定对账批次的真实流水与匹配结果，不以当前队列代替历史。"""
    fn = _BOUND.get("reconciliation_detail")
    if fn is None:
        raise ToolError("对账批次详情通道未就绪")
    return fn(args)


def _export_document_pdf(args):
    """单张单据 PDF：由 api 层渲染并给下载地址。"""
    fn = _BOUND.get("export_document_pdf")
    if fn is None:
        raise ToolError("单据 PDF 导出通道未就绪")
    return fn(str(args.get("kind") or "invoice"),
              str(args.get("docNo") or ""),
              str(args.get("lang") or ""))


def _bank_match_suggestions(args):
    """未匹配流水 + 候选单据（P1–P3 打分）。确认匹配要用 confirm_bank_match。"""
    fn = _BOUND.get("bank_match_suggestions")
    if fn is None:
        raise ToolError("匹配建议通道未就绪")
    acct = int(args.get("accountId") or 0)
    r = fn(acct)
    out = []
    for x in (r.get("matches") or [])[:50]:
        c = x.get("candidate") or {}
        out.append({"lineId": x["lineId"], "suggestDoc": c.get("docNo"),
                    "rule": c.get("rule"), "confidence": c.get("confidence"),
                    "amount": c.get("compareAmount"), "difference": c.get("difference"),
                    "autoMatch": True})
    for x in (r.get("pending") or [])[:50]:
        c = x.get("candidate") or {}
        out.append({"lineId": x["lineId"], "suggestDoc": c.get("docNo"),
                    "rule": c.get("rule"), "confidence": c.get("confidence"),
                    "amount": c.get("compareAmount"), "difference": c.get("difference"),
                    "autoMatch": False,
                    "note": "置信不足，确认前请核对金额与日期"})
    return {"suggestions": out, "autoCount": len(r.get("matches") or []),
            "needsHuman": len(r.get("pending") or []),
            "unmatched": len(r.get("unmatched") or []),
            "note": "confirm_bank_match 需要 lineId + docId；这里只给 lineId 与单号，"
                    "docId 请用 open_docs 或 sql_readonly 查"}


def _bank_accounts(args):
    """银行账户清单：收付款要用 account_id，模型不能凭空编。"""
    from .. import reports

    # 余额取总账，与 /reports/bank-balances、银行页面保持一致
    gl = {a["account_id"]: a["current_balance"]
          for g in reports.bank_balances(1)["groups"] for a in g["accounts"]}
    rows = query("""SELECT account_id, name, currency, account_number_masked, status
                      FROM bank_accounts
                     WHERE entity_id=1 AND status='active'
                     ORDER BY (currency='HKD') DESC, account_id""")
    out = [{"accountId": int(r["account_id"]), "name": r["name"],
            "currency": r["currency"], "account": r["account_number_masked"],
            "balance": float(gl.get(int(r["account_id"]), 0))} for r in rows]
    return {"accounts": out, "count": len(out),
            "note": "create_payment 的 bankAccountId 必须取这里的 accountId"}


def _propose_document(args):
    """把识别/听从的结果变成一张「待确认」提案。

    注意边界：这里只写 ai_actions（提案），不写任何业务表。
    真正入库发生在人点了确认之后，执行者是登录用户。工具执行级仍然是 0 个。
    """
    from . import actions

    kind = str(args.get("kind") or "bill").strip()
    type_map = {"bill": "create_bill", "invoice": "create_invoice",
                "expense": "create_expense"}
    action_type = type_map.get(kind, kind)
    payload = {
        "partyName": str(args.get("partyName") or "").strip(),
        "date": str(args.get("date") or "")[:10] or None,
        "dueDate": str(args.get("dueDate") or "")[:10] or None,
        "currency": str(args.get("currency") or "HKD").upper(),
        "amountOriginal": args.get("amountOriginal") or 0,
        "taxOriginal": args.get("taxOriginal") or 0,
        "docNo": str(args.get("docNo") or "").strip() or None,
        "lines": args.get("lines") or [],
        "confidence": args.get("confidence"),
        "warnings": args.get("warnings") or [],
        "sourceNote": args.get("sourceNote"),
        "actor": args.get("actor") or "agent",
    }
    out = actions.propose(1, action_type, payload,
                          actor=payload.get("actor") or "agent",
                          source_file=args.get("sourceFile"))
    out["hint"] = ("已生成待确认卡片。请把金额、往来单位、日期念给用户，"
                   "并说明他点「确认导入」之后才会建单。不要自己说已经入账。")
    return out


def _hkfrs15_assess(args):
    """读规则文件，只做「覆盖/未覆盖」判定，不做准则推断。"""
    from pathlib import Path
    f = Path(__file__).with_name("rules") / "hkfrs15.yml"
    text = f.read_text(encoding="utf-8") if f.is_file() else ""
    case_id = str(args.get("caseId") or "").strip()
    covered = bool(case_id) and case_id in text
    return {
        "ruleFile": str(f),
        "caseId": case_id or None,
        "covered": covered,
        "result": ("规则已覆盖，按规则文件条款判定" if covered
                   else "规则未覆盖，需人工判断"),
        "authorization": "NEVER_AUTHORIZES_POSTING",
    }


def _tax_compute(args):
    """香港利得税两级制。undetermined 时禁止算税。"""
    status = str(args.get("twoTierStatus") or "undetermined")
    profit = args.get("assessableProfit")
    if status == "undetermined":
        return {"tax": None, "blocked": True,
                "reason": "two_tier_status 未确定，禁止计算税额"}
    try:
        p = float(profit or 0)
    except (TypeError, ValueError):
        return {"tax": None, "blocked": True, "reason": "应评税利润非法"}
    if p <= 0:
        return {"tax": 0.0, "blocked": False, "rate": 0, "note": "无应评税利润"}
    if status == "not_nominated":
        return {"tax": round(p * 0.165, 2), "blocked": False,
                "rate": 0.165, "note": "未提名两级制，全额 16.5%"}
    first = min(p, 2_000_000)
    rest = max(0.0, p - 2_000_000)
    return {"tax": round(first * 0.0825 + rest * 0.165, 2), "blocked": False,
            "rate": "8.25% / 16.5%",
            "breakdown": {"first2m": round(first * 0.0825, 2),
                          "remainder": round(rest * 0.165, 2)}}


def _analyze_document(args):
    """判断采购/销售，并按历史与该单位习惯推荐科目。只给建议，不写账。"""
    from .. import doc_analyze

    text = str(args.get("text") or "").strip()
    if not text:
        return {"error": "text_empty", "message": "请把单据文本或抬头、金额行贴给我"}
    return doc_analyze.analyze(
        text, entity_id=1, party=str(args.get("party") or ""),
        lines=args.get("lines") or None,
        extracted=args.get("extracted") or None)


def _open_docs(args):
    """未结清单据。核销要用 docId，所以这里必须带 id 与往来单位。"""
    kind = str(args.get("kind") or "invoice")
    if kind == "bill":
        table, id_col, no_col, party_col, date_col = "bills", "bill_id", "bill_no", "vendor_name", "date"
    else:
        table, id_col, no_col, party_col, date_col = "invoices", "invoice_id", "invoice_no", "supplier_name", "invoice_date"
    rows = query(f"""SELECT {id_col} AS id, {no_col} AS doc_no, {party_col} AS party,
                            {date_col} AS doc_date, currency,
                            (gross_original - settled_original) AS outstanding
                       FROM {table}
                      WHERE entity_id=%s AND status='posted'
                        AND (gross_original - settled_original) > 0
                      ORDER BY {date_col} LIMIT 50""", (1,))
    return {"kind": kind, "docs": [
        {"docId": int(r["id"]), "docNo": r["doc_no"], "party": r["party"],
         "docDate": str(r["doc_date"]), "currency": r["currency"],
         "outstanding": float(r["outstanding"])} for r in rows],
        "note": "create_payment 的 allocations[].docId 取这里的 docId，金额不得超过 outstanding"}


def _bank_lines(args):
    rows = query("""SELECT line_id, txn_date, amount_original, currency, counterparty_name, match_status
                      FROM bank_lines WHERE entity_id=%s AND match_status='unmatched'
                     ORDER BY txn_date DESC LIMIT 50""", (1,))
    return {"lines": _jsonable([dict(r) for r in rows])}


# ---------------------------------------------------------------- 确定性统计
# 口径与 core/reports.py 一致：已过账 + 已冲销计入，期间按 entry_date。
_POSTED = "e.status IN ('posted','reversed')"


def _period_range(period=None):
    """period 支持 'YYYY-MM' / 'YYYY' / None(全部)；返回 (起, 止) 或 (None, None)。"""
    p = str(period or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", p):
        y, m = int(p[:4]), int(p[5:7])
        start = f"{y:04d}-{m:02d}-01"
        end = (f"{y+1:04d}-01-01" if m == 12 else f"{y:04d}-{m+1:02d}-01")
        return start, end
    if re.fullmatch(r"\d{4}", p):
        return f"{p}-01-01", f"{int(p)+1:04d}-01-01"
    return None, None


def _cat_total(category, period=None, entity_id=1):
    """按科目类别汇总：一律返回「借方净额」。

    收入类正常在贷方，所以它的值会是负数；成本费用类在借方，是正数。
    与报表（HKAS 1）同一口径 —— 之前这里用 credit-debit，成本费用变负数，
    智能体算毛利时变成「收入 + 成本」，净利被高估一倍。
    """
    start, end = _period_range(period)
    cond, args = "", [entity_id, category]
    if start:
        cond = " AND e.entry_date >= %s AND e.entry_date < %s"
        args += [start, end]
    row = query_one(f"""SELECT COALESCE(SUM(l.debit - l.credit), 0) AS net,
                               COUNT(DISTINCT e.entry_id) AS entries
                          FROM journal_lines l
                          JOIN journal_entries e ON e.entry_id = l.entry_id
                          JOIN accounts a ON a.account_code = l.account_code AND a.entity_id = 1
                         WHERE e.entity_id = %s AND {_POSTED} AND a.category = %s{cond}""",
                    tuple(args))
    return {"net": float(row["net"]), "entries": int(row["entries"])}


def _finance_summary(args):
    """一句话问财务：收入 / 成本 / 费用 / 净利。

    数字直接取损益表（HKAS 1）—— 与「报表中心」「利得税页」同一口径。
    智能体只负责念出这几个数，不做任何加减：口径只存在于报表代码里，
    这样它报的净利永远不会和页面上的对不上。
    """
    from datetime import date, timedelta
    from .. import reports

    period = args.get("period")
    start, end = _period_range(period)
    if start:
        # profit_and_loss 用「> start 且 <= end」，传端点要各让一天，避免漏首日 / 跨月
        d0 = date.fromisoformat(start) - timedelta(days=1)
        d1 = date.fromisoformat(end) - timedelta(days=1)
        pl = reports.profit_and_loss(1, d0.isoformat(), d1.isoformat())
        entryCount = int(query_one(
            f"""SELECT COUNT(DISTINCT e.entry_id) AS n FROM journal_entries e
                 WHERE e.entity_id=%s AND {_POSTED}
                   AND e.entry_date > %s AND e.entry_date <= %s""",
            (1, d0.isoformat(), d1.isoformat()))["n"])
    else:
        pl = reports.profit_and_loss(1, None, None)
        entryCount = int(query_one(
            f"""SELECT COUNT(*) AS n FROM journal_entries e
                 WHERE e.entity_id=%s AND {_POSTED}""", (1,))["n"])

    return {
        "period": period or "全部期间",
        "currency": "HKD",
        "revenue": round(float(pl["revenue"]["total"]), 2),
        "costOfSales": round(float(pl["costOfSales"]["total"]), 2),
        "grossProfit": round(float(pl["grossProfit"]), 2),
        "otherIncome": round(float(pl["otherIncome"]["total"]), 2),
        "otherGains": round(float(pl["otherGains"]["total"]), 2),
        "operatingExpenses": round(float(pl["operatingExpenses"]["total"]), 2),
        "financeCosts": round(float(pl["financeCosts"]["total"]), 2),
        "profitBeforeTax": round(float(pl["profitBeforeTax"]), 2),
        "netProfit": round(float(pl["netProfit"]), 2),
        "entryCount": entryCount,
        "basis": "取自损益表（HKAS 1），只读；与报表中心同一口径",
        "note": "净利未含税务调整；应缴税请用 tax_compute 另算",
    }


def _receivables(args):
    """谁还欠我钱：按客户列未收余额。"""
    rows = query("""SELECT COALESCE(c.customer_name, i.supplier_name) AS party,
                           i.currency, SUM(i.gross_original - i.settled_original) AS outstanding
                      FROM invoices i
                      LEFT JOIN customers c ON c.customer_id = i.customer_id
                     WHERE i.entity_id = %s AND i.status = 'posted'
                       AND (i.gross_original - i.settled_original) > 0
                     GROUP BY party, i.currency
                     ORDER BY outstanding DESC LIMIT 30""", (1,))
    out = [{"party": r["party"], "currency": r["currency"],
            "outstanding": float(r["outstanding"])} for r in rows]
    note = "仅 HKD 合计；外币按币种分列，不直接相加"
    if len(out) >= 30:
        # 截断了要自己说出来，不能让调用方以为这就是全部
        note += "；只列前 30 个往来单位，还有更多未列出，合计仅含这 30 个"
    return {"rows": out, "count": len(out),
            "totalHkd": round(sum(x["outstanding"] for x in out if x["currency"] == "HKD"), 2),
            "truncated": len(out) >= 30,
            "note": note}


def _compliance_calendar(args):
    """本年度合规事项与倒计时。日期由数据库给，不估算。"""
    from datetime import date
    rows = query("""SELECT code, title, due_date, recurrence, note, status
                      FROM compliance_items
                     WHERE entity_id=%s AND status='open'
                     ORDER BY due_date LIMIT 50""", (1,))
    today = date.today()
    out = []
    for r in rows:
        due = r["due_date"]
        out.append({"code": r["code"], "title": r["title"],
                    "dueDate": due.isoformat(),
                    "daysLeft": (due - today).days,
                    "note": r["note"]})
    return {"today": today.isoformat(), "items": out,
            "overdue": [x for x in out if x["daysLeft"] < 0],
            "next": out[0] if out else None}


# ---------------------------------------------------------------- 注册
def _schema(props, required=None):
    return {"type": "object", "properties": props, "required": required or []}


TOOLS = {
    "journal_check": {
        "level": "read",
        "desc": "机械校验一条分录：借贷平衡、行结构、文档缺口、职责分离。不做准则判断。",
        "schema": _schema({
            "entry": {"type": "object", "description": "分录草稿：entryId/entryDate/currency/lines[]/requiredDocuments[]/documents[]/preparedBy/reviewedBy"},
        }, ["entry"]),
        "fn": lambda a: journal_check(a.get("entry")),
    },
    "variance_bridge": {
        "level": "read",
        "desc": "差异桥接：基准 + 驱动 = 期望；实际 − 期望 = 残差。残差显式暴露。",
        "schema": _schema({
            "bridge": {"type": "object", "description": "base / actual / drivers[{label,amount}]"},
        }, ["bridge"]),
        "fn": lambda a: variance_bridge(a.get("bridge")),
    },
    "reconciliation_snapshot": {
        "level": "read",
        "desc": "对账快照：账面对银行，列未达项，算差额。",
        "schema": _schema({
            "snapshot": {"type": "object", "description": "bookBalance / bankBalance / outstandingItems[]"},
        }, ["snapshot"]),
        "fn": lambda a: reconciliation_snapshot(a.get("snapshot")),
    },
    "sql_readonly": {
        "level": "read",
        "desc": "只读查询。只允许 SELECT，表必须在白名单内，自动加 LIMIT。",
        "schema": _schema({"sql": {"type": "string"}}, ["sql"]),
        "fn": _sql_readonly,
    },
    "account_search": {
        "level": "read",
        "desc": "按编码/中英文名搜科目。",
        "schema": _schema({"keyword": {"type": "string"}}, ["keyword"]),
        "fn": _account_search,
    },
    "account_history": {
        "level": "read",
        "desc": "查同一客户/供应商历史上用的科目，用于推荐科目。",
        "schema": _schema({"party": {"type": "string"}}, ["party"]),
        "fn": _account_history,
    },
    "propose_document": {
        "level": "propose",
        "desc": ("把一张单据的识别结果变成「待确认」提案（不写业务表），"
                 "用户在界面点确认后才建单。仅在「只提案」模式下使用；"
                 "能直接执行时请调 create_bill / create_invoice。"),
        "schema": _schema({
            "kind": {"type": "string", "enum": ["bill", "invoice", "expense"]},
            "partyName": {"type": "string", "description": "往来单位名称"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "dueDate": {"type": "string"},
            "currency": {"type": "string", "description": "HKD/USD/CNY…"},
            "amountOriginal": {"type": "number", "description": "不含税金额"},
            "taxOriginal": {"type": "number", "description": "税额"},
            "docNo": {"type": "string", "description": "对方单据号"},
            "lines": {"type": "array", "items": {"type": "object"},
                      "description": "明细行：{description, amount}"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "sourceNote": {"type": "string", "description": "来源说明，如「OCR 识别自 PDF」"},
        }, ["kind", "partyName"]),
        "fn": _propose_document,
    },
    "bank_match_suggestions": {
        "level": "read",
        "desc": "未匹配银行流水与候选单据（P1–P3 打分）。要确认匹配请接着调 confirm_bank_match。",
        "schema": _schema({"accountId": {"type": "integer", "description": "银行账户 id，可从 bank_accounts 取"}}),
        "fn": _bank_match_suggestions,
    },
    "export_pdf": {
        "level": "read",
        "desc": ("把报表导成 PDF，并给出可直接下载的链接。用户说「给我 PDF / 发我报表」时用它，"
                 "不要说自己不能生成 PDF，也不要让用户去别的页面导。"
                 "kind: pnl 利润表 / balance-sheet 财务状况表 / cash-flow 现金流量表 / "
                 "trial-balance 试算表 / aging 账龄 / gl 总账 / daybook 日记簿 / statements 全套报表。"
                 "from/to 不填则默认本年度至今。"),
        "schema": _schema({
            "kind": {"type": "string",
                     "enum": ["pnl", "balance-sheet", "cash-flow", "trial-balance",
                              "aging", "gl", "daybook", "statements"],
                     "description": "要导出的报表"},
            "from": {"type": "string", "description": "起日 YYYY-MM-DD，可空"},
            "to": {"type": "string", "description": "止日 YYYY-MM-DD，可空"},
            "lang": {"type": "string", "enum": ["en", "zh_hk", "zh_cn"],
                     "description": "报表语言：简体中文 zh_cn / 繁體中文 zh_hk / 英文 en。用户用中文提问就用中文，默认跟随界面语言"},
        }, required=["kind"]),
        "fn": lambda a: _export_pdf(a),
    },
    "financial_analysis": {
        "level": "read",
        "desc": ("生成完整财务分析报告：真实 KPI、月度趋势、费用结构、应收应付、现金、勾稽及完整财务报表，"
                 "并导出 PDF 或真正的 DOCX。默认本财务年至今、不使用 AI；返回确定性摘要和受控下载链接。"
                 "period=fiscal_year 时 year 指财务年度开始年；custom 必须同时给 from/to。"),
        "schema": _schema({
            "period": {"type": "string", "enum": ["this_month", "month", "calendar_year", "fiscal_year", "inception", "custom"]},
            "month": {"type": "string", "description": "period=month 时使用，YYYY-MM"},
            "year": {"type": "string", "description": "自然年份，或财务年度开始年，YYYY"},
            "from": {"type": "string", "description": "custom 起日 YYYY-MM-DD"},
            "to": {"type": "string", "description": "custom 止日 YYYY-MM-DD"},
            "lang": {"type": "string", "enum": ["zh_cn", "zh_hk", "en"], "description": "报告语言，默认跟随界面"},
            "format": {"type": "string", "enum": ["pdf", "docx"], "description": "下载格式，默认 pdf"},
        }),
        "fn": lambda a: _financial_analysis(a),
    },
    "workbench_todo": {
        "level": "read",
        "desc": ("读取 AI 工作台真实待办队列。section=all 全部；pending 待复核/阻断；"
                 "overdue 逾期应收（含到期日、逾期天数和账龄区间）；draft 待记账草稿；bank 未匹配流水汇总。"
                 "查看待办、待复核或逾期应收时先用它，不要用模型猜数。"),
        "schema": _schema({"section": {"type": "string",
                                       "enum": ["all", "pending", "overdue", "draft", "bank"]}}),
        "fn": _workbench_todo,
    },
    "period_close_status": {
        "level": "read",
        "desc": ("只读查看指定月（YYYY-MM，默认本月）的月结六步状态、完成数量、银行/应收应付/汇率缺口。"
                 "用户只看月结状态时必须用它，禁止调用 run_period_close。"),
        "schema": _schema({"period": {"type": "string", "description": "YYYY-MM，默认本月"}}),
        "fn": _period_close_status,
    },
    "document_detail": {
        "level": "read",
        "desc": ("按单号读取销售发票或采购账单的完整字段、明细、状态、未结金额及后续可办事项。"
                 "用户说「在这里显示单据 XXX 的完整内容」时使用；不要只给人工页面链接。"),
        "schema": _schema({"docNo": {"type": "string", "description": "完整单据编号"},
                           "kind": {"type": "string", "enum": ["invoice", "bill"],
                                    "description": "已知单据类型；不确定可省略，系统会同时查找"}}, ["docNo"]),
        "fn": _document_detail,
    },
    "reconciliation_detail": {
        "level": "read",
        "desc": ("按 statement_imports 的 batchId 还原该次对账的真实流水、匹配状态、匹配单号和规则；"
                 "未传 batchId 时读取当前实体最近导入批次。用户说「本次对账 / 看对账明细」且给出 batchId 时先用它。"
                 "它只读历史结果；仍需新候选时再调 bank_match_suggestions，不得把当前空队列当作历史结果。"),
        "schema": _schema({"batchId": {"type": "integer",
                                       "description": "对账单导入批次号；省略时取最近批次"}}),
        "fn": _reconciliation_detail,
    },
    "export_document_pdf": {
        "level": "read",
        "desc": ("按单号导出单张单据 PDF（发票 / 账单 / 报价单 / 贷记单），返回可直接下载的链接。"
                 "用户说「把 LEDU-INV-… 导出 PDF」「给我那张账单的 PDF」时用它，"
                 "不要说自己没有这个工具、也不要让用户去别的页面导。"
                 "kind：invoice 发票 / bill 账单 / quote 报价单 / credit 贷记单。"),
        "schema": _schema({
            "kind": {"type": "string", "enum": ["invoice", "bill", "quote", "credit"],
                     "description": "单据类型"},
            "docNo": {"type": "string", "description": "单号，例如 LEDU-INV-20261115-023"},
            "lang": {"type": "string", "enum": ["zh_cn", "zh_hk", "en"],
                     "description": "PDF 语言，默认跟随界面"},
        }, required=["kind", "docNo"]),
        "fn": lambda a: _export_document_pdf(a),
    },
    "bank_accounts": {
        "level": "read",
        "desc": "银行账户清单（含 accountId、币种、余额）。登记收付款前先查。",
        "schema": _schema({}),
        "fn": _bank_accounts,
    },
    "match_party": {
        "level": "read",
        "desc": "客户/供应商名称模糊匹配到档案。",
        "schema": _schema({"name": {"type": "string"},
                           "kind": {"type": "string", "enum": ["customer", "vendor"]}}, ["name"]),
        "fn": _party_match,
    },
    "hkfrs15_assess": {
        "level": "read",
        "desc": "判定收入确认情形是否被规则文件覆盖。未覆盖时必须交人工。",
        "schema": _schema({"caseId": {"type": "string"}}),
        "fn": _hkfrs15_assess,
    },
    "tax_compute": {
        "level": "read",
        "desc": "香港利得税两级制计算。two_tier_status=undetermined 时拒绝计算。",
        "schema": _schema({
            "twoTierStatus": {"type": "string", "enum": ["nominated", "not_nominated", "undetermined"]},
            "assessableProfit": {"type": "number"},
        }, ["twoTierStatus", "assessableProfit"]),
        "fn": _tax_compute,
    },
    "analyze_document": {
        "level": "read",
        "desc": "分析单据：判断是采购还是销售、单据类型，并按该往来单位历史与关键词推荐科目、"
                "借贷方向与分录预览；采购/费用同时判断公司直付或个人报销。只给建议，不写账。",
        "schema": _schema({
            "text": {"type": "string", "description": "单据文本，含抬头与金额行"},
            "party": {"type": "string", "description": "已知往来单位名称，可选"},
            "lines": {"type": "array", "items": {"type": "object"},
                      "description": "结构化明细，可选；不传则从文本行里找"},
            "extracted": {"type": "object",
                          "description": "已提取字段，可选；actionType 可明确 create_bill/create_expense/create_invoice"},
        }, ["text"]),
        "fn": _analyze_document,
    },
    "open_docs": {
        "level": "read",
        "desc": "列出未结清的发票或账单（用于核销建议）。",
        "schema": _schema({"kind": {"type": "string", "enum": ["invoice", "bill"]}}),
        "fn": _open_docs,
    },
    "bank_lines": {
        "level": "read",
        "desc": "列出未匹配的银行流水。",
        "schema": _schema({}),
        "fn": _bank_lines,
    },
    "finance_summary": {
        "level": "read",
        "desc": "一句话问财务：给期间（如 2026-11 / 2026 / 不填=全部），返回收入、销售成本、经营费用、毛利、净利。数字由确定性代码计算。",
        "schema": _schema({"period": {"type": "string", "description": "YYYY-MM 或 YYYY，留空为全部期间"}}),
        "fn": _finance_summary,
    },
    "receivables": {
        "level": "read",
        "desc": "谁还欠我钱：按客户列未收余额，外币分币种不合并。",
        "schema": _schema({}),
        "fn": _receivables,
    },
    "compliance_calendar": {
        "level": "read",
        "desc": "合规日历：利得税报税表、BR 续期、NAR1、核数准备，含法定截止日与剩余天数。日期来自数据库，不得估算。",
        "schema": _schema({}),
        "fn": _compliance_calendar,
    },
}


def openai_tools(names):
    """把指定工具转成 OpenAI tools 格式。"""
    out = []
    for n in names:
        t = TOOLS.get(n)
        if not t:
            continue
        out.append({
            "type": "function",
            "function": {"name": n, "description": t["desc"], "parameters": t["schema"]},
        })
    return out


def call(name, args):
    t = TOOLS.get(name)
    if not t:
        raise ToolError(f"工具不在白名单：{name}")
    return t["fn"](args or {})


def describe():
    """全部工具（只读 + 可执行），供智能体页面展示权限。"""
    from .tools_write import WRITE_TOOLS
    out = [{"name": n, "level": t["level"], "desc": t["desc"]}
           for n, t in TOOLS.items()]
    out += [{"name": n, "level": "write", "desc": t["desc"] + "（会写账套）"}
            for n, t in WRITE_TOOLS.items()]
    return out
