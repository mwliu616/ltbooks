# LtBooks — core/financial_analysis.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""LtBooks 财务分析报告：确定性取数、三语解读与 PDF/DOCX 导出。

金额只来自 core.reports。AI 是可选的定性文案层，不参与计算；任何 AI
不可用或输出不合规的情况都回退到确定性文案。
"""
from __future__ import annotations

import calendar
import html
import json
import re
import tempfile
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from . import reports
from .db import query, query_one

LANGS = ("zh_cn", "zh_hk", "en")
PERIODS = ("this_month", "month", "calendar_year", "fiscal_year", "inception", "custom")
TOLERANCE = Decimal("0.01")


def _L(lang, cn, hk, en):
    return {"zh_cn": cn, "zh_hk": hk, "en": en}.get(lang, en)


def _d(value=0):
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _f(value):
    return float(_d(value).quantize(Decimal("0.01")))


def _money(value):
    return "—" if value is None else f"{_d(value):,.2f}"


def _date(value, name):
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        raise ValueError(f"{name} 必须是 YYYY-MM-DD")


def _month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def _fy_end(year, mmdd):
    match = re.fullmatch(r"(\d{2})-(\d{2})", str(mmdd or "12-31"))
    if not match:
        raise ValueError("公司 fiscalYearEnd 必须是 MM-DD")
    month, day = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        raise ValueError("公司 fiscalYearEnd 日期无效")
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _book_bounds(entity_id, today):
    row = query_one(
        """SELECT MIN(entry_date) AS first_date, MAX(entry_date) AS last_date
             FROM journal_entries
            WHERE entity_id=%s AND status IN ('posted','reversed')
              AND entry_date <= %s""", (entity_id, today.isoformat())) or {}
    first, last = row.get("first_date"), row.get("last_date")
    return ((first if isinstance(first, date) else None),
            (last if isinstance(last, date) else None))


def resolve_period(entity, period="this_month", month="", year="", start="", end="",
                   *, today=None, bounds=None):
    """返回首尾均包含的实际期间；所有实际报表期间都不延伸到未来。

    fiscal_year 的 year 指财务年度开始年；inception 使用首条已过账分录日期。
    """
    today = today or date.today()
    kind = str(period or "this_month").strip()
    kind = {"current_month": "this_month", "specified_month": "month",
            "year": "calendar_year", "fy": "fiscal_year", "all": "inception"}.get(kind, kind)
    if kind not in PERIODS:
        raise ValueError("period 仅支持 this_month/month/calendar_year/fiscal_year/inception/custom")
    entity_id = int(entity.get("entity_id") or entity.get("id") or 1)
    first_book, last_book = bounds if bounds is not None else _book_bounds(entity_id, today)
    clamped = False

    if kind == "this_month":
        d0, d1 = today.replace(day=1), today
    elif kind == "month":
        if not re.fullmatch(r"\d{4}-\d{2}", str(month or "")):
            raise ValueError("指定月必须提供 month=YYYY-MM")
        y, m = int(month[:4]), int(month[5:7])
        try:
            d0 = date(y, m, 1)
        except ValueError:
            raise ValueError("指定月份无效")
        d1 = min(today, _month_end(y, m))
    elif kind == "calendar_year":
        y = int(year) if str(year or "").strip() else today.year
        if not 1900 <= y <= 9999:
            raise ValueError("自然年年份无效")
        d0, d1 = date(y, 1, 1), min(today, date(y, 12, 31))
    elif kind == "fiscal_year":
        fye = str(entity.get("fiscal_year_end_mmdd") or entity.get("fiscalYearEnd") or "12-31")
        if str(year or "").strip():
            start_year = int(year)
        else:
            current_end = _fy_end(today.year, fye)
            if today > current_end:
                current_end = _fy_end(today.year + 1, fye)
            start_year = current_end.year - 1
        if not 1899 <= start_year <= 9998:
            raise ValueError("财务年度开始年无效")
        fiscal_end = _fy_end(start_year + 1, fye)
        d0 = _fy_end(start_year, fye) + timedelta(days=1)
        d1 = min(today, fiscal_end)
    elif kind == "inception":
        # 起点取首条有效分录；截止日始终是香港业务日“今天”。
        # 最后一张凭证日期只放入 dataThrough，不能把“开业至今”缩短到最后记账日。
        d0 = first_book or today.replace(day=1)
        d1 = today
    else:
        if not start or not end:
            raise ValueError("自定义期间必须同时提供 from 和 to")
        d0, d1 = _date(start, "from"), _date(end, "to")

    if d0 > today:
        raise ValueError("实际财务分析的起日不能晚于今天")
    if d1 > today:
        d1, clamped = today, True
    if d0 > d1:
        raise ValueError("期间起日不能晚于止日")
    return {
        "type": kind, "start": d0.isoformat(), "end": d1.isoformat(),
        "month": str(month or "") or None,
        "year": int(year) if str(year or "").strip() else None,
        "fiscalYearEnd": (entity.get("fiscal_year_end_mmdd") or entity.get("fiscalYearEnd")),
        "firstBookDate": first_book.isoformat() if first_book else None,
        "dataThrough": last_book.isoformat() if last_book else None,
        "clampedToToday": clamped or (d1 == today and kind in ("this_month", "month", "calendar_year", "fiscal_year")),
        "noBookData": first_book is None,
    }


def _month_slices(start, end):
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    cursor = d0.replace(day=1)
    while cursor <= d1:
        last = _month_end(cursor.year, cursor.month)
        yield cursor, max(cursor, d0), min(last, d1)
        cursor = last + timedelta(days=1)


def _sum_section(pl, keys):
    return sum((_d(pl[k]["total"]) for k in keys), Decimal(0))


def _pl_kpis(pl):
    revenue = _d(pl["revenue"]["total"])
    expense = _sum_section(pl, ("operatingExpenses", "financeCosts", "taxExpense"))
    return revenue, expense, _d(pl["netProfit"])


def _check(code, label, ok, difference=0, detail=""):
    return {"code": code, "label": label, "ok": bool(ok),
            "difference": _f(difference), "detail": detail}


def _entry_checks(entity_id, start, end, lang):
    count_row = query_one(
        """SELECT COUNT(*) AS n FROM journal_entries e
            WHERE e.entity_id=%s AND e.status IN ('posted','reversed')
              AND e.entry_date >= %s AND e.entry_date <= %s""",
        (entity_id, start, end)) or {}
    bad_count = query_one(
        """SELECT COUNT(*) AS n FROM journal_entries e
            WHERE e.entity_id=%s AND e.status IN ('posted','reversed')
              AND e.entry_date >= %s AND e.entry_date <= %s
              AND ABS((SELECT COALESCE(SUM(l.debit),0) FROM journal_lines l WHERE l.entry_id=e.entry_id)
                    - (SELECT COALESCE(SUM(l.credit),0) FROM journal_lines l WHERE l.entry_id=e.entry_id)) >= 0.005""",
        (entity_id, start, end)) or {}
    rows = query(
        """SELECT e.entry_id, e.entry_no, e.entry_date,
                  COALESCE(SUM(l.debit),0) AS debit, COALESCE(SUM(l.credit),0) AS credit
             FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.entry_id
            WHERE e.entity_id=%s AND e.status IN ('posted','reversed')
              AND e.entry_date >= %s AND e.entry_date <= %s
            GROUP BY e.entry_id, e.entry_no, e.entry_date
           HAVING ABS(COALESCE(SUM(l.debit),0)-COALESCE(SUM(l.credit),0)) >= 0.005
            ORDER BY e.entry_date, e.entry_id LIMIT 20""", (entity_id, start, end))
    items = [{"entryId": int(r["entry_id"]), "entryNo": r["entry_no"],
              "entryDate": r["entry_date"].isoformat() if hasattr(r["entry_date"], "isoformat") else str(r["entry_date"]),
              "debit": _f(r["debit"]), "credit": _f(r["credit"]),
              "difference": _f(_d(r["debit"]) - _d(r["credit"]))} for r in rows]
    return int(count_row.get("n") or 0), int(bad_count.get("n") or 0), items


def _deterministic_narrative(report):
    lang, p, k = report["lang"], report["period"], report["kpis"]
    ccy, start, end = report["entity"]["currency"], p["start"], p["end"]
    margin = k["netMargin"]
    margin_text = (_L(lang, f"{margin:.2f}%", f"{margin:.2f}%", f"{margin:.2f}%")
                   if margin is not None else _L(lang, "收入为零，不计算", "收入為零，不計算", "not applicable with zero revenue"))
    summary = _L(
        lang,
        f"{start} 至 {end}，收入 {_money(k['revenue'])} {ccy}，净利 {_money(k['netProfit'])} {ccy}，净利率 {margin_text}。",
        f"{start} 至 {end}，收入 {_money(k['revenue'])} {ccy}，淨利 {_money(k['netProfit'])} {ccy}，淨利率 {margin_text}。",
        f"For {start} to {end}, revenue was {_money(k['revenue'])} {ccy} and net profit was {_money(k['netProfit'])} {ccy}; net margin was {margin_text}.")
    paragraphs = [_L(
        lang,
        f"毛利 {_money(k['grossProfit'])} {ccy}，费用（经营费用、财务费用及税项）{_money(k['expenses'])} {ccy}；经营活动现金流 {_money(k['operatingCashFlow'])} {ccy}。",
        f"毛利 {_money(k['grossProfit'])} {ccy}，費用（經營費用、財務費用及稅項）{_money(k['expenses'])} {ccy}；經營活動現金流 {_money(k['operatingCashFlow'])} {ccy}。",
        f"Gross profit was {_money(k['grossProfit'])} {ccy}. Expenses (operating, finance and tax) were {_money(k['expenses'])} {ccy}; operating cash flow was {_money(k['operatingCashFlow'])} {ccy}."), _L(
        lang,
        f"期末现金 {_money(k['cash'])} {ccy}，应收账款 {_money(k['receivables'])} {ccy}，应付账款 {_money(k['payables'])} {ccy}；现金净变动 {_money(k['netCashChange'])} {ccy}。",
        f"期末現金 {_money(k['cash'])} {ccy}，應收賬款 {_money(k['receivables'])} {ccy}，應付賬款 {_money(k['payables'])} {ccy}；現金淨變動 {_money(k['netCashChange'])} {ccy}。",
        f"Closing cash was {_money(k['cash'])} {ccy}, trade receivables were {_money(k['receivables'])} {ccy}, and trade payables were {_money(k['payables'])} {ccy}; net cash movement was {_money(k['netCashChange'])} {ccy}.")]
    expenses = [x for x in report["expenseBreakdown"] if abs(_d(x["amount"])) >= Decimal("0.005")]
    if expenses:
        top = max(expenses, key=lambda x: abs(_d(x["amount"])))
        paragraphs.append(_L(
            lang,
            f"最大成本费用项目为“{top['label']}”，金额 {_money(top['amount'])} {ccy}。",
            f"最大成本費用項目為「{top['label']}」，金額 {_money(top['amount'])} {ccy}。",
            f"The largest cost or expense item was {top['label']}, at {_money(top['amount'])} {ccy}."))
    if not report["data"]["hasPeriodEntries"]:
        paragraphs.append(_L(
            lang, "本期间没有已过账或已冲销分录，金额为零不代表已发生经营；请勿将空期间解释为实际业绩。",
            "本期間沒有已過賬或已沖銷分錄，金額為零不代表已發生經營；請勿將空期間解釋為實際業績。",
            "There are no posted or reversed entries in this period. Zero amounts do not represent trading activity; do not interpret an empty period as actual performance."))
    failed = [x for x in report["checks"] if not x["ok"]]
    if failed:
        paragraphs.append(_L(
            lang,
            "勾稽异常：" + "；".join(f"{x['label']}，差额 {_money(x['difference'])} {ccy}" for x in failed) + "。请先复核账簿，再使用本报告作决策。",
            "勾稽異常：" + "；".join(f"{x['label']}，差額 {_money(x['difference'])} {ccy}" for x in failed) + "。請先覆核帳簿，再使用本報告作決策。",
            "Reconciliation exceptions: " + "; ".join(f"{x['label']}, difference {_money(x['difference'])} {ccy}" for x in failed) + ". Review the ledger before relying on this report."))
    else:
        paragraphs.append(_L(
            lang, "借贷、试算平衡、损益、资产负债与现金勾稽均已校验，未发现差额。",
            "借貸、試算平衡、損益、資產負債與現金勾稽均已校驗，未發現差額。",
            "Entry debit/credit, trial balance, profit or loss, balance sheet and cash reconciliations passed with no detected difference."))
    return {"summary": summary, "paragraphs": paragraphs}


def _ai_narrative(report):
    """只让模型写不含数字的定性文字，数字与期间由确定性层统一展示。"""
    from .agents import llm

    if not llm.available():
        return None, "unconfigured", None
    lang = report["lang"]
    facts = {"entity": report["entity"], "period": report["period"],
             "kpis": report["kpis"], "monthlyTrend": report["monthlyTrend"],
             "expenseBreakdown": report["expenseBreakdown"], "checks": report["checks"]}
    language = {"zh_cn": "简体中文", "zh_hk": "繁體中文（香港用字）", "en": "English"}[lang]
    prompt = (
        f"请用{language}撰写财务分析定性文案。只能依据随附 JSON 事实，不得补充外部事实、预测或建议数字。"
        "不要在 summary 或 paragraphs 中写任何阿拉伯数字、日期、金额或百分比；数字由系统另行列出。"
        "必须提及趋势方向、主要费用与现金/应收应付的定性关系；有勾稽异常时优先提示复核。"
        '只返回 JSON：{"summary":"一句定性总结","paragraphs":["两至四段定性分析"]}。')
    response = llm.chat([{"role": "system", "content": "你是严谨的财务报告编辑，不得编造。"},
                         {"role": "user", "content": prompt + "\n" + json.dumps(facts, ensure_ascii=False)}],
                        temperature=0.1, max_tokens=900, json_mode=True, timeout=30)
    text = str((response.get("message") or {}).get("content") or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
    parsed = json.loads(text)
    summary = str(parsed.get("summary") or "").strip()
    paragraphs = [str(x).strip() for x in (parsed.get("paragraphs") or []) if str(x).strip()]
    if not summary or not 1 <= len(paragraphs) <= 4:
        raise ValueError("AI 文案结构无效")
    if any(re.search(r"\d", x) for x in [summary] + paragraphs):
        raise ValueError("AI 文案包含未经确定性层输出的数字")
    if len(summary) > 1000 or any(len(x) > 1800 for x in paragraphs):
        raise ValueError("AI 文案过长")
    return {"summary": summary, "paragraphs": paragraphs}, "generated", response.get("model")


def _attach_narrative(report, use_ai):
    deterministic = _deterministic_narrative(report)
    status = "not_requested" if not use_ai else "failed"
    model = None
    narrative = deterministic
    if use_ai:
        try:
            generated, status, model = _ai_narrative(report)
            if generated:
                narrative = generated
        except Exception:
            # 不返回 API 地址、密钥或上游响应，也不阻断 JSON 与文件导出。
            status = "failed"
            narrative = deterministic
    lang = report["lang"]
    notices = {
        "not_requested": _L(lang, "未请求 AI；本解读由确定性规则根据真实报表数据生成，未使用 AI。",
                            "未請求 AI；本解讀由確定性規則根據真實報表數據生成，未使用 AI。",
                            "AI was not requested. This deterministic commentary was generated from actual report data; no AI was used."),
        "unconfigured": _L(lang, "AI API 未配置，已改用确定性分析，未使用 AI；不影响文件导出。",
                           "AI API 未配置，已改用確定性分析，未使用 AI；不影響文件匯出。",
                           "The AI API is not configured. Deterministic analysis is provided instead, without AI; exports remain available."),
        "failed": _L(lang, "AI 调用失败或输出未通过校验，已改用确定性分析，未使用 AI；不影响文件导出。",
                     "AI 調用失敗或輸出未通過校驗，已改用確定性分析，未使用 AI；不影響文件匯出。",
                     "AI failed or returned invalid content. Deterministic analysis is provided instead, without AI; exports remain available."),
        "generated": _L(lang, "AI 仅生成不含数字的定性文案；全部金额、期间与勾稽结论来自确定性报表，仍需人工复核。",
                        "AI 僅生成不含數字的定性文案；全部金額、期間與勾稽結論來自確定性報表，仍需人工覆核。",
                        "AI supplied qualitative text without figures only. All amounts, dates and reconciliation conclusions come from deterministic reports and require human review."),
    }
    report["analysis"] = {
        **narrative, "dataSummary": deterministic["summary"], "usedAi": status == "generated",
        "mode": "ai" if status == "generated" else "deterministic", "status": status,
        "model": model if status == "generated" else None, "notice": notices[status],
        "sourceNote": _L(lang,
            f"数据期间：{report['period']['start']} 至 {report['period']['end']}；来源：core.reports 的已过账分录报表及 journal_entries 借贷校验。",
            f"數據期間：{report['period']['start']} 至 {report['period']['end']}；來源：core.reports 的已過賬分錄報表及 journal_entries 借貸校驗。",
            f"Data period: {report['period']['start']} to {report['period']['end']}; sources: posted-entry reports in core.reports and journal_entries debit/credit checks."),
    }


def build_report(entity, *, period="this_month", month="", year="", start="", end="",
                 lang="zh_cn", use_ai=False, today=None):
    """构建可 JSON 序列化的完整分析数据。日期首尾均包含。"""
    lang = lang if lang in LANGS else "zh_cn"
    reports.set_report_lang(lang)
    entity_id = int(entity.get("entity_id") or entity.get("id") or 1)
    p = resolve_period(entity, period, month, year, start, end, today=today)
    d0, d1 = p["start"], p["end"]
    pl = reports.profit_and_loss(entity_id, d0, d1)
    bs = reports.balance_sheet(entity_id, d1)
    cf = reports.cash_flow(entity_id, d0, d1)
    tb = reports.trial_balance(entity_id, d1)
    ar = reports.aging(entity_id, "receivable", d1)
    ap = reports.aging(entity_id, "payable", d1)
    entry_count, unbalanced_count, unbalanced = _entry_checks(entity_id, d0, d1, lang)

    trend = []
    for month_start, slice_start, slice_end in _month_slices(d0, d1):
        mpl = reports.profit_and_loss(entity_id, slice_start.isoformat(), slice_end.isoformat())
        rev, exp, net = _pl_kpis(mpl)
        trend.append({"period": month_start.strftime("%Y-%m"),
                      "start": slice_start.isoformat(), "end": slice_end.isoformat(),
                      "revenue": _f(rev), "costOfSales": _f(mpl["costOfSales"]["total"]),
                      "expenses": _f(exp), "netProfit": _f(net),
                      "grossProfit": _f(mpl["grossProfit"])})

    expense_items = []
    section_names = {
        "costOfSales": _L(lang, "销售成本", "銷售成本", "Cost of sales"),
        "operatingExpenses": _L(lang, "经营费用", "經營費用", "Operating expenses"),
        "financeCosts": _L(lang, "财务费用", "財務費用", "Finance costs"),
        "taxExpense": _L(lang, "税项", "稅項", "Tax expense"),
    }
    for key, section_label in section_names.items():
        sec = pl[key]
        if key == "costOfSales" and not sec["items"] and abs(_d(sec["total"])) >= Decimal("0.005"):
            expense_items.append({"section": key, "label": section_label,
                                  "sectionLabel": section_label,
                                  "accountCode": None, "amount": _f(sec["total"])})
        for item in sec["items"]:
            expense_items.append({"section": key, "label": item["accountName"],
                                  "sectionLabel": section_label,
                                  "accountCode": item["accountCode"],
                                  "fsLineItem": item.get("fsLineItem"),
                                  "amount": _f(item["amount"])})

    bs_items = bs["assets"]["items"] + bs["liabilities"]["items"]
    cash = sum((_d(x["amount"]) for x in bs["assets"]["items"]
                if x.get("fsLineItem") in ("CASH", "CASH_EQUIVALENTS")), Decimal(0))
    receivables = sum((_d(x["amount"]) for x in bs["assets"]["items"]
                       if x.get("fsLineItem") == "TRADE_RECEIVABLES"), Decimal(0))
    payables = sum((_d(x["amount"]) for x in bs["liabilities"]["items"]
                    if x.get("fsLineItem") == "TRADE_PAYABLES"), Decimal(0))
    revenue, expenses, net = _pl_kpis(pl)
    ccy = str(entity.get("functional_currency") or entity.get("functionalCurrency") or "HKD")

    pnl_expected = (_d(pl["grossProfit"]) + _d(pl["otherIncome"]["total"])
                    + _d(pl["otherGains"]["total"]) - _d(pl["operatingExpenses"]["total"])
                    - _d(pl["financeCosts"]["total"]) - _d(pl["taxExpense"]["total"]))
    checks = [
        _check("entries", _L(lang, "期间分录借贷", "期間分錄借貸", "Entry debits and credits"),
               unbalanced_count == 0, sum((_d(x["difference"]) for x in unbalanced), Decimal(0)),
               _L(lang, f"发现 {unbalanced_count} 条不平衡分录", f"發現 {unbalanced_count} 條不平衡分錄",
                  f"{unbalanced_count} unbalanced entries found") if unbalanced_count else ""),
        _check("trial_balance", _L(lang, "试算平衡", "試算平衡", "Trial balance"),
               tb["balanced"], tb["difference"]),
        _check("pnl", _L(lang, "损益表勾稽", "損益表勾稽", "Profit or loss reconciliation"),
               abs(net - pnl_expected) < TOLERANCE, net - pnl_expected),
        _check("balance_sheet", _L(lang, "资产负债表勾稽", "資產負債表勾稽", "Balance sheet reconciliation"),
               bs["check"]["balanced"], bs["check"]["difference"]),
        _check("cash", _L(lang, "期末现金勾稽", "期末現金勾稽", "Closing cash reconciliation"),
               abs(_d(cf.get("closingCash")) - cash) < TOLERANCE, _d(cf.get("closingCash")) - cash,
               _L(lang, "现金流量表期末现金减资产负债表现金", "現金流量表期末現金減資產負債表現金",
                  "Cash-flow closing cash less balance-sheet cash")),
        _check("trend", _L(lang, "月度趋势与本期损益", "月度趨勢與本期損益", "Monthly trend to period profit or loss"),
               abs(sum((_d(x["netProfit"]) for x in trend), Decimal(0)) - net) < TOLERANCE,
               sum((_d(x["netProfit"]) for x in trend), Decimal(0)) - net),
    ]
    if cf.get("netProfitReported") is not None and abs(_d(cf.get("netProfitReported")) - net) >= TOLERANCE:
        checks.append(_check("cash_profit", _L(lang, "现金流本期净利", "現金流本期淨利", "Cash-flow reported profit"),
                             False, _d(cf.get("netProfitReported")) - net))
    unclassified = sum((_d(x["amount"]) for x in (cf.get("workingCapital") or [])
                        if "未归类" in str(x.get("label")) or "未歸類" in str(x.get("label"))
                        or "unclassified" in str(x.get("label")).lower()), Decimal(0))
    if abs(unclassified) >= Decimal("0.005"):
        checks.append(_check("cash_unclassified", _L(lang, "现金流未归类调整", "現金流未歸類調整", "Unclassified cash-flow adjustment"),
                             False, unclassified,
                             _L(lang, "现金流量表已单列其他（未归类），需人工复核",
                                "現金流量表已單列其他（未歸類），需人工覆核",
                                "Other (unclassified) is separately presented in cash flow and requires review")))

    def aging_view(data, side):
        return {"side": side, "byCurrency": data["byCurrency"], "items": data["items"],
                "totalFunctional": _f(sum((_d(x["functionalHkd"]) for x in data["byCurrency"]), Decimal(0))),
                "note": _L(lang, "外币账龄按币种分列；功能货币汇总取折算列之和，不直接相加原币。",
                                 "外幣賬齡按幣種分列；功能貨幣匯總取折算列之和，不直接相加原幣。",
                                 "Foreign-currency aging is presented by currency; functional-currency totals sum translated amounts rather than original currencies."),
                "basis": _L(lang, "未结单据日期不晚于期末；未结金额按系统当前核销记录计算，不是历史核销状态还原。",
                            "未結單據日期不晚於期末；未結金額按系統當前核銷記錄計算，不是歷史核銷狀態還原。",
                            "Open documents are dated on or before period end; outstanding amounts use current settlement records, not a reconstruction of historical settlement status.")}

    report = {
        "report": "LtBooks Financial Analysis Ver1.0", "version": "1.0", "lang": lang,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "entity": {"id": entity_id, "name": entity.get("entity_name") or entity.get("name") or "",
                   "legalName": entity.get("legal_name") or entity.get("legalName"),
                   "currency": ccy, "framework": entity.get("reporting_framework") or entity.get("reportingFramework")},
        "period": p,
        "data": {"entryCount": entry_count, "hasPeriodEntries": entry_count > 0,
                 "unbalancedEntryCount": unbalanced_count, "unbalancedEntries": unbalanced},
        "kpis": {"revenue": _f(revenue), "costOfSales": _f(pl["costOfSales"]["total"]),
                 "grossProfit": _f(pl["grossProfit"]), "expenses": _f(expenses),
                 "profitBeforeTax": _f(pl["profitBeforeTax"]), "netProfit": _f(net),
                 "netMargin": (float((net / revenue * 100).quantize(Decimal("0.01"))) if revenue else None),
                 "assets": _f(bs["assets"]["total"]), "liabilities": _f(bs["liabilities"]["total"]),
                 "equity": _f(bs["equity"]["total"]), "cash": _f(cash),
                 "receivables": _f(receivables), "payables": _f(payables),
                 "operatingCashFlow": _f(cf.get("operating")), "netCashChange": _f(cf.get("netChange"))},
        "monthlyTrend": trend, "expenseBreakdown": expense_items,
        "receivablesAging": aging_view(ar, "receivable"), "payablesAging": aging_view(ap, "payable"),
        "statements": {"profitAndLoss": pl, "balanceSheet": bs, "cashFlow": cf, "trialBalance": tb},
        "checks": checks, "reconciled": all(x["ok"] for x in checks),
        "sources": [
            {"function": "core.reports.profit_and_loss", "start": d0, "end": d1},
            {"function": "core.reports.balance_sheet", "asOf": d1},
            {"function": "core.reports.cash_flow", "start": d0, "end": d1},
            {"function": "core.reports.trial_balance", "asOf": d1},
            {"function": "core.reports.aging", "asOf": d1, "sides": ["receivable", "payable"]},
            {"function": "journal_entries/journal_lines", "purpose": "entry debit/credit validation"},
        ],
        "currencyNote": _L(lang, f"金额单位为 {ccy}，除比率外均保留两位小数。",
                           f"金額單位為 {ccy}，除比率外均保留兩位小數。",
                           f"Amounts are in {ccy} and rounded to two decimals except ratios."),
        "disclaimer": _L(lang, "本报告由确定性报表生成，需人工复核。", "本報告由確定性報表生成，需人工覆核。",
                           "This report is generated from deterministic statements and requires human review."),
    }
    _attach_narrative(report, bool(use_ai))
    return report


# ---------------------------------------------------------------- 图表与导出
def _font(size):
    from PIL import ImageFont
    candidates = ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _chart_files(report, directory):
    from PIL import Image, ImageDraw

    directory = Path(directory)
    font, small = _font(24), _font(18)
    title = _font(30)
    trend_path = directory / "trend.png"
    image = Image.new("RGB", (1400, 620), "white")
    draw = ImageDraw.Draw(image)
    lang = report["lang"]
    draw.text((35, 20), _L(lang, "收入、费用与净利月度趋势", "收入、費用與淨利月度趨勢", "Monthly revenue, expenses and net profit"), fill="#152238", font=title)
    rows = report["monthlyTrend"]
    left, top, right, bottom = 105, 90, 1360, 525
    values = [_d(x[k]) for x in rows for k in ("revenue", "expenses", "netProfit")]
    low, high = min(values + [Decimal(0)]), max(values + [Decimal(0)])
    if high == low:
        high = low + Decimal(1)
    pad = (high - low) * Decimal("0.08")
    low, high = low - pad, high + pad

    def y(value):
        return bottom - float((_d(value) - low) / (high - low)) * (bottom - top)

    for i in range(5):
        yy = top + (bottom - top) * i / 4
        value = high - (high - low) * Decimal(str(i / 4))
        draw.line((left, yy, right, yy), fill="#e5eaf0", width=1)
        draw.text((12, yy - 10), f"{float(value):,.0f}", fill="#667085", font=small)
    zero_y = y(0)
    draw.line((left, zero_y, right, zero_y), fill="#8b95a5", width=2)
    count = max(1, len(rows))

    def x(index):
        return left + (right - left) * (index + 0.5) / count

    series = (("revenue", _L(lang, "收入", "收入", "Revenue"), "#2457f5"),
              ("expenses", _L(lang, "费用", "費用", "Expenses"), "#b45309"),
              ("netProfit", _L(lang, "净利", "淨利", "Net profit"), "#0f766e"))
    for sindex, (key, label, color) in enumerate(series):
        points = [(x(i), y(row[key])) for i, row in enumerate(rows)]
        if len(points) > 1:
            draw.line(points, fill=color, width=4)
        for px, py in points:
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=color)
        lx = 60 + sindex * 280
        draw.line((lx, 575, lx + 35, 575), fill=color, width=5)
        draw.text((lx + 45, 562), label, fill="#344054", font=font)
    if rows:
        step = max(1, (len(rows) + 7) // 8)
        for i, row in enumerate(rows):
            if i % step == 0 or i == len(rows) - 1:
                label = row["period"]
                draw.text((x(i) - 34, bottom + 12), label, fill="#667085", font=small)
    image.save(trend_path, "PNG")

    expense_path = directory / "expenses.png"
    image = Image.new("RGB", (1100, 650), "white")
    draw = ImageDraw.Draw(image)
    draw.text((35, 20), _L(lang, "成本费用结构", "成本費用結構", "Cost and expense composition"), fill="#152238", font=title)
    positives = sorted((x for x in report["expenseBreakdown"] if _d(x["amount"]) > 0),
                       key=lambda x: _d(x["amount"]), reverse=True)
    if len(positives) > 8:
        rest = sum((_d(x["amount"]) for x in positives[7:]), Decimal(0))
        positives = positives[:7] + [{"label": _L(lang, "其他", "其他", "Other"), "amount": _f(rest)}]
    total = sum((_d(x["amount"]) for x in positives), Decimal(0))
    palette = ("#2457f5", "#0c7b7a", "#b45309", "#64748b", "#38bdf8", "#8b5cf6", "#e11d48", "#16a34a")
    if total > 0:
        angle = -90.0
        for i, item in enumerate(positives):
            extent = float(_d(item["amount"]) / total) * 360
            color = palette[i % len(palette)]
            draw.pieslice((45, 100, 545, 600), angle, angle + extent, fill=color)
            angle += extent
        draw.ellipse((175, 230, 415, 470), fill="white")
        draw.text((205, 320), _money(total), fill="#152238", font=font)
        for i, item in enumerate(positives):
            yy = 115 + i * 61
            color = palette[i % len(palette)]
            draw.rectangle((610, yy + 5, 635, yy + 30), fill=color)
            label = str(item["label"])
            if len(label) > 22:
                label = label[:21] + "…"
            draw.text((650, yy), label, fill="#344054", font=font)
            draw.text((650, yy + 29), f"{_money(item['amount'])}  {float(_d(item['amount']) / total * 100):.1f}%",
                      fill="#667085", font=small)
    else:
        draw.text((80, 250), _L(lang, "本期间没有正数成本费用可绘制结构图", "本期間沒有正數成本費用可繪製結構圖",
                                  "No positive cost or expense values are available for this chart"), fill="#667085", font=font)
    image.save(expense_path, "PNG")
    return {"trend": trend_path, "expenses": expense_path}


def _table_html(headers, rows, numeric=()):
    out = ["<table><thead><tr>"]
    for i, value in enumerate(headers):
        out.append(f'<th class="{"num" if i in numeric else ""}">{html.escape(str(value))}</th>')
    out.append("</tr></thead><tbody>")
    for row in rows:
        classes = ""
        if row and isinstance(row[0], str) and row[0].startswith("**"):
            row = [str(row[0])[2:]] + list(row[1:])
            classes = ' class="subtotal"'
        out.append(f"<tr{classes}>")
        for i, value in enumerate(row):
            out.append(f'<td class="{"num" if i in numeric else ""}">{html.escape("—" if value is None else str(value))}</td>')
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _statement_tables(report):
    """导出与 DOCX 共用的完整报表行，避免两种文件口径不同。"""
    lang, ccy = report["lang"], report["entity"]["currency"]
    L = lambda cn, hk, en: _L(lang, cn, hk, en)
    m = lambda value: _money(value)
    pl = report["statements"]["profitAndLoss"]
    pnl_rows = []
    for key, label in (("revenue", L("收入", "收入", "Revenue")),
                       ("costOfSales", L("销售成本", "銷售成本", "Cost of sales")),
                       ("otherIncome", L("其他收入", "其他收入", "Other income")),
                       ("otherGains", L("其他收益／（亏损）", "其他收益／（虧損）", "Other gains / (losses)")),
                       ("operatingExpenses", L("经营费用", "經營費用", "Operating expenses")),
                       ("financeCosts", L("财务费用", "財務費用", "Finance costs")),
                       ("taxExpense", L("税项", "稅項", "Tax expense"))):
        sec = pl[key]
        pnl_rows.append(["**" + label, "", m(sec["total"])])
        for item in sec["items"]:
            pnl_rows.append([item["accountName"], item["accountCode"], m(item["amount"])])
        if key == "costOfSales":
            pnl_rows.append(["**" + L("毛利", "毛利", "Gross profit"), "", m(pl["grossProfit"])])
        if key == "financeCosts":
            pnl_rows.append(["**" + L("除税前溢利", "除稅前溢利", "Profit before tax"), "", m(pl["profitBeforeTax"])])
    pnl_rows.append(["**" + L("本期净利／（亏损）", "本期淨利／（虧損）", "Net profit / (loss)"), "", m(pl["netProfit"])])

    bs = report["statements"]["balanceSheet"]
    bs_rows = []
    for key, label in (("assets", L("资产", "資產", "Assets")),
                       ("liabilities", L("负债", "負債", "Liabilities")),
                       ("equity", L("权益", "權益", "Equity"))):
        sec = bs[key]
        bs_rows.append(["**" + label, "", m(sec["total"])])
        for item in sec["items"]:
            bs_rows.append([item["accountName"], item["accountCode"], m(item["amount"])])
        if key == "equity":
            bs_rows.append([L("累计损益（截至期末）", "累計損益（截至期末）", "Accumulated profit or loss at period end"), "", m(sec.get("currentYearProfit"))])
    bs_rows.append(["**" + L("勾稽差额", "勾稽差額", "Reconciliation difference"), "",
                    m(bs["check"]["difference"])])

    cf = report["statements"]["cashFlow"]
    cf_rows = [[L("期初现金及现金等价物", "期初現金及現金等價物", "Opening cash and cash equivalents"), m(cf.get("openingCash"))],
               [L("本期净利／（亏损，现金流口径）", "本期淨利／（虧損，現金流口徑）", "Net profit / (loss), cash-flow basis"), m(cf.get("netProfit"))]]
    if abs(_d(cf.get("openingEntryCash"))) >= Decimal("0.005"):
        cf_rows.append([L("期内期初分录现金变动（不计入经营活动）", "期內期初分錄現金變動（不計入經營活動）",
                          "Cash from opening entries in the period (excluded from operating activities)"),
                        m(cf.get("openingEntryCash"))])
    for item in cf.get("nonCash") or []:
        cf_rows.append([L("非现金调整：", "非現金調整：", "Non-cash adjustment: ") + str(item.get("account")), m(item["amount"])])
    for item in cf.get("workingCapital") or []:
        cf_rows.append([L("营运资金及调整：", "營運資金及調整：", "Working capital and adjustments: ") + str(item.get("label")), m(item["amount"])])
    for key, label in (("operating", L("经营活动现金净额", "經營活動現金淨額", "Net cash from operating activities")),
                       ("investing", L("投资活动现金净额", "投資活動現金淨額", "Net cash from investing activities")),
                       ("financing", L("融资活动现金净额", "融資活動現金淨額", "Net cash from financing activities")),
                       ("netChange", L("现金净变动", "現金淨變動", "Net cash movement")),
                       ("closingCash", L("期末现金及现金等价物", "期末現金及現金等價物", "Closing cash and cash equivalents"))):
        cf_rows.append(["**" + label, m(cf.get(key))])

    tb = report["statements"]["trialBalance"]
    tb_rows = [[x["accountCode"], x["accountName"], m(x["debit"]), m(x["credit"]), m(x["balance"])]
               for x in tb["accounts"]]
    tb_rows.append(["**" + L("合计", "合計", "Total"), "", m(tb["totalDebit"]), m(tb["totalCredit"]), m(tb["difference"])])
    return pnl_rows, bs_rows, cf_rows, tb_rows


def _report_html(report, charts):
    lang, p, k = report["lang"], report["period"], report["kpis"]
    L = lambda cn, hk, en: _L(lang, cn, hk, en)
    e = lambda value: html.escape(str(value if value is not None else "—"))
    title = L("财务分析报告", "財務分析報告", "Financial Analysis Report")
    css = """
    @page { size:A4; margin:16mm 14mm 18mm; @bottom-center { content: counter(page) " / " counter(pages); font-size:8pt; color:#667085; vertical-align:bottom; padding-bottom:6mm; } }
    * { box-sizing:border-box } body { font-family:'WenQuanYi Zen Hei','Noto Sans CJK SC',sans-serif; font-size:9pt; color:#172033; line-height:1.5 }
    h1 { font-size:22pt; margin:0 0 4mm } h2 { font-size:14pt; margin:9mm 0 3mm; border-bottom:1px solid #98a2b3; padding-bottom:2mm }
    h3 { font-size:11pt; margin:6mm 0 2mm } .meta,.note { color:#475467; font-size:8.5pt } .notice { background:#f2f4f7; padding:3mm; margin:4mm 0 }
    table { width:100%; border-collapse:collapse; margin:3mm 0 5mm; page-break-inside:auto } tr { page-break-inside:avoid }
    th { text-align:left; background:#eef2f6; padding:2mm; border-bottom:1px solid #98a2b3 } td { padding:1.7mm 2mm; border-bottom:1px solid #e4e7ec; vertical-align:top }
    .num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap } .subtotal td { font-weight:700; background:#f8fafc }
    .kpis td:first-child { color:#475467 } .kpis td:last-child { text-align:right; font-size:11pt; font-weight:700 }
    img { width:100%; max-height:155mm; object-fit:contain; margin:2mm 0 } .bad { color:#a11010; font-weight:700 } .ok { color:#086b55 }
    .page-break { page-break-before:always } ul { padding-left:6mm } .aging-note { font-size:8pt; color:#667085 }
    .checks td { padding:1.5mm 2mm }
    """
    parts = [f"<!doctype html><html lang='{e(lang)}'><head><meta charset='utf-8'><style>{css}</style></head><body>",
             f"<h1>{e(title)}</h1><div><b>{e(report['entity']['name'])}</b></div>",
             f"<div class='meta'>LtBooks Ver1.0 · {e(p['start'])} – {e(p['end'])} · {e(report['entity']['currency'])}</div>",
             f"<div class='meta'>{e(report['generatedAt'])} · {e(report['currencyNote'])}</div>",
             f"<h2>{e(L('管理摘要', '管理摘要', 'Executive summary'))}</h2><p><b>{e(report['analysis']['summary'])}</b></p>"]
    for text in report["analysis"]["paragraphs"]:
        parts.append(f"<p>{e(text)}</p>")
    parts += [f"<div class='notice'>{e(report['analysis']['notice'])}<br>{e(report['analysis']['sourceNote'])}</div>"]
    kpi_rows = [(L("收入", "收入", "Revenue"), k["revenue"]), (L("毛利", "毛利", "Gross profit"), k["grossProfit"]),
                (L("费用", "費用", "Expenses"), k["expenses"]), (L("净利", "淨利", "Net profit"), k["netProfit"]),
                (L("净利率", "淨利率", "Net margin"), None), (L("期末现金", "期末現金", "Closing cash"), k["cash"]),
                (L("应收账款", "應收賬款", "Trade receivables"), k["receivables"]),
                (L("应付账款", "應付賬款", "Trade payables"), k["payables"]),
                (L("经营活动现金流", "經營活動現金流", "Operating cash flow"), k["operatingCashFlow"])]
    parts.append(_table_html([L("关键指标", "關鍵指標", "Key metric"), L("金额", "金額", "Amount")],
                             [[label, (f"{value:.2f}%" if label in (L("净利率", "淨利率", "Net margin"),) and value is not None else _money(value))]
                              for label, value in [(x[0], k["netMargin"] if x[1] is None and x[0] == L("净利率", "淨利率", "Net margin") else x[1]) for x in kpi_rows]], (1,)))
    parts.append(f"<div class='page-break'></div><h2>{e(L('趋势与费用结构', '趨勢與費用結構', 'Trend and expense composition'))}</h2>")
    parts.append(f"<img src='{e(charts['trend'].name)}'><img src='{e(charts['expenses'].name)}'>")
    trend_rows = [[x["period"], _money(x["revenue"]), _money(x["expenses"]), _money(x["netProfit"])] for x in report["monthlyTrend"]]
    parts.append(f"<h3>{e(L('月度趋势明细', '月度趨勢明細', 'Monthly trend detail'))}</h3>")
    parts.append(_table_html([L("月份", "月份", "Month"), L("收入", "收入", "Revenue"), L("费用", "費用", "Expenses"), L("净利", "淨利", "Net profit")], trend_rows, (1, 2, 3)))
    expense_rows = [[x.get("sectionLabel") or x["section"], x["label"], x.get("accountCode") or "", _money(x["amount"])] for x in report["expenseBreakdown"]]
    parts.append(_table_html([L("类别", "類別", "Section"), L("项目", "項目", "Item"), L("科目", "科目", "Account"), L("金额", "金額", "Amount")], expense_rows, (3,)))
    parts.append(f"<div class='page-break'></div><h2>{e(L('应收应付与现金', '應收應付與現金', 'Receivables, payables and cash'))}</h2>")
    for data, heading in ((report["receivablesAging"], L("应收账龄", "應收賬齡", "Receivables aging")),
                          (report["payablesAging"], L("应付账龄", "應付賬齡", "Payables aging"))):
        rows = [[x["currency"], _money(x["0-30"]), _money(x["31-60"]), _money(x["61-90"]), _money(x["90+"]), _money(x["total"]), _money(x["functionalHkd"])] for x in data["byCurrency"]]
        parts.append(f"<h3>{e(heading)}</h3>")
        parts.append(_table_html([L("币种", "幣種", "Currency"), "0–30", "31–60", "61–90", "90+", L("原币合计", "原幣合計", "Original total"), L("功能货币", "功能貨幣", "Functional currency")], rows, (1, 2, 3, 4, 5, 6)))
        parts.append(f"<div class='aging-note'>{e(data['basis'])} {e(data.get('note'))}</div>")
    cash_rows = [[L("资产负债表现金", "資產負債表現金", "Balance-sheet cash"), _money(k["cash"])],
                 [L("现金流量表期末现金", "現金流量表期末現金", "Cash-flow closing cash"), _money(report["statements"]["cashFlow"].get("closingCash"))],
                 [L("现金净变动", "現金淨變動", "Net cash movement"), _money(k["netCashChange"])]]
    parts.append(_table_html([L("现金项目", "現金項目", "Cash item"), L("金额", "金額", "Amount")], cash_rows, (1,)))
    parts.append(f"<h2>{e(L('勾稽与异常披露', '勾稽與異常披露', 'Reconciliations and exceptions'))}</h2>")
    check_rows = [[x["label"], L("通过", "通過", "PASS") if x["ok"] else L("异常", "異常", "EXCEPTION"), _money(x["difference"]), x["detail"]] for x in report["checks"]]
    parts.append("<div class='checks'>")
    parts.append(_table_html([L("校验", "校驗", "Check"), L("结果", "結果", "Result"), L("差额", "差額", "Difference"), L("说明", "說明", "Detail")], check_rows, (2,)))
    parts.append("</div>")
    if report["data"]["unbalancedEntries"]:
        parts.append(_table_html([L("凭证", "憑證", "Entry"), L("日期", "日期", "Date"), L("借方", "借方", "Debit"), L("贷方", "貸方", "Credit"), L("差额", "差額", "Difference")],
                                 [[x["entryNo"], x["entryDate"], _money(x["debit"]), _money(x["credit"]), _money(x["difference"])] for x in report["data"]["unbalancedEntries"]], (2, 3, 4)))
    pnl_rows, bs_rows, cf_rows, tb_rows = _statement_tables(report)
    statements = ((L("损益及其他全面收益表", "損益及其他全面收益表", "Statement of Profit or Loss and Other Comprehensive Income"),
                   [L("项目", "項目", "Item"), L("科目", "科目", "Account"), L("金额", "金額", "Amount")], pnl_rows, (2,)),
                  (L("财务状况表", "財務狀況表", "Statement of Financial Position"),
                   [L("项目", "項目", "Item"), L("科目", "科目", "Account"), L("金额", "金額", "Amount")], bs_rows, (2,)),
                  (L("现金流量表（间接法）", "現金流量表（間接法）", "Statement of Cash Flows (Indirect Method)"),
                   [L("项目", "項目", "Item"), L("金额", "金額", "Amount")], cf_rows, (1,)),
                  (L("试算平衡表", "試算平衡表", "Trial Balance"),
                   [L("科目", "科目", "Account"), L("名称", "名稱", "Name"), L("借方", "借方", "Debit"), L("贷方", "貸方", "Credit"), L("余额", "餘額", "Balance")], tb_rows, (2, 3, 4)))
    for heading, headers, rows, nums in statements:
        parts.append(f"<div class='page-break'></div><h2>{e(heading)}</h2>")
        parts.append(_table_html(headers, rows, nums))
    parts.append(f"<div class='notice'>{e(report['disclaimer'])}</div></body></html>")
    return "".join(parts)


def _docx(report, charts, path):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt

    lang, p, k = report["lang"], report["period"], report["kpis"]
    L = lambda cn, hk, en: _L(lang, cn, hk, en)
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.65)
    section.left_margin = section.right_margin = Inches(0.65)
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(9)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    def add_table(headers, rows, numeric=()):
        table = document.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        for i, value in enumerate(headers):
            table.rows[0].cells[i].text = str(value)
        for row in rows:
            cells = table.add_row().cells
            for i, value in enumerate(row):
                text = str(value)
                if i == 0 and text.startswith("**"):
                    text = text[2:]
                cells[i].text = text
                if i in numeric:
                    cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(7.5)
                        run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "Microsoft YaHei")
        return table

    document.add_heading(L("财务分析报告", "財務分析報告", "Financial Analysis Report"), 0)
    document.add_paragraph(report["entity"]["name"])
    document.add_paragraph(f"LtBooks Ver1.0 · {p['start']} – {p['end']} · {report['entity']['currency']}")
    document.add_paragraph(report["currencyNote"])
    document.add_heading(L("管理摘要", "管理摘要", "Executive summary"), 1)
    document.add_paragraph(report["analysis"]["summary"])
    for text in report["analysis"]["paragraphs"]:
        document.add_paragraph(text)
    document.add_paragraph(report["analysis"]["notice"])
    document.add_paragraph(report["analysis"]["sourceNote"])
    kpi_rows = [[label, _money(value)] for label, value in
                ((L("收入", "收入", "Revenue"), k["revenue"]), (L("毛利", "毛利", "Gross profit"), k["grossProfit"]),
                 (L("费用", "費用", "Expenses"), k["expenses"]), (L("净利", "淨利", "Net profit"), k["netProfit"]),
                 (L("期末现金", "期末現金", "Closing cash"), k["cash"]),
                 (L("应收账款", "應收賬款", "Trade receivables"), k["receivables"]),
                 (L("应付账款", "應付賬款", "Trade payables"), k["payables"]),
                 (L("经营活动现金流", "經營活動現金流", "Operating cash flow"), k["operatingCashFlow"]))]
    if k["netMargin"] is not None:
        kpi_rows.insert(4, [L("净利率", "淨利率", "Net margin"), f"{k['netMargin']:.2f}%"])
    add_table([L("关键指标", "關鍵指標", "Key metric"), L("数值", "數值", "Value")], kpi_rows, (1,))
    document.add_page_break()
    document.add_heading(L("趋势与费用结构", "趨勢與費用結構", "Trend and expense composition"), 1)
    document.add_picture(str(charts["trend"]), width=Inches(6.8))
    document.add_picture(str(charts["expenses"]), width=Inches(6.8))
    add_table([L("月份", "月份", "Month"), L("收入", "收入", "Revenue"), L("费用", "費用", "Expenses"), L("净利", "淨利", "Net profit")],
              [[x["period"], _money(x["revenue"]), _money(x["expenses"]), _money(x["netProfit"])] for x in report["monthlyTrend"]], (1, 2, 3))
    add_table([L("类别", "類別", "Section"), L("项目", "項目", "Item"), L("科目", "科目", "Account"), L("金额", "金額", "Amount")],
              [[x.get("sectionLabel") or x["section"], x["label"], x.get("accountCode") or "", _money(x["amount"])] for x in report["expenseBreakdown"]], (3,))
    document.add_page_break()
    document.add_heading(L("应收应付与现金", "應收應付與現金", "Receivables, payables and cash"), 1)
    for data, heading in ((report["receivablesAging"], L("应收账龄", "應收賬齡", "Receivables aging")),
                          (report["payablesAging"], L("应付账龄", "應付賬齡", "Payables aging"))):
        document.add_heading(heading, 2)
        add_table([L("币种", "幣種", "Currency"), "0–30", "31–60", "61–90", "90+", L("原币合计", "原幣合計", "Original total"), L("功能货币", "功能貨幣", "Functional currency")],
                  [[x["currency"], _money(x["0-30"]), _money(x["31-60"]), _money(x["61-90"]), _money(x["90+"]), _money(x["total"]), _money(x["functionalHkd"])] for x in data["byCurrency"]], (1, 2, 3, 4, 5, 6))
        document.add_paragraph(data["basis"] + " " + str(data.get("note") or ""))
    document.add_heading(L("勾稽与异常披露", "勾稽與異常披露", "Reconciliations and exceptions"), 1)
    add_table([L("校验", "校驗", "Check"), L("结果", "結果", "Result"), L("差额", "差額", "Difference"), L("说明", "說明", "Detail")],
              [[x["label"], L("通过", "通過", "PASS") if x["ok"] else L("异常", "異常", "EXCEPTION"), _money(x["difference"]), x["detail"]] for x in report["checks"]], (2,))
    if report["data"]["unbalancedEntries"]:
        add_table([L("凭证", "憑證", "Entry"), L("日期", "日期", "Date"), L("借方", "借方", "Debit"), L("贷方", "貸方", "Credit"), L("差额", "差額", "Difference")],
                  [[x["entryNo"], x["entryDate"], _money(x["debit"]), _money(x["credit"]), _money(x["difference"])] for x in report["data"]["unbalancedEntries"]], (2, 3, 4))
    pnl_rows, bs_rows, cf_rows, tb_rows = _statement_tables(report)
    for heading, headers, rows, nums in ((L("损益及其他全面收益表", "損益及其他全面收益表", "Statement of Profit or Loss and Other Comprehensive Income"),
                                          [L("项目", "項目", "Item"), L("科目", "科目", "Account"), L("金额", "金額", "Amount")], pnl_rows, (2,)),
                                         (L("财务状况表", "財務狀況表", "Statement of Financial Position"),
                                          [L("项目", "項目", "Item"), L("科目", "科目", "Account"), L("金额", "金額", "Amount")], bs_rows, (2,)),
                                         (L("现金流量表（间接法）", "現金流量表（間接法）", "Statement of Cash Flows (Indirect Method)"),
                                          [L("项目", "項目", "Item"), L("金额", "金額", "Amount")], cf_rows, (1,)),
                                         (L("试算平衡表", "試算平衡表", "Trial Balance"),
                                          [L("科目", "科目", "Account"), L("名称", "名稱", "Name"), L("借方", "借方", "Debit"), L("贷方", "貸方", "Credit"), L("余额", "餘額", "Balance")], tb_rows, (2, 3, 4))):
        document.add_page_break()
        document.add_heading(heading, 1)
        add_table(headers, rows, nums)
    document.add_paragraph(report["disclaimer"])
    document.save(path)


def export_report(report, fmt, directory):
    """导出真正的 PDF 或 Office Open XML DOCX，返回新文件路径。"""
    fmt = str(fmt or "").lower()
    if fmt not in ("pdf", "docx"):
        raise ValueError("format 只能是 pdf 或 docx")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # audit_log.object_id 最长 64 字符；完整文件名必须连 DOCX 后缀也留有余量。
    name = (f"LtBooks-FA-{report['period']['start']}_"
            f"{report['period']['end']}-{report['lang']}-{uuid.uuid4().hex[:10]}.{fmt}")
    path = directory / name
    with tempfile.TemporaryDirectory(prefix="ledu-analysis-") as tmp:
        charts = _chart_files(report, tmp)
        if fmt == "pdf":
            from weasyprint import HTML
            HTML(string=_report_html(report, charts), base_url=tmp).write_pdf(str(path))
        else:
            _docx(report, charts, path)
    return path
