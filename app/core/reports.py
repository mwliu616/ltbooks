# LtBooks — core/reports.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""报表聚合：按 fs_line_item + normal_balance + contra_reclass_target。"""
import re
from contextvars import ContextVar

from .db import query, query_one
from .money import dec, sum_money

# 报表口径：已过账（含被冲销的原分录）。草稿不进报表，误录靠复核拦截。
POSTED = "e.status IN ('posted','reversed')"
# 期初分录（source_type='opening'）是把期初余额灌进账簿，不是当期业务：
# 现金流量表里算作「期初现金」，不计入经营活动/融资活动，否则会出现
# 「股东借款平白产生 68,929.87 融资流入」这种假象。
NOT_OPENING = "(e.source_type IS NULL OR e.source_type <> 'opening')"


# ---------------------------------------------------------------- 语言
# 报表里的科目名要跟着输出语言走：英文 PDF 不能出现中文科目名。
# 语言在请求入口用 set_report_lang() 设定，缺值一律回退到 account_name。
_REPORT_LANG = ContextVar("ltbooks_report_lang", default="en")


def _t(cn, hk, en):
    """报表内固定标签按当前输出语言取，避免中文表里混繁体、英文表里混中文。"""
    return {"zh_cn": cn, "zh_hk": hk, "en": en}.get(_REPORT_LANG.get(), en)


def set_report_lang(lang):
    # ContextVar 隔离并发请求；不能用进程级字符串，否则中英报告可能互相串语。
    _REPORT_LANG.set(lang if lang in ("en", "zh_cn", "zh_hk") else "en")


def _name_col(alias="a"):
    """按当前语言取科目名的 SQL 表达式。语言值已白名单校验，可直接内联。"""
    return (f"CASE '{_REPORT_LANG.get()}'"
            f" WHEN 'en' THEN COALESCE(NULLIF({alias}.name_en,''), {alias}.account_name)"
            f" WHEN 'zh_hk' THEN COALESCE(NULLIF({alias}.name_zh_hk,''), {alias}.account_name)"
            f" ELSE COALESCE(NULLIF({alias}.name_zh_cn,''), {alias}.account_name) END")


def _balances(entity_id, asof=None):
    extra = " AND e.entry_date <= %s" if asof else ""
    params = (entity_id, asof) if asof else (entity_id,)
    rows = query(
        f"""SELECT a.account_code, {_name_col()} AS account_name, a.category, a.fs_line_item,
                   a.normal_balance, a.contra_reclass_target,
                   COALESCE(SUM(l.debit),0) AS dr, COALESCE(SUM(l.credit),0) AS cr
              FROM journal_lines l
              JOIN journal_entries e ON e.entry_id = l.entry_id
              JOIN accounts a ON a.account_code = l.account_code AND a.entity_id = e.entity_id
             WHERE e.entity_id = %s AND {POSTED}{extra}
             GROUP BY a.account_code, {_name_col()}, a.category, a.fs_line_item,
                      a.normal_balance, a.contra_reclass_target
             ORDER BY a.account_code""",
        params,
    )
    out = []
    for r in rows:
        dr, cr = dec(r["dr"]), dec(r["cr"])
        out.append(dict(r, dr=dr, cr=cr, net=(dr - cr)))
    return out


def trial_balance(entity_id, asof=None):
    """试算平衡表：每个科目按**净额**列在一侧（与审计包口径一致）。

    早期版本把借方发生额与贷方发生额分别累加，同一个科目会同时出现在两栏，
    合计会比审计包大——审计的科目余额表是净借项/净贷项。这里改成净额。
    另保留 grossDebit/grossCredit，需要看发生额的场景（如账户类型摘要）不受影响。
    """
    rows = _balances(entity_id, asof)
    items, td, tc = [], dec(0), dec(0)
    for r in rows:
        net = r["net"]
        if net == 0:
            continue
        debit, credit = (net, dec(0)) if net > 0 else (dec(0), -net)
        td += debit
        tc += credit
        items.append({"accountCode": r["account_code"], "accountName": r["account_name"],
                      "category": r["category"], "fsLineItem": r["fs_line_item"],
                      "debit": float(debit), "credit": float(credit),
                      "grossDebit": float(r["dr"]), "grossCredit": float(r["cr"]),
                      "balance": float(net)})
    return {
        "accounts": items,
        "totalDebit": float(td), "totalCredit": float(tc),
        "balanced": td == tc, "difference": float(td - tc),
    }


def _signed(r, cat):
    return (-r["net"] if cat == "revenue" else r["net"])


OPEX_LINES = ("STAFF_COSTS", "OCCUPANCY", "PROFESSIONAL_FEES", "BANK_CHARGES",
              "TRAVEL", "ENTERTAINMENT", "ADMIN_EXPENSES", "DEPRECIATION",
              "AMORTISATION", "OPERATING_EXPENSES")


def profit_and_loss(entity_id, start=None, end=None):
    """损益及其他全面收益表（HKAS 1 格式）。

    分节：收入 → 销售成本 → 毛利 → 其他收入 → 其他收益/亏损
          → 经营费用 → 财务费用 → 除税前溢利 → 税项 → 本期溢利
    """
    if start or end:
        where, params = [], [entity_id]
        if start:
            where.append("AND e.entry_date >= %s"); params.append(start)   # 起期含当日
        if end:
            where.append("AND e.entry_date <= %s"); params.append(end)
        rows = query(
            f"""SELECT a.account_code, {_name_col()} AS account_name, a.category, a.fs_line_item,
                       a.normal_balance,
                       COALESCE(SUM(l.debit),0) AS dr, COALESCE(SUM(l.credit),0) AS cr
                  FROM journal_lines l
                  JOIN journal_entries e ON e.entry_id = l.entry_id
                  JOIN accounts a ON a.account_code = l.account_code AND a.entity_id = e.entity_id
                 WHERE e.entity_id = %s AND {POSTED} {' '.join(where)}
                 GROUP BY a.account_code, {_name_col()}, a.category, a.fs_line_item, a.normal_balance
                 ORDER BY a.account_code""", tuple(params))
        rows = [dict(r, dr=dec(r["dr"]), cr=dec(r["cr"]), net=(dec(r["dr"]) - dec(r["cr"]))) for r in rows]
    else:
        rows = _balances(entity_id)

    def section(label, predicate):
        items = []
        for r in rows:
            if not predicate(r):
                continue
            # 收入类正常为贷方；成本费用类正常为借方
            if r["category"] in ("revenue", "liability", "equity"):
                amt = -r["net"]
            else:
                amt = r["net"]
            if amt != 0:
                items.append({"accountCode": r["account_code"], "accountName": r["account_name"],
                              "fsLineItem": r["fs_line_item"], "amount": float(amt)})
        total = sum((dec(x["amount"]) for x in items), dec(0))
        return {"label": label, "items": items, "total": float(total)}

    revenue = section(_t("收入", "收入", "Revenue"), lambda r: r["category"] == "revenue"
                      and r["fs_line_item"] == "REVENUE"
                      or r["category"] == "revenue" and r["fs_line_item"] is None)
    other_income = section(_t("其他收入", "其他收入", "Other income"),
                           lambda r: r["fs_line_item"] == "OTHER_INCOME")
    fx = section(_t("其他收益／（亏损）", "其他收益／（虧損）", "Other gains / (losses)"),
                 lambda r: r["fs_line_item"] == "FX_GAIN_LOSS")
    cogs = section(_t("销售成本", "銷售成本", "Cost of sales"),
                   lambda r: r["category"] == "cogs")
    opex = section(_t("经营费用", "經營費用", "Operating expenses"),
                   lambda r: r["category"] == "expense" and r["fs_line_item"] in OPEX_LINES)
    finance = section(_t("财务费用", "財務費用", "Finance costs"),
                      lambda r: r["fs_line_item"] == "FINANCE_COSTS")
    tax = section(_t("税项", "稅項", "Tax expense"),
                  lambda r: r["fs_line_item"] == "TAX_EXPENSE")

    gross = dec(revenue["total"]) - dec(cogs["total"])
    pbt = (gross + dec(other_income["total"]) + dec(fx["total"])
           - dec(opex["total"]) - dec(finance["total"]))
    net = pbt - dec(tax["total"])

    return {
        "revenue": revenue,
        "costOfSales": cogs,
        "grossProfit": float(gross),
        "otherIncome": other_income,
        "otherGains": fx,
        "operatingExpenses": opex,
        "financeCosts": finance,
        "profitBeforeTax": float(pbt),
        "taxExpense": tax,
        "netProfit": float(net),
        "note": _t("按 HKAS 1 格式列报；税项按利得税计算表确认后入账，未确认前不预估",
                   "按 HKAS 1 格式列報；稅項按利得稅計算表確認後入帳，未確認前不預估",
                   "Presented under HKAS 1. Tax is recognised from the profits-tax computation; no unconfirmed tax estimate is accrued."),
    }


