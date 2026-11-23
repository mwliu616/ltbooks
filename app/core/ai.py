# LtBooks — core/ai.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""AI 层：自然语言查账、差异桥、发票字段解析。

设计约束：
- AI 只读。所有生成 SQL 强制 SELECT，禁写、禁 DDL、禁元数据表、强制 LIMIT。
- AI 不计算金额。数字一律来自数据库或确定性代码；AI 只负责「翻译问题」与「解释结果」。
- AI 输出标注为 AI 生成，不构成过账授权。
"""
import re
import json
import re

import urllib.error
import urllib.request

from config import env
from .db import query

DISCLAIMER = "AI 生成，仅供辅助；金额与结论须人工复核，不构成过账授权"

SCHEMA = """
实体与科目：
  entities(entity_id, entity_code, entity_name, functional_currency, two_tier_status)
  accounts(account_code, account_name, category, fs_line_item, normal_balance)
      category: asset/liability/equity/revenue/cogs/expense
单据：
  invoices(invoice_id, invoice_no, supplier_name, invoice_date, currency, amount_original,
           tax_original, gross_original, amount_functional, settled_original, status, revenue_account_code)
  bills(bill_id, bill_no, vendor_name, date, currency, amount, tax_amount, gross_original,
        amount_functional, settled_original, status)
  expenses(expense_id, expense_no, category, date, currency, amount, amount_functional, status)
分录：
  journal_entries(entry_id, entry_no, entry_date, period, source_type, status, total_debit, total_credit)
  journal_lines(entry_id, line_no, account_code, description, debit, credit, ccy, amount_original, rate)
银行：
  bank_accounts(account_id, name, currency, current_balance, current_balance_functional)
  bank_lines(line_id, bank_account_id, bank_ref, txn_date, amount_original, currency,
             counterparty_name, match_status)
  payments_received(payment_no, date, amount, currency, amount_functional, settlement_fx_diff)
  payments_made(payment_no, date, amount, currency, amount_functional, settlement_fx_diff)
其他：
  customers(customer_name, default_currency, payment_terms_days)
  vendors(vendor_name, default_currency)
  fx_rates(rate_date, from_ccy, to_ccy, rate)
  pending_review(kind, ref_table, ref_id, reason, severity, status)
  audit_log(seq_no, actor, action, object_type, object_id, created_at)
说明：
  status 取值：invoices/bills 为 draft/posted/void；journal_entries 为 draft/posted/reversed
  金额单位为功能货币 HKD，除非列名带 currency 注明
  不同币种不得直接相加