def _presentation_rows(rows, entity_id):
    """按正常余额方向取带符号金额，并把反向余额按 contra 目标重分类。

    关键点：重分类必须把金额**加到目标科目**上。若只把本行清零而不加，
    金额就会凭空消失，报表立刻不平（实测：差 60 与 2810 两次都是这个原因）。
    """
    out, reclass = [], {}
    for r in rows:
        debit_normal = r["normal_balance"] == "debit"
        signed = r["net"] if debit_normal else -r["net"]
        if signed < 0 and r["contra_reclass_target"]:
            reclass[r["contra_reclass_target"]] = (
                reclass.get(r["contra_reclass_target"], dec(0)) + (-signed))
            out.append(dict(r, amount=dec(0), reclassedTo=r["contra_reclass_target"]))
        else:
            out.append(dict(r, amount=signed, reclassedTo=None))
    # 把重分类金额并入目标科目
    by_code = {r["account_code"]: r for r in out}
    for target, amt in reclass.items():
        if target in by_code:
            by_code[target]["amount"] = by_code[target]["amount"] + amt
            by_code[target]["reclassifiedIn"] = by_code[target].get("reclassifiedIn", dec(0)) + amt
        else:
            info = query_one(
                f"SELECT {_name_col()} AS account_name, a.category, a.fs_line_item, a.normal_balance "
                "FROM accounts a WHERE a.entity_id=%s AND a.account_code=%s LIMIT 1",
                (entity_id, target))
            out.append({
                "account_code": target,
                "account_name": (info or {}).get(
                    "account_name", target + _t("（重分类）", "（重分類）", " (reclassification)")),
                "category": (info or {}).get("category"),
                "fs_line_item": (info or {}).get("fs_line_item"),
                "normal_balance": (info or {}).get("normal_balance", "credit"),
                "contra_reclass_target": None,
                "dr": dec(0), "cr": dec(0), "net": dec(0),
                "amount": amt, "reclassedTo": None, "reclassifiedIn": amt,
            })
    return out


def balance_sheet(entity_id, asof=None):
    rows = _presentation_rows(_balances(entity_id, asof), entity_id)

    def group(cat):
        items = [{"accountCode": r["account_code"], "accountName": r["account_name"],
                  "fsLineItem": r["fs_line_item"], "amount": float(r["amount"]),
                  "reclassedTo": r["reclassedTo"]}
                 for r in rows if r["category"] == cat and r["amount"] != 0]
        return {"items": items, "total": float(sum((dec(i["amount"]) for i in items), dec(0)))}

    assets, liabilities, equity = group("asset"), group("liability"), group("equity")
    pl = profit_and_loss(entity_id, None, asof)
    eq_total = dec(equity["total"]) + dec(pl["netProfit"])
    diff = dec(assets["total"]) - (dec(liabilities["total"]) + eq_total)
    return {
        "assets": assets, "liabilities": liabilities,
        "equity": dict(equity, currentYearProfit=pl["netProfit"], total=float(eq_total)),
        "check": {"assetsTotal": assets["total"],
                  "liabilitiesPlusEquity": float(dec(liabilities["total"]) + eq_total),
                  "difference": float(diff), "balanced": diff == 0},
    }


def cash_flow(entity_id, start=None, end=None):
    """现金流量表——间接法。

    结构照审计包的样子：期初现金 → 本期净利 → 非现金调整 →
    营运资金变动 → 经营活动净额 → 投资 → 融资 → 期末现金。

    间接法比「把现金分录按科目归类」好在能解释「赚了钱为什么现金没增加」，
    这也是 HKAS 7 允许并推荐的做法。
    """
    cash_accs = query("""SELECT account_code FROM accounts
                          WHERE entity_id=%s AND fs_line_item IN ('CASH','CASH_EQUIVALENTS')""",
                      (entity_id,))
    codes = [c["account_code"] for c in cash_accs]
    if not codes:
        # 即使科目表尚未配置现金科目，也返回完整结构，避免分析页和导出器取到空值。
        return {"openingCash": 0.0, "openingEntryCash": 0.0,
                "netProfit": 0.0, "netProfitReported": 0.0, "openingPlExcluded": 0.0,
                "nonCash": [], "nonCashTotal": 0.0, "workingCapital": [],
                "workingCapitalTotal": 0.0, "operating": 0.0, "investing": 0.0,
                "financing": 0.0, "netChange": 0.0, "closingCash": 0.0, "check": 0.0,
                "note": _t("无现金科目", "無現金科目", "No cash accounts are configured")}

    ph = ",".join(["%s"] * len(codes))

    def cash_net(where, args, exclude_opening=True):
        extra = f" AND {NOT_OPENING}" if exclude_opening else ""
        r = query_one(
            f"""SELECT COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
                  FROM journal_lines l JOIN journal_entries e ON e.entry_id=l.entry_id
                 WHERE e.entity_id=%s AND {POSTED} AND l.account_code IN ({ph}) {where}{extra}""",
            tuple([entity_id] + codes + args))
        return dec(r["dr"]) - dec(r["cr"]) if r else dec(0)

    # 期初现金只含期起日之前的全部现金分录，以及期起当日的 opening 初始化分录。
    # 期间内较后日期的 opening 分录单独列示：既不混入经营/融资，也不能计入历史期间的期初。
    opening = cash_net("AND e.entry_date < %s", [start], exclude_opening=False) if start else dec(0)
    if start:
        opening += cash_net("AND e.source_type='opening' AND e.entry_date = %s",
                            [start], exclude_opening=False)
    opening_scope, opening_args = ["AND e.source_type='opening'"], []
    if start:
        opening_scope.append("AND e.entry_date > %s"); opening_args.append(start)
    if end:
        opening_scope.append("AND e.entry_date <= %s"); opening_args.append(end)
    opening_entry_move = cash_net(" ".join(opening_scope), opening_args, exclude_opening=False)
    move = cash_net("AND e.entry_date >= %s AND e.entry_date <= %s", [start, end]) \
        if (start and end) else (cash_net("AND e.entry_date <= %s", [end]) if end else
                                 cash_net("AND e.entry_date >= %s", [start]) if start else
                                 cash_net("", []))
    closing = opening + opening_entry_move + move

    # 本期净利（用同一区间）。期初分录里的损益是「上年结转」，
    # 它没有现金流，也不属于本期经营结果，这里剔掉才能和经营现金流对得上。
    pl = profit_and_loss(entity_id, start, end)
    net_profit = dec(pl["netProfit"])
    opening_pl = dec(0)
    scope_o, args_o = [], []
    if start:
        scope_o.append("AND e.entry_date >= %s"); args_o.append(start)
    if end:
        scope_o.append("AND e.entry_date <= %s"); args_o.append(end)
    r_o = query_one(
        f"""SELECT COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
              FROM journal_lines l JOIN journal_entries e ON e.entry_id=l.entry_id
              JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=e.entity_id
             WHERE e.entity_id=%s AND {POSTED} AND e.source_type='opening'
               AND a.category IN ('revenue','cogs','expense') {' '.join(scope_o)}""",
        tuple([entity_id] + args_o))
    if r_o:
        opening_pl = dec(r_o["dr"]) - dec(r_o["cr"])      # 借方为正 = 净费用
    # opening_pl 是「借-贷」，正数代表净费用；利润里费用是负数，
    # 所以要加回去才是「不含期初结转的经营结果」
    net_profit_for_cf = net_profit + opening_pl

    # 非现金调整：折旧/摊销/减值（这些科目在利润表里扣了，但没动现金）
    where2, args2 = [], []
    if start:
        where2.append("AND e.entry_date >= %s"); args2.append(start)
    if end:
        where2.append("AND e.entry_date <= %s"); args2.append(end)
    nc = query(
        f"""SELECT a.account_code, {_name_col()} AS account_name, a.category, a.fs_line_item,
                   COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
              FROM journal_lines l JOIN journal_entries e ON e.entry_id=l.entry_id
              JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=e.entity_id
             WHERE e.entity_id=%s AND {POSTED} AND {NOT_OPENING} AND a.category IN ('expense','cogs')
               {' '.join(where2)}
             GROUP BY a.account_code, {_name_col()}, a.category, a.fs_line_item""",
        tuple([entity_id] + args2))
    # 非付现费用以科目表分类为主、三语名称为辅；不能把科目编码当名称匹配。
    NONCASH_HINT = ("折舊", "攤銷", "折旧", "摊销", "減值", "减值",
                    "depreciation", "amortisation", "amortization", "impairment")
    NONCASH_LINES = {"DEPRECIATION", "AMORTISATION", "AMORTIZATION", "IMPAIRMENT"}
    noncash = []
    for r in nc:
        name = str(r.get("account_name") or "")
        if r.get("fs_line_item") in NONCASH_LINES or any(h in name.lower() for h in NONCASH_HINT):
            amt = dec(r["dr"]) - dec(r["cr"])
            if amt:
                noncash.append({"account": r["account_code"], "accountName": name,
                                "amount": float(amt)})
    noncash_total = sum(dec(x["amount"]) for x in noncash)

    # 经营营运资金只含经营性流动项目；借款与租赁负债在融资活动中列示。
    # 同时兼容科目表历史 singular 与现行 plural 分类，避免整类科目静默漏算。
    WC_LABEL = {
        "TRADE_RECEIVABLES": _t("应收账款", "應收賬款", "Trade receivables"),
        "TRADE_PAYABLES": _t("应付账款", "應付賬款", "Trade payables"),
        "CONTRACT_ASSETS": _t("合同资产", "合同資產", "Contract assets"),
        "CONTRACT_LIABILITIES": _t("合同负债", "合同負債", "Contract liabilities"),
        "PREPAID": _t("预付费用", "預付費用", "Prepayments"),
        "PREPAYMENTS": _t("预付费用", "預付費用", "Prepayments"),
        "OTHER_CURRENT_ASSET": _t("其他流动资产", "其他流動資產", "Other current assets"),
        "OTHER_CURRENT_ASSETS": _t("其他流动资产", "其他流動資產", "Other current assets"),
        "CURRENT_ASSETS": _t("其他流动资产", "其他流動資產", "Other current assets"),
        "OTHER_CURRENT_LIABILITY": _t("其他流动负债", "其他流動負債", "Other current liabilities"),
        "OTHER_CURRENT_LIABILITIES": _t("其他流动负债", "其他流動負債", "Other current liabilities"),
        "CURRENT_LIABILITIES": _t("其他流动负债", "其他流動負債", "Other current liabilities"),
        "INVENTORY": _t("存货", "存貨", "Inventories"),
        "INVENTORIES": _t("存货", "存貨", "Inventories"),
        "OTHER_RECEIVABLE": _t("其他应收款", "其他應收款", "Other receivables"),
        "OTHER_RECEIVABLES": _t("其他应收款", "其他應收款", "Other receivables"),
        "OTHER_PAYABLE": _t("其他应付款", "其他應付款", "Other payables"),
        "OTHER_PAYABLES": _t("其他应付款", "其他應付款", "Other payables"),
        "ACCRUALS": _t("应计费用", "應計費用", "Accrued expenses"),
        "TAX_ASSETS": _t("可收回税项", "可收回稅項", "Tax recoverable"),
        "TAX_LIABILITIES": _t("应付税项", "應付稅項", "Tax liabilities"),
        "CREDIT_CARD": _t("信用卡", "信用卡", "Credit cards"),
    }
    wc_lines = tuple(WC_LABEL)
    wc_ph = ",".join(["%s"] * len(wc_lines))
    wc_rows = query(
        f"""SELECT a.account_code, a.category, a.fs_line_item,
                   COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
              FROM journal_lines l JOIN journal_entries e ON e.entry_id=l.entry_id
              JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=e.entity_id
             WHERE e.entity_id=%s AND {POSTED} AND {NOT_OPENING}
               AND a.fs_line_item IN ({wc_ph}) {' '.join(where2)}
             GROUP BY a.account_code, a.category, a.fs_line_item""",
        tuple([entity_id] + list(wc_lines) + args2))
    wc = {}
    for r in wc_rows:
        delta = dec(r["dr"]) - dec(r["cr"])
        label = WC_LABEL[r["fs_line_item"]]
        # delta 统一为「借方－贷方」：资产增加为正、负债增加为负。
        # 两者对经营现金的影响都取 -delta，不能把负债方向再反转一次。
        effect = -delta
        wc[label] = wc.get(label, dec(0)) + effect
    working_capital = [{"label": k, "amount": float(v)} for k, v in wc.items() if v]

    explained = net_profit_for_cf + noncash_total + sum((dec(x["amount"]) for x in working_capital), dec(0))

    # 投资 / 融资：按现金分录的另一方科目归类（与本表主体口径一致）
    inv = fin = dec(0)
    if codes:
        scope, sargs = [], []
        if start:
            scope.append("AND e.entry_date >= %s"); sargs.append(start)
        if end:
            scope.append("AND e.entry_date <= %s"); sargs.append(end)
        entries = query(
            f"""SELECT DISTINCT e.entry_id FROM journal_lines l
                  JOIN journal_entries e ON e.entry_id=l.entry_id
                 WHERE e.entity_id=%s AND {POSTED} AND {NOT_OPENING}
                   AND l.account_code IN ({ph}) {' '.join(scope)}""",
            tuple([entity_id] + codes + sargs))
        ids = [x["entry_id"] for x in entries]
        if ids:
            iph = ",".join(["%s"] * len(ids))
            lines = query(
                f"""SELECT l.entry_id, l.account_code, l.debit, l.credit, a.category, a.fs_line_item
                      FROM journal_lines l
                      JOIN journal_entries e ON e.entry_id=l.entry_id
                      LEFT JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=e.entity_id
                     WHERE e.entry_id IN ({iph})""", tuple(ids))
            by_entry = {}
            for l in lines:
                by_entry.setdefault(l["entry_id"], []).append(l)
            cash_set = set(codes)
            for ls in by_entry.values():
                net = sum((dec(l["debit"]) - dec(l["credit"]) for l in ls
                           if l["account_code"] in cash_set), dec(0))
                if net == 0:
                    continue
                others = [l for l in ls if l["account_code"] not in cash_set]
                cats = {l["category"] for l in others}
                items = {l["fs_line_item"] for l in others}
                # 只有非流动资产 / 权益 / 借款算投资与融资，其余已在经营活动里。
                FINANCING_ITEMS = {
                    "NON_CURRENT_LIABILITY", "NON_CURRENT_LIABILITIES",
                    "SHORT_TERM_BORROWINGS", "LONG_TERM_BORROWINGS", "BORROWINGS",
                    "LEASE_LIABILITIES_CURRENT", "LEASE_LIABILITIES_NONCURRENT",
                }
                INVESTING_ITEMS = {
                    "FIXED_ASSETS", "NON_CURRENT_ASSET", "NON_CURRENT_ASSETS",
                    "PROPERTY_PLANT_EQUIPMENT", "INTANGIBLE_ASSETS",
                    "LONG_TERM_INVESTMENTS", "INVESTMENT_PROPERTIES",
                }
                if "equity" in cats or items & FINANCING_ITEMS:
                    fin += net
                elif "asset" in cats and items & INVESTING_ITEMS:
                    inv += net

    # 经营活动现金流取「现金净变动 − 投资 − 融资」：报表天然配平。
    # 与「净利 + 调整」的差额单列一行，不藏起来。
    operating = move - inv - fin
    residual = operating - explained
    adjustments = list(working_capital)
    if abs(residual) >= 0.005:
        adjustments.append({"label": _t("其他（未归类）", "其他（未歸類）", "Other (unclassified)"),
                            "amount": float(residual)})

    return {
        "openingCash": float(opening),
        "openingEntryCash": float(opening_entry_move),
        "netProfit": float(net_profit_for_cf),
        "netProfitReported": float(net_profit),
        "openingPlExcluded": float(opening_pl),
        "nonCash": noncash, "nonCashTotal": float(noncash_total),
        "workingCapital": adjustments,
        "workingCapitalTotal": float(sum((dec(x["amount"]) for x in adjustments), dec(0))),
        "operating": float(operating),
        "investing": float(inv),
        "financing": float(fin),
        "netChange": float(move + opening_entry_move),
        "closingCash": float(closing),
        "check": float(closing - (opening + opening_entry_move + operating + inv + fin)),
        "note": _t("间接法：净利 + 非现金调整 + 营运资金变动 = 经营活动现金流",
                   "間接法：淨利 + 非現金調整 + 營運資金變動 = 經營活動現金流",
                   "Indirect method: profit + non-cash adjustments + working capital movement = operating cash flow"),
    }