"""

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|replace|"
    r"information_schema|mysql\.|performance_schema|sys\.|load_file|outfile|"
    r"sleep|benchmark)\b", re.I)


class AIError(Exception):
    pass


def _post(url, payload, headers, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers=dict({"Content-Type": "application/json"}, **headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise AIError(f"模型接口返回 {e.code}：{body}")
    except Exception as e:
        raise AIError(f"模型接口不可用：{e}")


def _llm(messages, *, temperature=0.2, max_tokens=1200, json_mode=False):
    from .settings import llm_config
    c = llm_config()
    key = c["apiKey"]
    if not key:
        raise AIError("未配置大模型 API Key：环境变量 LEDU_LLM_API_KEY 或 系统设置 → 大模型")
    base = (c["base"] or "https://api.deepseek.com").rstrip("/")
    model = c["model"] or "deepseek-chat"
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = _post(base + "/chat/completions", payload, {"Authorization": "Bearer " + key})
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise AIError("模型返回结构异常")


# ------------------------------------------------------------------ NL → SQL
def _clean_sql(text):
    s = text.strip()
    s = re.sub(r"^```(?:sql)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    s = s.strip().rstrip(";").strip()
    return s


def safe_sql(sql):
    """只允许单条 SELECT；拦截写操作、元数据表与文件函数。"""
    s = _clean_sql(sql)
    if not re.match(r"^(select|with)\b", s, re.I):
        raise AIError("生成的语句不是查询语句，已拒绝执行")
    if FORBIDDEN.search(s):
        raise AIError("查询包含不允许的关键字，已拒绝执行")
    # 初始：只拦截普通注释（-- 或 /* 但不是 MariaDB 优化器提示 /*+）
    if re.search(r"--|/\*(?!\+)", s):
        raise AIError("查询包含注释，已拒绝执行")
    if s.count(";") > 0:
        raise AIError("只允许单条语句")
    if not re.search(r"\blimit\b", s, re.I):
        s += " LIMIT 200"
    # MariaDB MAX_EXECUTION_TIME 提示 — 防止 AI 生成全表扫描慢查询耗尽连接
    if not re.search(r"MAX_EXECUTION_TIME\s*\(", s, re.I):
        s = re.sub(r"^\s*select\b", "SELECT /*+ MAX_EXECUTION_TIME(10000) */", s, count=1, flags=re.I)
    return s


def nl_query(question, max_rows=200):
    """自然语言问账：生成 SQL → 安全校验 → 执行 → 用模型解释结果。"""
    prompt = (
        "你是会计数据查询助手。根据下面的库表结构，把用户的问题翻译成一条 MariaDB 查询语句。\n"
        "规则：\n"
        "1. 只能写一条 SELECT，不要写任何写操作，不要加注释。\n"
        "2. 必须包含 LIMIT（最多 200）。\n"
        "3. 不同币种不得直接相加；需要合计时按币种分组或只用 *_functional 列。\n"
        "4. 只返回 SQL 本身，不要解释。\n\n"
        f"库表结构：\n{SCHEMA}\n\n用户问题：{question}"
    )
    sql = safe_sql(_llm([{"role": "user", "content": prompt}], temperature=0, max_tokens=600))

    try:
        rows = query(sql.replace("%", "%%"))
    except Exception as e:
        raise AIError(f"查询执行失败：{e}")

    rows = rows[:max_rows]
    preview = rows[:50]
    explain = (
        "下面是用户问题与数据库返回的真实结果。用中文简洁回答用户，"
        "只使用结果中的数字，不要自行计算或推测；若结果为空，直接说明没有数据。"
        "金额请保留两位小数并标注币种或 HKD。\n\n"
        f"问题：{question}\n执行的 SQL：{sql}\n结果（最多 50 行）："
        f"{json.dumps(preview, ensure_ascii=False, default=str)}"
    )
    answer = _llm([{"role": "user", "content": explain}], temperature=0.2, max_tokens=800)
    return {"question": question, "sql": sql, "rowCount": len(rows),
            "rows": preview, "answer": answer.strip(), "disclaimer": DISCLAIMER}


# ------------------------------------------------------------------ 差异桥
def variance_bridge(expected, actual, factors):
    """量价差异分解由确定性代码完成，模型只负责解释。"""
    from .money import dec
    e, a = dec(expected), dec(actual)
    if e is None or a is None:
        raise AIError("预期值或实际值非法")
    total = a - e
    pct = None if e == 0 else float(total / e * 100)
    detail = []
    explained = dec(0)
    for f in factors or []:
        v = dec(f.get("amount"))
        if v is None:
            continue
        explained += v
        detail.append({"name": f.get("name") or "未命名因素", "amount": float(v),
                       "note": f.get("note")})
    unexplained = total - explained

    narration = None
    try:
        narration = _llm([{"role": "user", "content": (
            "用两三句中文解释下面的差异，语气客观，不要编造数字，"
            "若存在未解释差额要明确指出需要进一步核查。\n"
            f"预期 {e}，实际 {a}，总差异 {total}（{pct}%）。\n"
            f"已识别因素：{json.dumps(detail, ensure_ascii=False)}\n"
            f"未解释差额：{unexplained}")}], max_tokens=400).strip()
    except AIError:
        narration = None

    return {"expected": float(e), "actual": float(a), "totalVariance": float(total),
            "variancePercent": pct, "factors": detail,
            "explained": float(explained), "unexplained": float(unexplained),
            "complete": unexplained == 0,
            "narration": narration, "disclaimer": DISCLAIMER}


# ------------------------------------------------------------------ 发票字段解析
# 银行对账单/月结单的特征词：这类文件不是发票，识别成发票只会得到垃圾结果
STATEMENT_HINTS = ("statement", "portfolio summary", "total balance", "bank statement",
                   "statement of account", "opening balance", "closing balance",
                   "account number", "存款", "結單", "对账单", "賬戶結餘")
INVOICE_HINTS = ("invoice", "發票", "发票", "receipt", "收據", "收据", "tax invoice",
                 "bill to", "invoice no", "invoice number")


def looks_like_statement(text: str) -> dict:
    """判断这段文字是不是银行流水/月结单，而不是发票。

    只看关键词：命中 2 个以上对账单特征、且没有任何发票特征 → 判为对账单。
    返回 {"isStatement": bool, "hits": [...]}，让调用方能给人一句准话。
    """
    t = (text or "").lower()
    hits = [h for h in STATEMENT_HINTS if h in t]
    inv = [h for h in INVOICE_HINTS if h in t]
    return {"isStatement": len(hits) >= 2 and not inv, "hits": hits,
            "invoiceHits": inv}


EXTRACT_PROMPT = """从下面的发票/收据文本中提取字段，输出 JSON（不要输出其他内容）：
{
  "invoiceNo": "发票号",
  "supplierName": "开票方：把单据开给你的那一方，通常在页眉信头",
  "supplierAddress": "开票方地址或 null",
  "supplierPhone": "开票方电话或 null",
  "supplierTaxId": "开票方税号/商业登记号或 null",
  "customerName": "受票方：单据上的 TO / Bill To，或 null",
  "invoiceDate": "YYYY-MM-DD",
  "dueDate": "YYYY-MM-DD 或 null",
  "currency": "币种代码，如 HKD/USD/CNY/CAD",
  "amountOriginal": 不含税金额数字,
  "taxOriginal": 税额数字,
  "grossOriginal": 价税合计数字,
  "taxRate": 税率小数如 0.13,
  "lines": [
    {"description":"项目","amount":金额数字,"period":"服务期间或 null"}
  ],
  "paymentAccounts": [
    {"bank":"银行名","account":"账号","holder":"户名或 null"}
  ],
  "paymentTerms": "付款条款摘要或 null",
  "notes": "其他重要备注或 null",
  "confidence": "high/medium/low",
  "warnings": ["不确定之处"]
}
规则：
- 区分开票方与受票方：页眉公司是开票方，TO / Bill To 之后是受票方，不要混为一谈。
- 明细按单据逐行列出，金额取该行合计；括号里的服务期间填进 period。
- 单据若同时列出多个收款账户（如 CITIBANK、HSBC），全部列入 paymentAccounts。
- 受票方只填明确标注为购方 / 客户 / TO / Bill To 的单位名称；单据上的「用户名」「账号」「会员名」不算受票方，没有就填 null。
- 凭证编号、订单号、流水号都可作为 invoiceNo；同时把订单号写进 notes。
- 找不到的字段填 null，不要猜测；不要编造看不到的编号。
数字只输出数值不带千分位与货币符号。"""


def extract_invoice(text, hints: str = ""):
    """从文本里抽发票字段。hints 是这家供应商的历史纠正（few-shot），可为空。"""
    text = (text or "").strip()
    if len(text) < 10:
        # 这是输入问题，不是服务故障，调用方应按 400 处理
        raise ValueError("文本太短，无法识别")
    prompt = EXTRACT_PROMPT
    if hints:
        prompt += "\n\n" + hints
    raw = _llm([{"role": "user", "content": prompt + "\n\n文本：\n" + text[:8000]}],
               temperature=0, max_tokens=1200, json_mode=True)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise AIError("模型返回的不是合法 JSON")

    # 数额一致性自检：金额 + 税额应等于价税合计
    from .money import dec
    a, t, g = dec(data.get("amountOriginal")), dec(data.get("taxOriginal")), dec(data.get("grossOriginal"))
    warnings = list(data.get("warnings") or [])

    # OCR 常把 118 读成 18。真单据通常会多次出现同一金额，按出现次数的多数票纠正。
    yuan = [int(x) for x in re.findall(r"(\d{1,9})\s*元", text)]
    if yuan:
        from collections import Counter
        val, times = Counter(yuan).most_common(1)[0]
        conflicting = len(set(yuan)) > 1
        if times >= 2 and g is not None and abs(float(g) - val) > 0.005:
            warnings.append(f"单据多次出现「{val} 元」，但识别的价税合计是 {g}；已按多数票改为 {val}，请核对原件")
            data["grossOriginal"] = g = dec(val)
            if a is not None:
                data["amountOriginal"] = a = dec(val)
            data["confidence"] = "low"
        elif conflicting and g is not None and abs(float(g) - val) > 0.005:
            warnings.append(f"单据同时出现多个金额，识别取 {g}，另有 {val}；请核对原件")

    # 明细合计应与「不含税金额」一致（明细通常是不含税行金额，税额单列）
    lines = data.get("lines") or []
    if lines and g is not None:
        try:
            s_lines = sum(float(dec(x.get("amount")) or 0) for x in lines)
            base = float(a) if (a is not None and t is not None and float(t) > 0) else float(g)
            if abs(s_lines - base) > 0.02:
                warnings.append(f"明细合计 {s_lines:,.2f} 与单据金额 {base:,.2f} 不符")
                data["confidence"] = "low"
        except Exception:
            pass

    if a is not None and t is not None and g is not None:
        if abs((a + t) - g) > dec("0.02"):
            warnings.append(f"金额勾稽不符：{a} + {t} ≠ {g}")
            data["confidence"] = "low"
    if a is not None and t is not None and a > 0 and data.get("taxRate") is None:
        data["taxRate"] = float(t / a)
    data["warnings"] = warnings
    data["disclaimer"] = DISCLAIMER
    return data


# ------------------------------------------------------------------ 客户资料
PARTY_PROMPT = """从下面的名片、公司注册证书、商业登记证、客户资料或往来邮件文本中提取客户档案字段，
输出 JSON（不要输出其他内容）：
{
  "customerType": "company 或 individual；公司填 company，个人名片填 individual",
  "customerName": "公司注册全称或姓名",
  "contactName": "联系人姓名或 null",
  "contactTitle": "职位或 null",
  "phone": "固定电话或 null",
  "mobile": "手机或 null",
  "fax": "传真或 null",
  "email": "邮箱或 null",
  "website": "网站或 null",
  "taxId": "商业登记号/税号/统一社会信用代码或 null",
  "address": "详细地址，合并为一行或 null",
  "district": "地区/城市或 null",
  "country": "国家/地区或 null",
  "currency": "文本中出现的结算币种代码，如 HKD/USD/CNY，没有则 null",
  "paymentTermsDays": 付款账期天数数字或 null,
  "notes": "其他有用信息（品牌、经营范围等）或 null",
  "confidence": "high/medium/low",
  "warnings": ["不确定之处"]
}
规则：
- 公司名称优先取注册全称；只有品牌名时保留原文，并在 warnings 说明。
- 电话与手机分开；无法区分时放 phone。
- 地址保留原文，不要编造或改写。
- 找不到的字段填 null，不要猜测；不要编造编号。
- 没有公司名、只有个人姓名的，customerType 填 individual。"""


def extract_party(text):
    """从名片/注册证书/客户资料文本里抽客户档案字段。"""
    text = (text or "").strip()
    if len(text) < 6:
        raise ValueError("文本太短，无法识别")
    raw = _llm([{"role": "user", "content": PARTY_PROMPT + "\n\n文本：\n" + text[:8000]}],
               temperature=0, max_tokens=900, json_mode=True)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise AIError("模型返回的不是合法 JSON")

    out = {}
    for k, v in (data or {}).items():
        if isinstance(v, str):
            v = v.strip()
            if v.lower() in ("", "null", "none", "n/a"):
                v = None
        out[k] = v
    if out.get("customerType") not in ("company", "individual"):
        out["customerType"] = "company"
    if not out.get("customerName"):
        raise AIError("没有识别到公司名称或姓名，请换更清晰的资料或手工填写")
    out["warnings"] = list(out.get("warnings") or [])
    out["disclaimer"] = DISCLAIMER
    return out


# ------------------------------------------------------------------ PG 分析
def analyze_review_queue(rows):
    """对当前待复核队列给出处置建议（只读，不改变数据）。"""
    if not rows:
        return {"advice": "当前没有待复核项。", "groups": [], "disclaimer": DISCLAIMER}
    compact = [{"kind": r.get("kind"), "severity": r.get("severity"),
                "reason": str(r.get("reason"))[:200]} for r in rows[:40]]
    groups = {}
    for r in compact:
        groups.setdefault(r["kind"], []).append(r)
    try:
        advice = _llm([{"role": "user", "content": (
            "下面是会计系统的待复核队列。用中文给出处置顺序建议：先说明哪几项会阻断过账，"
            "再说明可批量处理的类型。不要编造不存在的项目。\n"
            + json.dumps(compact, ensure_ascii=False))}], max_tokens=600).strip()
    except AIError as e:
        advice = f"AI 不可用：{e}"
    return {"advice": advice,
            "groups": [{"kind": k, "count": len(v)} for k, v in groups.items()],
            "disclaimer": DISCLAIMER}