# ---------------------------------------------------------------- 新增：账户类型摘要
def _type_labels():
    return {
        "asset": _t("资产", "資產", "Assets"),
        "liability": _t("负债", "負債", "Liabilities"),
        "equity": _t("所有者权益", "所有者權益", "Equity"),
        "revenue": _t("收入", "收入", "Revenue"),
        "cogs": _t("销售成本", "銷貨成本", "Cost of sales"),
        "expense": _t("费用", "費用", "Expenses"),
    }


def _type_order():
    return [
        ("CASH", _t("现金", "現金", "Cash")),
        ("CASH_EQUIVALENTS", _t("银行", "銀行", "Bank")),
        ("TRADE_RECEIVABLES", _t("应收账款", "應收帳款", "Trade receivables")),
        ("INVENTORY", _t("库存", "庫存", "Inventories")),
        ("PREPAID", _t("其他流动资产", "其他流動資產", "Other current assets")),
        ("OTHER_CURRENT_ASSET", _t("其他流动资产", "其他流動資產", "Other current assets")),
        ("FIXED_ASSETS", _t("固定资产", "固定資產", "Fixed assets")),
        ("NON_CURRENT_ASSET", _t("非流动资产", "非流動資產", "Non-current assets")),
        ("TRADE_PAYABLES", _t("应付账款", "應付帳款", "Trade payables")),
        ("OTHER_CURRENT_LIABILITY", _t("其他流动负债", "其他流動負債", "Other current liabilities")),
        ("NON_CURRENT_LIABILITY", _t("非流动负债", "非流動負債", "Non-current liabilities")),
        ("OTHER_LIABILITY", _t("其他负债", "其他負債", "Other liabilities")),
        ("EQUITY", _t("所有者权益", "所有者權益", "Equity")),
        ("REVENUE", _t("收入", "收入", "Revenue")),
        ("OTHER_INCOME", _t("其他收入", "其他收入", "Other income")),
        ("COGS", _t("销售成本", "銷貨成本", "Cost of sales")),
        ("OPEX", _t("营业费用", "營業費用", "Operating expenses")),
        ("FINANCE_COSTS", _t("财务费用", "財務費用", "Finance costs")),
        ("TAX_EXPENSE", _t("税项", "稅項", "Tax expense")),
    ]


def account_type_summary(entity_id, start=None, end=None):
    """帳戶類型摘要：按科目类型汇总本期借贷。

    审计包里常见的一张「那一类科目本期动了多少钱」，比试算表更粗、
    比利润表更全（含资产负债类）。期间不传则取全部历史。
    """
    where, params = [], [entity_id]
    if start:
        where.append("AND e.entry_date >= %s"); params.append(start)
    if end:
        where.append("AND e.entry_date <= %s"); params.append(end)
    rows = query(
        f"""SELECT a.category, a.fs_line_item, a.account_code,
                   COALESCE(SUM(l.debit),0) AS dr, COALESCE(SUM(l.credit),0) AS cr
              FROM journal_lines l
              JOIN journal_entries e ON e.entry_id=l.entry_id
              JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=e.entity_id
             WHERE e.entity_id=%s AND {POSTED} {' '.join(where)}
             GROUP BY a.category, a.fs_line_item, a.account_code""", tuple(params))

    buckets = {}
    for r in rows:
        key = (r["category"], r["fs_line_item"] or "OTHER_CURRENT_ASSET")
        b = buckets.setdefault(key, {"debit": dec(0), "credit": dec(0), "accounts": []})
        b["debit"] += dec(r["dr"])
        b["credit"] += dec(r["cr"])
        b["accounts"].append(r["account_code"])

    groups = []
    type_label, type_order = _type_labels(), _type_order()
    for cat in ("asset", "liability", "equity", "revenue", "cogs", "expense"):
        merged = {}
        for fli, label in type_order:
            b = buckets.get((cat, fli))
            if not b:
                continue
            m = merged.setdefault(label, {"type": label, "debit": 0.0,
                                          "credit": 0.0, "accounts": []})
            m["debit"] += float(b["debit"])
            m["credit"] += float(b["credit"])
            m["accounts"] += sorted(b["accounts"])
        lst = list(merged.values())
        if lst:
            groups.append({"category": cat, "label": type_label[cat], "items": lst,
                           "debit": float(sum(i["debit"] for i in lst)),
                           "credit": float(sum(i["credit"] for i in lst))})
    return {"groups": groups,
            "debit": float(sum(g["debit"] for g in groups)),
            "credit": float(sum(g["credit"] for g in groups))}


# ---------------------------------------------------------------- 新增：详细总分类账
def _gl_detail_text(text):
    """交易明细只保留摘要本身：去掉导入时拼在前面的科目名（以 2+ 空格分隔）。"""
    raw = str(text or "").strip()
    parts = re.split(r"[ \t]{2,}", raw, maxsplit=1)
    s = parts[1].strip() if len(parts) == 2 and parts[1].strip() else raw
    return re.sub(r"[ \t]+", " ", s)[:200]


def general_ledger_detail(entity_id, start=None, end=None, account_code=None):
    """詳細的總分類帳：每个科目的期初余额 + 逐笔流水 + 结余。"""
    acc_where, acc_args = ["entity_id=%s", "is_active=1"], [entity_id]
    if account_code:
        acc_where.append("account_code=%s"); acc_args.append(account_code)
    accounts = query(f"""SELECT account_code, {_name_col('accounts')} AS account_name, category,
                                normal_balance
                           FROM accounts WHERE {' AND '.join(acc_where)}
                          ORDER BY account_code""", tuple(acc_args))

    out = []
    for a in accounts:
        code = a["account_code"]
        ob = dec(0)
        if start:
            r = query_one(
                f"""SELECT COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
                      FROM journal_lines l JOIN journal_entries e ON e.entry_id=l.entry_id
                     WHERE e.entity_id=%s AND {POSTED} AND l.account_code=%s
                       AND e.entry_date < %s""", (entity_id, code, start))
            ob = (dec(r["dr"]) - dec(r["cr"])) if r else dec(0)
        q2 = (f"""SELECT l.entry_id, e.entry_date, e.entry_no, e.description, e.source_type,
                         l.debit, l.credit, l.description AS line_desc
                    FROM journal_lines l JOIN journal_entries e ON e.entry_id=l.entry_id
                   WHERE e.entity_id=%s AND {POSTED} AND l.account_code=%s
                     {'AND e.entry_date >= %s' if start else ''}
                     {'AND e.entry_date <= %s' if end else ''}
                   ORDER BY e.entry_date, e.entry_id""")
        args = [entity_id, code]
        if start: args.append(start)
        if end: args.append(end)
        lines = query(q2, tuple(args))
        if not lines and abs(ob) < 0.005:
            continue
        running = ob
        rows = []
        for l in lines:
            running += dec(l["debit"]) - dec(l["credit"])
            rows.append({
                "date": l["entry_date"].isoformat(),
                "entryNo": l["entry_no"],
                "description": _gl_detail_text(l["line_desc"] or l["description"] or ""),
                "sourceType": l["source_type"],
                "debit": float(dec(l["debit"])),
                "credit": float(dec(l["credit"])),
                "balance": float(running),
            })
        out.append({"accountCode": code, "accountName": a["account_name"],
                    "category": a["category"], "opening": float(ob),
                    "debit": float(sum(dec(x["debit"]) for x in rows)),
                    "credit": float(sum(dec(x["credit"]) for x in rows)),
                    "closing": float(running), "lines": rows})
    return {"accounts": out,
            "debit": float(sum(dec(a["debit"]) for a in out)),
            "credit": float(sum(dec(a["credit"]) for a in out))}

def aging(entity_id, side="receivable", as_of=None):
    table = "invoices" if side == "receivable" else "bills"
    col_no = "invoice_no" if side == "receivable" else "bill_no"
    col_date = "invoice_date" if side == "receivable" else "date"
    # 未结金额含税，折功能货币也必须是含税口径：
    # invoices 拆了净额与税额两列，bills 只有原币税额，故分别构造表达式
    if side == "receivable":
        gross_fn = "amount_functional + COALESCE(tax_functional, 0)"
    else:
        gross_fn = "amount_functional + COALESCE(tax_amount, 0) * COALESCE(fx_rate, 1)"
    asof_sql, asof_args = "", []
    if as_of and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(as_of)):
        asof_sql = f" AND {col_date} <= %s"
        asof_args = [as_of]
    rows = query(
        f"""SELECT {col_no} AS doc_no, currency, gross_original, settled_original,
                   {gross_fn} AS gross_functional, {col_date} AS doc_date
              FROM {table}
             WHERE entity_id=%s AND status='posted'
               AND (gross_original - settled_original) > 0{asof_sql}
             ORDER BY {col_date}""", tuple([entity_id] + asof_args))

    from datetime import date, datetime as _dt
    today = (_dt.strptime(str(as_of), "%Y-%m-%d").date()
             if (as_of and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(as_of))) else date.today())
    buckets = {"0-30": dec(0), "31-60": dec(0), "61-90": dec(0), "90+": dec(0)}
    by_ccy, items = {}, []

    for r in rows:
        out = dec(r["gross_original"]) - dec(r["settled_original"])
        d = r["doc_date"]
        days = (today - d).days if hasattr(d, "year") else 0
        key = "0-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "90+"
        ccy = r["currency"]
        g = by_ccy.setdefault(ccy, {"currency": ccy, "0-30": dec(0), "31-60": dec(0),
                                    "61-90": dec(0), "90+": dec(0), "total": dec(0), "functional": dec(0)})
        g[key] += out
        g["total"] += out
        # 按未结比例折算，避免已收款部分仍计入账龄
        ratio = (out / dec(r["gross_original"])) if dec(r["gross_original"]) else dec(0)
        g["functional"] += (dec(r["gross_functional"]) * ratio)
        buckets[key] += out
        items.append({"docNo": r["doc_no"], "currency": ccy,
                      "docDate": d.isoformat() if hasattr(d, "isoformat") else str(d),
                      "days": days, "bucket": key, "outstanding": float(out)})

    return {"side": side, "buckets": {k: float(v) for k, v in buckets.items()},
            "byCurrency": [{"currency": g["currency"],
                            "0-30": float(g["0-30"]), "31-60": float(g["31-60"]),
                            "61-90": float(g["61-90"]), "90+": float(g["90+"]),
                            "total": float(g["total"]), "functionalHkd": float(g["functional"])}
                           for g in by_ccy.values()],
            "items": items,
            "note": _t("外币账龄按币种分列；功能货币汇总取折算列之和，不直接相加原币",
                       "外幣賬齡按幣種分列；功能貨幣匯總取折算列之和，不直接相加原幣",
                       "Foreign-currency aging is presented by currency; functional-currency totals sum translated amounts, not original currencies")}


def bank_balances(entity_id):
    # 功能货币（HKD）优先，其余按币种字母序 —— 默认货币必须排第一
    ent = query_one("SELECT functional_currency FROM entities WHERE entity_id=%s", (entity_id,))
    base = (ent or {}).get("functional_currency") or "HKD"
    rows = query("""SELECT account_id, name, account_holder, currency, account_code,
                           bank_name, bank_code, swift_code, bank_address, branch,
                           account_number, account_number_masked, is_primary_receiving,
                           current_balance, current_balance_functional,
                           last_reval_rate, last_reval_date
                      FROM bank_accounts WHERE entity_id=%s AND status='active'
                     ORDER BY (currency = %s) DESC, currency, account_id""",
                 (entity_id, base))
    # 账面余额取总账。bank_accounts.current_balance 只在导入流水时维护，
    # 期初结转、手工分录不会动它，直接用会出现「总账六万八、首页显示零」。
    gl = {}
    for gr in query("""SELECT l.account_code,
                              COALESCE(SUM(l.debit),0)-COALESCE(SUM(l.credit),0) AS bal
                         FROM journal_lines l JOIN journal_entries e ON e.entry_id=l.entry_id
                        WHERE e.entity_id=%s AND e.status IN ('posted','reversed')
                          AND l.account_code IN (SELECT account_code FROM bank_accounts
                                                  WHERE entity_id=%s AND status='active')
                        GROUP BY l.account_code""", (entity_id, entity_id)):
        gl[gr["account_code"]] = dec(gr["bal"])

    groups = {}
    for r in rows:
        g = groups.setdefault(r["currency"], {"currency": r["currency"], "accounts": [],
                                              "originalTotal": dec(0), "functionalTotal": dec(0)})
        if r["account_code"] in gl:
            r = dict(r, current_balance=gl[r["account_code"]],
                        current_balance_functional=gl[r["account_code"]])
        item = dict(r, current_balance=dec(r["current_balance"]),
                    current_balance_functional=dec(r["current_balance_functional"]),
                    last_reval_rate=float(r["last_reval_rate"]) if r["last_reval_rate"] is not None else None,
                    last_reval_date=r["last_reval_date"].isoformat() if r["last_reval_date"] else None)
        g["accounts"].append(item)
        g["originalTotal"] += item["current_balance"]
        g["functionalTotal"] += item["current_balance_functional"]

    out = []
    for g in groups.values():
        out.append({"currency": g["currency"],
                    "accounts": [dict(a, current_balance=float(a["current_balance"]),
                                      current_balance_functional=float(a["current_balance_functional"]))
                                 for a in g["accounts"]],
                    "originalTotal": float(g["originalTotal"]),
                    "functionalTotal": float(g["functionalTotal"])})
    return {"groups": out,
            "hkdTotal": float(sum((dec(g["functionalTotal"]) for g in out), dec(0))),
            "currencies": [g["currency"] for g in out],
            "note": "不同币种不得直接相加；HKD 合计为各账户折算金额之和"}


def fx_gain_loss(entity_id):
    rows = query(
        f"""SELECT a.account_code, {_name_col()} AS account_name, e.source_type,
                   COALESCE(SUM(l.debit),0) AS dr, COALESCE(SUM(l.credit),0) AS cr
              FROM journal_lines l
              JOIN journal_entries e ON e.entry_id=l.entry_id
              JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=e.entity_id
             WHERE e.entity_id=%s AND {POSTED} AND a.fs_line_item='FX_GAIN_LOSS'
             GROUP BY a.account_code, {_name_col()}, e.source_type""", (entity_id,))
    items = [{"accountCode": r["account_code"], "accountName": r["account_name"],
              "sourceType": r["source_type"],
              "amount": float(dec(r["cr"]) - dec(r["dr"]))} for r in rows]
    return {"items": items,
            "total": float(sum((dec(i["amount"]) for i in items), dec(0))),
            "note": "正数为汇兑收益，负数为汇兑损失"}


# ============================================================================
# HKFRS 财务报表：权益变动表 + 报表包
# ============================================================================

def _account_balance_at(entity_id, upto, category=None):
    """截至某日（含）的科目净发生额，按 normal_balance 取符号。"""
    sql = f"""SELECT a.account_code, {_name_col()} AS account_name, a.category, a.fs_line_item,
                    a.normal_balance,
                    COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
               FROM journal_lines l
               JOIN journal_entries e ON e.entry_id = l.entry_id
               JOIN accounts a ON a.account_code = l.account_code AND a.entity_id = e.entity_id
              WHERE e.entity_id = %s AND {POSTED}
                AND e.entry_date <= %s """
    params = [entity_id, upto]
    if category:
        sql += " AND a.category = %s "
        params.append(category)
    sql += f""" GROUP BY a.account_code, {_name_col()}, a.category, a.fs_line_item, a.normal_balance
              ORDER BY a.account_code"""
    out = []
    for r in query(sql, tuple(params)):
        net = dec(r["dr"]) - dec(r["cr"])
        signed = net if r["normal_balance"] == "debit" else -net
        out.append(dict(r, signed=signed))
    return out


def _profit_between(entity_id, start, end):
    """区间损益：收入 − 成本 − 费用。"""
    rows = query(f"""SELECT a.category,
                           COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
                      FROM journal_lines l
                      JOIN journal_entries e ON e.entry_id = l.entry_id
                      JOIN accounts a ON a.account_code = l.account_code AND a.entity_id = e.entity_id
                     WHERE e.entity_id = %s AND {POSTED}
                       AND e.entry_date >= %s AND e.entry_date <= %s
                       AND a.category IN ('revenue','cogs','expense')
                     GROUP BY a.category""", (entity_id, start, end))
    m = {r["category"]: dec(r["cr"]) - dec(r["dr"]) for r in rows}
    # 收入正常为贷方余额；成本费用为借方，取相反数
    rev = m.get("revenue", dec(0))
    cost = -(m.get("cogs", dec(0)))
    exp = -(m.get("expense", dec(0)))
    return {"revenue": rev, "costOfSales": cost, "expenses": exp,
            "profit": rev - cost - exp}


def equity_changes(entity_id, start, end):
    """权益变动表（HKAS 1）。

    口径：期初权益 = 期初权益科目余额 + 期初累计损益；
    期末权益 = 期初权益 + 本期利润 + 本期权益科目直接发生额。
    直接发生额单独列示（如增资、宣派股息），不要与本期利润混为一谈。
    """
    from datetime import date, timedelta
    from .money import parse_date

    sd = parse_date(start)
    day_before = (sd - timedelta(days=1)).isoformat() if sd else start

    opening_acct = sum((r["signed"] for r in _account_balance_at(entity_id, day_before, "equity")), dec(0))
    opening_profit = _profit_between(entity_id, "0000-01-01", day_before)["profit"]
    opening_equity = opening_acct + opening_profit

    # 本期损益从期起当日开始；day_before 只用于期初余额，不能重复计入本期。
    period = _profit_between(entity_id, start, end)
    closing_acct = sum((r["signed"] for r in _account_balance_at(entity_id, end, "equity")), dec(0))

    direct = closing_acct - opening_acct           # 本期权益科目的直接发生额
    closing_equity = opening_equity + period["profit"] + direct

    cols = [{"code": r["account_code"], "name": r["account_name"], "amount": float(r["signed"])}
            for r in _account_balance_at(entity_id, end, "equity") if r["signed"] != 0]

    return {
        "from": start, "to": end,
        "openingEquityAccounts": float(opening_acct),
        "openingRetainedProfit": float(opening_profit),
        "openingEquity": float(opening_equity),
        "profitForPeriod": float(period["profit"]),
        "equityDirectMovements": float(direct),
        "closingEquityAccounts": float(closing_acct),
        "closingEquity": float(closing_equity),
        "closingByAccount": cols,
        "balanced": abs(float(closing_equity - (closing_acct + period["profit"] + opening_profit))) < 0.005,
        "note": _t("期初权益含累计未分配利润；「权益直接变动」为权益科目本期发生额",
                   "期初權益含累計未分配利潤；「權益直接變動」為權益科目本期發生額",
                   "Opening equity includes accumulated retained earnings; direct equity movements are movements in equity accounts during the period"),
    }


def financial_statements(entity_id, entity, period_start, period_end):
    """完整财务报表包：财务状况表 / 损益及其他全面收益表 / 权益变动表 / 现金流量表 / 附注。"""
    # 损益与现金流严格使用所选期间；财务状况表取期末时点，不能退回全部历史。
    pl = profit_and_loss(entity_id, period_start, period_end)
    bs = balance_sheet(entity_id, period_end)
    cf = cash_flow(entity_id, period_start, period_end)
    eq = equity_changes(entity_id, period_start, period_end)

    # 按流动/非流动拆分：以 fs_line_item 前缀判断，缺失则归入流动
    NONCURRENT = {"PROPERTY_PLANT_EQUIPMENT", "FIXED_ASSETS", "NON_CURRENT_ASSET",
                  "NON_CURRENT_ASSETS", "INTANGIBLE_ASSETS", "LONG_TERM_INVESTMENTS",
                  "INVESTMENT_PROPERTIES", "DEFERRED_TAX_ASSET", "NON_CURRENT_LIABILITY",
                  "NON_CURRENT_LIABILITIES", "LONG_TERM_BORROWINGS", "LEASE_LIABILITIES_NONCURRENT"}

    def split(section):
        cur, noncur = [], []
        for it in section["items"]:
            (noncur if it.get("fsLineItem") in NONCURRENT else cur).append(it)
        return cur, noncur

    assets_cur, assets_noncur = split(bs["assets"])
    liab_cur, liab_noncur = split(bs["liabilities"])

    rates = query("""SELECT rate_date, from_ccy, to_ccy, rate FROM fx_rates
                      WHERE rate_date BETWEEN %s AND %s
                        AND to_ccy = %s
                      ORDER BY rate_date, from_ccy""",
                  (period_start, period_end, entity["functional_currency"]))

    return {
        "entity": {"code": entity["entity_code"], "name": entity["entity_name"],
                   "functionalCurrency": entity["functional_currency"],
                   "framework": entity["reporting_framework"],
                   "addressLine1": entity.get("address_line1"),
                   "addressLine2": entity.get("address_line2"),
                   "district": entity.get("district"),
                   "region": entity.get("region"),
                   "brNumber": entity.get("br_number")},
        "periodStart": period_start, "periodEnd": period_end,
        "statementOfFinancialPosition": {
            "assetsNonCurrent": {"items": assets_noncur,
                                 "total": float(sum((dec(i["amount"]) for i in assets_noncur), dec(0)))},
            "assetsCurrent": {"items": assets_cur,
                              "total": float(sum((dec(i["amount"]) for i in assets_cur), dec(0)))},
            "assetsTotal": bs["assets"]["total"],
            "equity": bs["equity"],
            "liabilitiesNonCurrent": {"items": liab_noncur,
                                      "total": float(sum((dec(i["amount"]) for i in liab_noncur), dec(0)))},
            "liabilitiesCurrent": {"items": liab_cur,
                                    "total": float(sum((dec(i["amount"]) for i in liab_cur), dec(0)))},
            "liabilitiesTotal": bs["liabilities"]["total"],
            "check": bs["check"],
        },
        "statementOfProfitOrLoss": {
            "revenue": pl["revenue"], "costOfSales": pl["costOfSales"],
            "grossProfit": pl["grossProfit"],
            "otherIncome": pl["otherIncome"], "otherGains": pl["otherGains"],
            "operatingExpenses": pl["operatingExpenses"],
            "financeCosts": pl["financeCosts"],
            "profitBeforeTax": pl["profitBeforeTax"],
            "taxExpense": pl["taxExpense"],
            "netProfit": pl["netProfit"],
            "otherComprehensiveIncome": 0.0,
            "totalComprehensiveIncome": pl["netProfit"],
            "note": pl["note"],
        },
        "statementOfChangesInEquity": eq,
        "statementOfCashFlows": cf,
        "notes": {
            "basis": [
                _t("本财务报表按香港财务报告准则编制。",
                   "本財務報表按香港財務報告準則編製。",
                   "These financial statements are prepared under Hong Kong Financial Reporting Standards.")
                if entity["reporting_framework"] == "full_hkfrs" else
                _t("本财务报表按《香港财务报告准则》中小型企业准则编制。",
                   "本財務報表按《香港財務報告準則》中小型企業準則編製。",
                   "These financial statements are prepared under the HKFRS for Private Entities."),
                _t(f"功能货币为 {entity['functional_currency']}，列报货币相同。",
                   f"功能貨幣為 {entity['functional_currency']}，列報貨幣相同。",
                   f"The functional and presentation currency is {entity['functional_currency']}."),
                _t(f"金额单位为 {entity['functional_currency']}，除另有注明外均四舍五入至小数点后两位。",
                   f"金額單位為 {entity['functional_currency']}，除另有註明外均四捨五入至小數點後兩位。",
                   f"Amounts are in {entity['functional_currency']} and rounded to two decimal places unless otherwise stated."),
                _t("会计记录采用权责发生制；不同币种的金额不直接相加，折算后方可汇总。",
                   "會計記錄採用權責發生制；不同幣種的金額不直接相加，折算後方可匯總。",
                   "Accounting records use the accrual basis. Amounts in different currencies are translated before aggregation."),
            ],
            "fxRates": [{"date": r["rate_date"].isoformat(),
                         "pair": f"{r['from_ccy']}→{r['to_ccy']}",
                         "rate": float(dec(r["rate"]))} for r in rates],
            "policies": [
                _t("收入：按 HKFRS 15 五步法确认。", "收入：按 HKFRS 15 五步法確認。",
                   "Revenue: recognised using the five-step model in HKFRS 15."),
                _t("外币折算：按 HKAS 21，货币性项目于期末按即期汇率重估，差额计入损益。",
                   "外幣折算：按 HKAS 21，貨幣性項目於期末按即期匯率重估，差額計入損益。",
                   "Foreign currency: under HKAS 21, monetary items are retranslated at closing rates with differences in profit or loss."),
                _t("金融工具：应收应付按摊余成本计量。", "金融工具：應收應付按攤餘成本計量。",
                   "Financial instruments: receivables and payables are measured at amortised cost."),
                _t("利得税：按 HKAS 12 处理；两级制税率资格以税务机关认定为准。",
                   "利得稅：按 HKAS 12 處理；兩級制稅率資格以稅務機關認定為準。",
                   "Profits tax: accounted for under HKAS 12; two-tier eligibility is subject to tax-authority assessment."),
            ],
            "twoTierStatus": entity["two_tier_status"],
            "relatedParties": _related_party_notes(entity),
        },
        "generatedAt": None,
    }



# ---------------------------------------------------------------- 关联方（HKAS 24）
RP_KEYWORDS = ("股东", "股東", "董事", "关联", "關聯", "股东借款", "股東借款",
               "王若薇", "刘明伟", "劉明偉")


def _related_party_notes(entity):
    """关联方交易：从分录摘要里认人。

    没有「关联方」主数据表，靠分录摘要里的关键词识别；宁可比对得粗一点，
    也不要在审计附注里漏掉股东借款这种必披露项。
    """
    eid = entity["entity_id"]
    cond = " OR ".join(["e.description LIKE %s"] * len(RP_KEYWORDS))
    args = [f"%{k}%" for k in RP_KEYWORDS]
    rows = query(
        f"""SELECT a.account_code, a.category, e.description, e.entry_date,
                   COALESCE(SUM(l.debit),0) dr, COALESCE(SUM(l.credit),0) cr
              FROM journal_lines l
              JOIN journal_entries e ON e.entry_id=l.entry_id
              JOIN accounts a ON a.account_code=l.account_code AND a.entity_id=e.entity_id
             WHERE e.entity_id=%s AND {POSTED}
               AND ({cond})
               AND a.category IN ('liability','equity','asset')
               AND COALESCE(a.fs_line_item,'') NOT IN ('CASH','CASH_EQUIVALENTS')
             GROUP BY a.account_code, a.category, e.description, e.entry_date""",
        tuple([eid] + args))
    if not rows:
        return []
    out = {}
    for r in rows:
        key = (r["account_code"], r["category"])
        item = out.setdefault(key, {"accountCode": r["account_code"],
                                    "category": r["category"],
                                    "balance": 0.0, "date": r["entry_date"].isoformat(),
                                    "description": r["description"]})
        item["balance"] += float(dec(r["cr"]) - dec(r["dr"]))
    return sorted(out.values(), key=lambda x: -abs(x["balance"]))

# ============================================================================
# 补充分析报表：财务比率表 / 客户余额表 / 供应商余额表
# ============================================================================

def financial_ratios(entity_id):
    """财务比率（Business Performance Ratio）。比率一律由确定性代码计算。"""
    bs = balance_sheet(entity_id)
    pl = profit_and_loss(entity_id)
    tb = trial_balance(entity_id)

    assets = dec(bs["assets"]["total"])
    liab = dec(bs["liabilities"]["total"])
    equity = dec(bs["equity"]["total"])
    revenue = dec(pl["revenue"]["total"])
    gross = dec(pl["grossProfit"])
    net = dec(pl["netProfit"])
    cogs = dec(pl["costOfSales"]["total"])
    opex = dec(pl["operatingExpenses"]["total"])

    # 流动资产/负债：按 fs_line_item 归集
    cur_assets = sum((dec(i["amount"]) for i in bs["assets"]["items"]
                      if str(i.get("fsLineItem") or "").startswith(("CASH", "TRADE_RECEIVABLES",
                                                                    "CONTRACT_ASSETS", "PREPAY", "TAX_ASSETS"))), dec(0))
    cur_liab = sum((dec(i["amount"]) for i in bs["liabilities"]["items"]
                    if str(i.get("fsLineItem") or "").startswith(("TRADE_PAYABLES", "CONTRACT_LIAB",
                                                                  "ACCRUALS", "TAX_LIAB", "CREDIT_CARD"))), dec(0))

    # 多币种账龄不能把原币 buckets 直接相加；比率基础使用各币种折算后的功能货币金额。
    def outstanding(side):
        data = aging(entity_id, side)
        return sum((dec(row.get("functionalHkd", 0)) for row in data["byCurrency"]), dec(0))

    ar = outstanding("receivable")
    ap = outstanding("payable")

    def r(num, den):
        n, d = dec(num), dec(den)
        if n is None or d is None or d == 0:
            return None
        return float((n / d).quantize(dec("0.0001")))

    def days(den):
        if revenue == 0:
            return None
        return float((ar / revenue * 365).quantize(dec("0.1")))

    items = [
        ("流动比率", r(cur_assets, cur_liab), "流动资产 ÷ 流动负债", "倍"),
        ("速动比率", r(cur_assets, cur_liab), "（流动资产 − 存货）÷ 流动负债", "倍"),
        ("资产负债率", r(liab, assets), "总负债 ÷ 总资产", "倍"),
        ("毛利率", r(gross, revenue), "毛利 ÷ 收入", "%"),
        ("净利率", r(net, revenue), "净利 ÷ 收入", "%"),
        ("费用率", r(opex, revenue), "经营费用 ÷ 收入", "%"),
        ("成本率", r(cogs, revenue), "销售成本 ÷ 收入", "%"),
        ("权益回报率", r(net, equity), "净利 ÷ 期末权益", "%"),
        ("应收周转天数", days(revenue), "应收账款 ÷ 收入 × 365", "天"),
    ]
    return {
        "items": [{"name": n, "value": v, "formula": f, "unit": u} for n, v, f, u in items],
        "basis": {"totalAssets": float(assets), "totalLiabilities": float(liab),
                  "totalEquity": float(equity), "revenue": float(revenue),
                  "grossProfit": float(gross), "netProfit": float(net),
                  "currentAssets": float(cur_assets), "currentLiabilities": float(cur_liab),
                  "receivables": float(ar), "payables": float(ap)},
        "note": "比率仅供参考；不同行业基准差异很大，不应单独作为决策依据",
    }


def customer_balances(entity_id):
    """客户余额表：已开票、已收、未收。"""
    rows = query("""SELECT supplier_name AS party, currency,
                           COUNT(*) AS invoices,
                           SUM(gross_original) AS invoiced,
                           SUM(settled_original) AS settled,
                           SUM(gross_original - settled_original) AS outstanding,
                           SUM(CASE WHEN gross_original > 0
                                    THEN (gross_original - settled_original) / gross_original
                                         * (amount_functional + COALESCE(tax_functional,0))
                                    ELSE 0 END) AS outstanding_functional
                      FROM invoices WHERE entity_id=%s AND status='posted'
                     GROUP BY supplier_name, currency
                     ORDER BY outstanding DESC""", (entity_id,))
    return {"rows": [{"party": r["party"], "currency": r["currency"],
                      "invoices": int(r["invoices"]),
                      "invoiced": float(dec(r["invoiced"])),
                      "settled": float(dec(r["settled"])),
                      "outstanding": float(dec(r["outstanding"])),
                      "outstandingFunctional": float(dec(r["outstanding_functional"]))} for r in rows],
            "totalFunctional": float(sum((dec(r["outstanding_functional"]) for r in rows), dec(0))),
            "note": "按客户与币种分列；HKD 合计仅取折算列"}


def vendor_balances(entity_id):
    """供应商余额表：已收票、已付、未付。"""
    rows = query("""SELECT vendor_name AS party, currency,
                           COUNT(*) AS bills,
                           SUM(gross_original) AS billed,
                           SUM(settled_original) AS settled,
                           SUM(gross_original - settled_original) AS outstanding,
                           SUM(CASE WHEN gross_original > 0
                                    THEN (gross_original - settled_original) / gross_original
                                         * (amount_functional + COALESCE(tax_amount,0) * COALESCE(fx_rate,1))
                                    ELSE 0 END) AS outstanding_functional
                      FROM bills WHERE entity_id=%s AND status='posted'
                     GROUP BY vendor_name, currency
                     ORDER BY outstanding DESC""", (entity_id,))
    return {"rows": [{"party": r["party"], "currency": r["currency"],
                      "bills": int(r["bills"]),
                      "billed": float(dec(r["billed"])),
                      "settled": float(dec(r["settled"])),
                      "outstanding": float(dec(r["outstanding"])),
                      "outstandingFunctional": float(dec(r["outstanding_functional"]))} for r in rows],
            "totalFunctional": float(sum((dec(r["outstanding_functional"]) for r in rows), dec(0))),
            "note": "按供应商与币种分列；HKD 合计仅取折算列"}
