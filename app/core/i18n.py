# LtBooks — core/i18n.py
# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT

"""三语支持：简体中文 / 香港繁体中文 / 英文。

科目名以英文为权威来源（会计术语），简繁由「英文→中文」映射表给出，
避免依赖简繁自动转换产生「税/稅」「兑/兌」这类不一致。
"""
import re

LANGS = ("zh_cn", "zh_hk", "en")
DEFAULT_LANG = "zh_cn"

# 会计科目英文名（按科目编码，编码是稳定键）
ACCOUNT_EN = {
 "1000": "Assets", "1100": "Current Assets", "1110": "Cash",
 "1120": "Bank and Credit Cards", "1121": "Bank Account — HKD",
 "1122": "Bank Account — USD", "1123": "Bank Account — CNY",
 "1124": "Bank Account — CAD", "1130": "Trade Receivables",
 "1131": "Trade Receivables — Foreign Currency", "1140": "Contract Assets",
 "1150": "Prepayments", "1160": "Input Tax", "1170": "Inventories",
 "1171": "Notes Receivable", "1172": "Other Receivables",
 "1173": "Deposits and Prepayments", "1174": "Tax Recoverable",
 "1200": "Non-current Assets", "1210": "Property, Plant and Equipment",
 "1211": "Buildings", "1212": "Plant and Machinery", "1213": "Computer Equipment",
 "1214": "Furniture and Fixtures", "1215": "Motor Vehicles",
 "1219": "Accumulated Depreciation — PP&E", "1220": "Right-of-use Assets",
 "1229": "Accumulated Depreciation — Right-of-use Assets",
 "1230": "Intangible Assets", "1240": "Investment Properties",
 "1250": "Long-term Investments", "1260": "Deferred Tax Assets",
 "2000": "Liabilities", "2100": "Current Liabilities", "2110": "Trade Payables",
 "2111": "Trade Payables — Foreign Currency", "2120": "Contract Liabilities",
 "2130": "Accrued Expenses", "2140": "Output Tax", "2150": "Profits Tax Payable",
 "2160": "Credit Card", "2170": "Notes Payable", "2171": "Payroll Payable",
 "2172": "Provisional Profits Tax", "2173": "Other Payables",
 "2174": "Lease Liabilities — Current", "2175": "Short-term Borrowings",
 "2200": "Non-current Liabilities", "2210": "Long-term Borrowings",
 "2220": "Lease Liabilities — Non-current", "2230": "Deferred Tax Liabilities",
 "2240": "Provisions",
 "3000": "Equity", "3100": "Share Capital", "3200": "Retained Earnings",
 "3300": "Current Year Profit or Loss", "3400": "Share Premium",
 "3500": "Revaluation Reserve", "3600": "Foreign Currency Translation Reserve",
 "3700": "Dividends Declared",
 "4000": "Revenue", "4100": "Sales Revenue", "4200": "Service Revenue",
 "4300": "Other Income", "4400": "Exchange Differences",
 "4410": "Exchange Differences — Realised", "4420": "Exchange Differences — Unrealised (Revaluation)",
 "4500": "Interest Income", "4510": "Dividend Income",
 "4520": "Government Grants", "4530": "Sundry Income",
 "5000": "Cost of Sales", "5100": "Purchases", "5200": "Service Costs",
 "5300": "Inventory Adjustments", "5400": "Subcontracting Costs",
 "6000": "Operating Expenses", "6100": "Staff Costs", "6110": "MPF Contributions",
 "6120": "Salaries and Wages", "6130": "Employee Benefits",
 "6140": "Severance and Long Service Payments", "6200": "Rent",
 "6210": "Rates and Government Rent", "6220": "Building Management Fees",
 "6230": "Utilities", "6300": "Professional Fees", "6310": "Audit Fee",
 "6320": "Legal and Consulting Fees", "6330": "Company Secretarial Fees",
 "6400": "Bank Charges", "6500": "Travelling", "6510": "Entertainment",
 "6520": "Transport", "6600": "Office Expenses", "6610": "Communication",
 "6620": "Computer and Software", "6630": "Repairs and Maintenance",
 "6640": "Insurance", "6650": "Business Registration Fee", "6700": "Depreciation",
 "6800": "Profits Tax Expense", "6810": "Amortisation",
 "6820": "Depreciation — Right-of-use Assets",
 "7000": "Finance Costs", "7100": "Interest Expense", "7110": "Bank Overdraft Interest",
}

# 香港繁体术语修正：opencc 的 s2hk 会把「税」「兑」留作简体
HK_FIX = [("税", "稅"), ("兑", "兌"), ("账", "賬"), ("户", "戶")]


def to_hk(s: str) -> str:
    from opencc import OpenCC
    out = OpenCC("s2hk").convert(s)
    for a, b in HK_FIX:
        out = out.replace(a, b)
    return out


def to_cn(s: str) -> str:
    from opencc import OpenCC
    return OpenCC("t2s").convert(s)


def account_names(code: str, cn: str) -> dict:
    """给定原始名称，返回三语。"""
    return {"zh_cn": to_cn(cn), "zh_hk": to_hk(cn), "en": ACCOUNT_EN.get(code, cn)}


# ---------------------------------------------------------------- 报表标签
LABELS = {
    "zh_cn": {
        "statement_of_financial_position": "财务状况表",
        "statement_of_profit_or_loss": "损益及其他全面收益表",
        "statement_of_changes_in_equity": "权益变动表",
        "statement_of_cash_flows": "现金流量表",
        "notes": "财务报表附注",
        "financial_statements": "财务报表",
        "as_at": "于 {date} 结算",
        "for_period": "截至 {date} 止期间",
        "period_range": "{start} 至 {end}",
        "currency_note": "金额单位：{cur}",
        "cross_check": "勾稽检查：",
        "cumulative": "累计",
        "closing_equity": "期末权益",
        "note_hkas1": "按 HKAS 1 格式列报；税项按利得税计算表确认后入账，未确认前不预估",
        "note_no_cash": "无现金科目",
        "note_equity": "期初权益含累计未分配利润；「权益直接变动」为权益科目本期发生额",
        "note_ratios": "比率仅供参考；不同行业基准差异很大，不应单独作为决策依据",
        "note_vend_bal": "按供应商与币种分列；HKD 合计仅取折算列",
        "note_cust_bal": "按客户与币种分列；HKD 合计仅取折算列",
        "note_fx_sign": "正数为汇兑收益，负数为汇兑损失",
        "note_fx_bank": "不同币种不得直接相加；HKD 合计为各账户折算金额之和",
        "note_fx_aging": "外币账龄按币种分列；HKD 汇总取折算列之和，不直接相加原币",
        "note_cash_recon": "期末现金必须与资产负债表现金一致",
        "item": "项目", "current": "本期末", "prior": "上期末",
        "assets": "资产", "current_assets": "流动资产", "non_current_assets": "非流动资产",
        "total_assets": "资产合计",
        "equity_liabilities": "权益及负债", "equity": "权益",
        "total_equity": "权益合计", "liabilities": "负债",
        "current_liabilities": "流动负债", "non_current_liabilities": "非流动负债",
        "total_liabilities": "负债合计",
        "revenue": "收入", "cost_of_sales": "销售成本", "gross_profit": "毛利",
        "other_income": "其他收入", "other_gains": "其他收益／（亏损）",
        "operating_expenses": "经营费用", "finance_costs": "财务费用",
        "profit_before_tax": "除税前溢利", "tax": "税项", "net_profit": "本期溢利",
        "oci": "其他全面收益", "total_comprehensive": "本期全面收益总额",
        "fx_translation": "外币报表折算差额",
        "opening_equity": "期初权益", "profit_for_period": "本期溢利",
        "direct_movements": "权益直接变动（增资／股息等）",
        "closing_equity": "期末权益",
        "operating": "经营活动", "investing": "投资活动", "financing": "筹资活动",
        "net_change": "现金及现金等价物净增加", "closing_cash": "期末现金及现金等价物",
        "check_assets": "勾稽：资产 {a} － 权益及负债 {b} ＝ {d}",
        "balanced": "平衡", "unbalanced": "不平衡，须核查",
        "account": "科目", "name": "名称", "code": "编码",
        "debit": "借方", "credit": "贷方", "balance": "余额",
        "account_name": "科目名称", "amount": "金额",
        "currency": "币种", "date": "日期", "description": "摘要",
        "generated": "本报表由 LtBooks 按香港财务报告准则自动生成，数据来自已过账分录。",

        "management_report": "管理报表",
        "trial_balance": "试算表",
        "cash_flow_report": "现金流量表",
        "aging_report": "账龄分析表",
        "bank_balances": "银行账户余额表",
        "fx_report": "汇兑损益表",
        "general_ledger": "总分类账",
        "daybook": "日记簿",
        "sales_detail": "销售明细表",
        "purchase_detail": "采购明细表",
        "ratios": "财务比率表",
        "customer_balances": "客户余额表",
        "vendor_balances": "供应商余额表",
        "profits_tax": "利得税计算表",
        "item": "项目", "amount_hkd": "金额（HKD）", "assessable_profits": "应评税利润", "two_tier_status": "两级制资格", "applicable_rate": "适用税率", "tax_payable": "应缴利得税", "two_tier_nominated": "已提名：首 200 万 8.25%，其余 16.5%", "two_tier_not_nominated": "未提名：全额 16.5%", "two_tier_undetermined": "资格未确定，不计算税额", "basis_posted_entries": "已过账与已冲销分录，按 entry_date 归期，港币本位",
        "daily": "今日",
        "to_date": "截至 {date}",
        "copyright": "© {year} LEDU TECH CO., LIMITED · 依 MIT 许可证发布",
        "hkfrs15_disclosure": "收入披露报表（HKFRS 15）",
        "basis_of_preparation": "编制基础", "significant_policies": "主要会计政策",
    },
    "zh_hk": {
        "statement_of_financial_position": "財務狀況表",
        "statement_of_profit_or_loss": "損益及其他全面收益表",
        "statement_of_changes_in_equity": "權益變動表",
        "statement_of_cash_flows": "現金流量表",
        "notes": "財務報表附註",
        "financial_statements": "財務報表",
        "as_at": "於 {date} 結算",
        "for_period": "截至 {date} 止期間",
        "period_range": "{start} 至 {end}",
        "currency_note": "金額單位：{cur}",
        "cross_check": "勾稽檢查：",
        "cumulative": "累計",
        "closing_equity": "期末權益",
        "note_hkas1": "按 HKAS 1 格式列報；稅項按利得稅計算表確認後入賬，未確認前不預估",
        "note_fx_aging": "外幣賬齡按幣種分列；HKD 匯總取折算列之和，不直接相加原幣",
        "note_fx_bank": "不同幣種不得直接相加；HKD 合計為各賬戶折算金額之和",
        "note_fx_sign": "正數為匯兌收益，負數為匯兌損失",
        "note_cust_bal": "按客戶與幣種分列；HKD 合計僅取折算列",
        "note_vend_bal": "按供應商與幣種分列；HKD 合計僅取折算列",
        "note_ratios": "比率僅供參考；不同行業基準差異很大，不應單獨作為決策依據",
        "note_equity": "期初權益含累計未分配利潤；「權益直接變動」為權益科目本期發生額",
        "note_no_cash": "無現金科目",
        "note_cash_recon": "期末現金必須與資產負債表現金一致",
        "item": "項目", "current": "本期末", "prior": "上期末",
        "assets": "資產", "current_assets": "流動資產", "non_current_assets": "非流動資產",
        "total_assets": "資產合計",
        "equity_liabilities": "權益及負債", "equity": "權益",
        "total_equity": "權益合計", "liabilities": "負債",
        "current_liabilities": "流動負債", "non_current_liabilities": "非流動負債",
        "total_liabilities": "負債合計",
        "revenue": "收入", "cost_of_sales": "銷售成本", "gross_profit": "毛利",
        "other_income": "其他收入", "other_gains": "其他收益／（虧損）",
        "operating_expenses": "經營費用", "finance_costs": "財務費用",
        "profit_before_tax": "除稅前溢利", "tax": "稅項", "net_profit": "本期溢利",
        "oci": "其他全面收益", "total_comprehensive": "本期全面收益總額",
        "fx_translation": "外幣報表折算差額",
        "opening_equity": "期初權益", "profit_for_period": "本期溢利",
        "direct_movements": "權益直接變動（增資／股息等）",
        "closing_equity": "期末權益",
        "operating": "經營活動", "investing": "投資活動", "financing": "籌資活動",
        "net_change": "現金及現金等價物淨增加", "closing_cash": "期末現金及現金等價物",
        "check_assets": "勾稽：資產 {a} － 權益及負債 {b} ＝ {d}",
        "balanced": "平衡", "unbalanced": "不平衡，須核查",
        "account": "科目", "name": "名稱", "code": "編碼",
        "debit": "借方", "credit": "貸方", "balance": "餘額",
        "account_name": "科目名稱", "amount": "金額",
        "currency": "幣種", "date": "日期", "description": "摘要",
        "generated": "本報表由 LtBooks 按香港財務報告準則自動生成，數據來自已過賬分錄。",

        "management_report": "管理報表",
        "trial_balance": "試算表",
        "cash_flow_report": "現金流量表",
        "aging_report": "賬齡分析表",
        "bank_balances": "銀行賬戶餘額表",
        "fx_report": "匯兌損益表",
        "general_ledger": "總分類賬",
        "daybook": "日記簿",
        "sales_detail": "銷售明細表",
        "purchase_detail": "採購明細表",
        "ratios": "財務比率表",
        "customer_balances": "客戶餘額表",
        "vendor_balances": "供應商餘額表",
        "profits_tax": "利得稅計算表",
        "item": "項目", "amount_hkd": "金額（HKD）", "assessable_profits": "應評稅利潤", "two_tier_status": "兩級制資格", "applicable_rate": "適用稅率", "tax_payable": "應繳利得稅", "two_tier_nominated": "已提名：首 200 萬 8.25%，其餘 16.5%", "two_tier_not_nominated": "未提名：全額 16.5%", "two_tier_undetermined": "資格未確定，不計算稅額", "basis_posted_entries": "已過賬與已沖銷分錄，按 entry_date 歸期，港幣本位",
        "daily": "今日",
        "to_date": "截至 {date}",
        "copyright": "© {year} LEDU TECH CO., LIMITED · 依 MIT 許可證發布",
        "hkfrs15_disclosure": "收入披露報表（HKFRS 15）",
        "basis_of_preparation": "編制基礎", "significant_policies": "主要會計政策",
    },
    "en": {
        "statement_of_financial_position": "Statement of Financial Position",
        "statement_of_profit_or_loss": "Statement of Profit or Loss and Other Comprehensive Income",
        "statement_of_changes_in_equity": "Statement of Changes in Equity",
        "statement_of_cash_flows": "Statement of Cash Flows",
        "notes": "Notes to the Financial Statements",
        "financial_statements": "Financial Statements",
        "as_at": "As at {date}",
        "for_period": "For the period ended {date}",
        "period_range": "{start} to {end}",
        "currency_note": "Amounts in {cur}",
        "cross_check": "Cross-check:",
        "cumulative": "Cumulative",
        "closing_equity": "Closing equity",
        "note_hkas1": "Presented under HKAS 1; tax is recognised per the profits tax computation and not accrued before confirmation",
        "note_fx_aging": "Foreign-currency aging is shown per currency; the HKD total sums the translated column, not the original amounts",
        "note_fx_bank": "Different currencies are not added directly; the HKD total sums each account after translation",
        "note_fx_sign": "Positive = exchange gain; negative = exchange loss",
        "note_cust_bal": "Split by customer and currency; the HKD total uses the translated column only",
        "note_vend_bal": "Split by vendor and currency; the HKD total uses the translated column only",
        "note_ratios": "Ratios are indicative only; industry benchmarks vary widely and should not be the sole basis for decisions",
        "note_equity": "Opening equity includes accumulated retained profits; the direct equity movements are the period movements on equity accounts",
        "note_no_cash": "No cash account",
        "note_cash_recon": "Closing cash must agree with the cash balance in the statement of financial position",
        "item": "Item", "current": "Current period", "prior": "Prior period",
        "assets": "Assets", "current_assets": "Current assets",
        "non_current_assets": "Non-current assets", "total_assets": "Total assets",
        "equity_liabilities": "Equity and Liabilities", "equity": "Equity",
        "total_equity": "Total equity", "liabilities": "Liabilities",
        "current_liabilities": "Current liabilities",
        "non_current_liabilities": "Non-current liabilities",
        "total_liabilities": "Total liabilities",
        "revenue": "Revenue", "cost_of_sales": "Cost of sales", "gross_profit": "Gross profit",
        "other_income": "Other income", "other_gains": "Other gains／(losses)",
        "operating_expenses": "Operating expenses", "finance_costs": "Finance costs",
        "profit_before_tax": "Profit before tax", "tax": "Tax",
        "net_profit": "Profit for the period",
        "oci": "Other comprehensive income",
        "total_comprehensive": "Total comprehensive income for the period",
        "fx_translation": "Exchange differences on translation",
        "opening_equity": "Equity at beginning of period",
        "profit_for_period": "Profit for the period",
        "direct_movements": "Direct movements in equity (capital / dividends)",
        "closing_equity": "Equity at end of period",
        "operating": "Operating activities", "investing": "Investing activities",
        "financing": "Financing activities",
        "net_change": "Net increase in cash and cash equivalents",
        "closing_cash": "Cash and cash equivalents at end of period",
        "check_assets": "Check: Assets {a} − Equity and liabilities {b} = {d}",
        "balanced": "Balanced", "unbalanced": "Not balanced — investigate",
        "account": "Code", "name": "Name", "code": "Code",
        "debit": "Debit", "credit": "Credit", "balance": "Balance",
        "account_name": "Account", "amount": "Amount",
        "currency": "Currency", "date": "Date", "description": "Description",
        "generated": "Generated by LtBooks in accordance with HKFRS; data from posted journal entries.",

        "management_report": "Management Report",
        "trial_balance": "Trial Balance",
        "cash_flow_report": "Statement of Cash Flows",
        "aging_report": "Aging Analysis",
        "bank_balances": "Bank Account Balances",
        "fx_report": "Exchange Gain or Loss",
        "general_ledger": "General Ledger",
        "daybook": "Journal Day Book",
        "sales_detail": "Sales Details",
        "purchase_detail": "Purchase Details",
        "ratios": "Financial Ratios",
        "customer_balances": "Customer Balances",
        "vendor_balances": "Vendor Balances",
        "profits_tax": "Profits Tax Computation",
        "item": "Item", "amount_hkd": "Amount (HKD)", "assessable_profits": "Assessable profits", "two_tier_status": "Two-tiered status", "applicable_rate": "Applicable rate", "tax_payable": "Tax payable", "two_tier_nominated": "Nominated: 8.25% on first HKD 2,000,000, 16.5% thereafter", "two_tier_not_nominated": "Not nominated: 16.5% on the whole amount", "two_tier_undetermined": "Status undetermined; tax is not computed", "basis_posted_entries": "From posted and reversed entries, allocated by entry_date, in HKD",
        "daily": "today",
        "to_date": "As at {date}",
        "copyright": "© {year} LEDU TECH CO., LIMITED · Released under the MIT License",
        "hkfrs15_disclosure": "Revenue Disclosures (HKFRS 15)",
        "basis_of_preparation": "Basis of Preparation", "significant_policies": "Significant Accounting Policies",
    },
}


_EXTRA_LABELS = {
    "zh_cn": {
        "asset": "资产", "liability": "负债", "no_data": "暂无数据",
        "opening_cash": "期初现金及现金等价物",
        "opening_entry_cash": "期内期初分录现金变动（不计入经营活动）",
        "operating_cash_flow": "经营活动带来的现金净额",
        "investing_cash_flow": "投资活动带来的现金净额",
        "financing_cash_flow": "筹资活动带来的现金净额",
        "noncash_adjustment": "非现金调整",
        "working_capital_change": "营运资金变动",
        "account_type_summary": "账户类型摘要",
        "account_type": "账户类型",
        "total": "合计",
        "entry_no": "凭证号",
        "transaction_details": "交易明细",
        "opening_balance": "期初余额",
        "period_total": "本期合计",
        "general_ledger_detail": "详细的总分类账",
        "related_party_title": "关联方交易",
        "related_party_note": "本公司与股东之间的资金往来按无息、无抵押、随时可偿还的条件处理；下列余额已计入财务状况表相应项目。",
        "nature": "性质",
        "balance_hkd": "余额（HKD）",
        "profits_tax_title": "利得税计算表",
        "tax_year_period": "课税年度 {year} · 基期止 {period}",
        "tax_currency_note": "金额单位：港元（HKD）· 依《税务条例》（第112章）编制",
        "accounting_profit": "会计利润",
        "profit_before_tax_accounting": "除税前会计利润",
        "add_nondeductible": "加：不可扣税开支",
        "no_adjustments": "（无调整项）",
        "total_add_back": "加回合计",
        "less_nontaxable": "减：非应课税收入",
        "total_deduct": "扣除合计",
        "adjusted_assessable": "经调整的应评税利润",
        "less_capital_allowances": "减：资本免税额",
        "none_paren": "（无）",
        "assessable_profit": "应评税利润",
        "profits_tax_payable": "应缴利得税",
        "tier1_profit": "首 {cap} 应评税利润 @ {rate}%",
        "tier2_profit": "其余应评税利润 @ {rate}%",
        "less_provisional": "减：已缴暂缴税",
        "balance_payable": "应补缴／（应退税）",
        "two_tier_nominated_status": "已获两级制税率提名",
        "two_tier_not_nominated_status": "未获两级制税率提名",
        "two_tier_undetermined": "两级制税率资格尚未确定",
        "two_tier_eligibility": "两级制税率资格：{label}。",
        "tax_note_profit": "应评税利润为正，按两级制计税",
        "tax_note_loss": "应评税利润为负，属税务亏损，可无限期结转抵销未来年度利润",
        "generated_at": "生成时间 {time}",
        "tax_interim_only": "以下中间数据仅供核对，不含税额",
        "tax_reason_undetermined": "实体两级制税率资格未确定（undetermined）；按规不得自行假定，须先确认资格",
    },
    "zh_hk": {
        "asset": "資產", "liability": "負債", "no_data": "暫無數據",
        "opening_cash": "期初現金及現金等價物",
        "opening_entry_cash": "期內期初分錄現金變動（不計入經營活動）",
        "operating_cash_flow": "經營活動帶來的現金淨額",
        "investing_cash_flow": "投資活動帶來的現金淨額",
        "financing_cash_flow": "籌資活動帶來的現金淨額",
        "noncash_adjustment": "非現金調整",
        "working_capital_change": "營運資金變動",
        "account_type_summary": "賬戶類型摘要",
        "account_type": "賬戶類型",
        "total": "合計",
        "entry_no": "憑證號",
        "transaction_details": "交易明細",
        "opening_balance": "期初餘額",
        "period_total": "本期合計",
        "general_ledger_detail": "詳細的總分類帳",
        "related_party_title": "關聯方交易",
        "related_party_note": "本公司與股東之間的資金往來按無息、無抵押、隨時可償還的條件處理；下列餘額已計入財務狀況表相應項目。",
        "nature": "性質",
        "balance_hkd": "餘額（HKD）",
        "profits_tax_title": "利得稅計算表",
        "tax_year_period": "課稅年度 {year} · 基期止 {period}",
        "tax_currency_note": "金額單位：港元（HKD）· 依《稅務條例》（第112章）編製",
        "accounting_profit": "會計利潤",
        "profit_before_tax_accounting": "除稅前會計利潤",
        "add_nondeductible": "加：不可扣稅開支",
        "no_adjustments": "（無調整項）",
        "total_add_back": "加回合計",
        "less_nontaxable": "減：非應課稅收入",
        "total_deduct": "扣除合計",
        "adjusted_assessable": "經調整的應評稅利潤",
        "less_capital_allowances": "減：資本免稅額",
        "none_paren": "（無）",
        "assessable_profit": "應評稅利潤",
        "profits_tax_payable": "應繳利得稅",
        "tier1_profit": "首 {cap} 應評稅利潤 @ {rate}%",
        "tier2_profit": "其餘應評稅利潤 @ {rate}%",
        "less_provisional": "減：已繳暫繳稅",
        "balance_payable": "應補繳／（應退稅）",
        "two_tier_nominated_status": "已獲兩級制稅率提名",
        "two_tier_not_nominated_status": "未獲兩級制稅率提名",
        "two_tier_undetermined": "兩級制稅率資格尚未確定",
        "two_tier_eligibility": "兩級制稅率資格：{label}。",
        "tax_note_profit": "應評稅利潤為正，按兩級制計稅",
        "tax_note_loss": "應評稅利潤為負，屬稅務虧損，可無限期結轉抵銷未來年度利潤",
        "generated_at": "生成時間 {time}",
        "tax_interim_only": "以下中間數據僅供核對，不含稅額",
        "tax_reason_undetermined": "實體兩級制稅率資格未確定（undetermined）；按規不得自行假定，須先確認資格",
    },
    "en": {
        "asset": "Assets", "liability": "Liabilities", "no_data": "No data",
        "opening_cash": "Cash and cash equivalents at beginning of period",
        "opening_entry_cash": "Cash from opening entries in the period (excluded from operating activities)",
        "operating_cash_flow": "Net cash from operating activities",
        "investing_cash_flow": "Net cash from investing activities",
        "financing_cash_flow": "Net cash from financing activities",
        "noncash_adjustment": "Non-cash adjustment",
        "working_capital_change": "Working capital movement",
        "account_type_summary": "Account Type Summary",
        "account_type": "Account type",
        "total": "Total",
        "entry_no": "Voucher No.",
        "transaction_details": "Transaction details",
        "opening_balance": "Opening balance",
        "period_total": "Total for the period",
        "general_ledger_detail": "General Ledger Detail",
        "related_party_title": "Related party transactions",
        "related_party_note": "Funding between the company and its shareholders is unsecured, interest-free and repayable on demand. The balances below are included in the corresponding statement of financial position captions.",
        "nature": "Nature",
        "balance_hkd": "Balance (HKD)",
        "profits_tax_title": "Profits Tax Computation",
        "tax_year_period": "Year of assessment {year} · Basis period ended {period}",
        "tax_currency_note": "Amounts in HKD · Prepared under the Inland Revenue Ordinance (Cap. 112)",
        "accounting_profit": "Accounting profit",
        "profit_before_tax_accounting": "Accounting profit before tax",
        "add_nondeductible": "Add: non-deductible expenses",
        "no_adjustments": "(none)",
        "total_add_back": "Total add-backs",
        "less_nontaxable": "Less: non-taxable income",
        "total_deduct": "Total deductions",
        "adjusted_assessable": "Adjusted assessable profits",
        "less_capital_allowances": "Less: capital allowances",
        "none_paren": "(none)",
        "assessable_profit": "Assessable profits",
        "profits_tax_payable": "Profits tax payable",
        "tier1_profit": "First {cap} of assessable profits @ {rate}%",
        "tier2_profit": "Remainder of assessable profits @ {rate}%",
        "less_provisional": "Less: provisional tax paid",
        "balance_payable": "Tax payable / (refundable)",
        "two_tier_nominated_status": "Nominated for two-tiered rates",
        "two_tier_not_nominated_status": "Not nominated for two-tiered rates",
        "two_tier_undetermined": "Two-tiered rate status not yet determined",
        "two_tier_eligibility": "Two-tiered rate status: {label}.",
        "tax_note_profit": "Assessable profits are positive; two-tiered rates apply",
        "tax_note_loss": "Assessable profits are negative (tax loss); may be carried forward indefinitely",
        "generated_at": "Generated {time}",
        "tax_interim_only": "Interim figures are for reconciliation only; no tax amount is computed",
        "tax_reason_undetermined": "Two-tiered rate eligibility is undetermined; it must be confirmed before tax can be computed",
    },
}
for _l, _kv in _EXTRA_LABELS.items():
    LABELS[_l].update(_kv)


def label(lang: str, key: str) -> str:
    l = lang if lang in LABELS else DEFAULT_LANG
    # 不把简中偷偷塞进英文/繁中 PDF；新增标签必须同时补齐三语。
    return LABELS[l].get(key) or key


def labels(lang: str) -> dict:
    return LABELS.get(lang) if lang in LABELS else LABELS[DEFAULT_LANG]


# 通用报表列名：键为简体中文（代码既有写法），值为 (香港繁体, 英文)
COLUMN_I18N = {
    "科目": ("科目", "Code"), "名称": ("名稱", "Name"), "编码": ("編碼", "Code"),
    "科目名称": ("科目名稱", "Account"), "类别": ("類別", "Category"),
    "借方": ("借方", "Debit"), "贷方": ("貸方", "Credit"), "余额": ("餘額", "Balance"),
    "项目": ("項目", "Item"), "金额": ("金額", "Amount"),
    "比率": ("比率", "Ratio"), "数值": ("數值", "Value"), "计算式": ("計算式", "Formula"),
    "单位": ("單位", "Unit"),
    "币种": ("幣種", "Currency"), "日期": ("日期", "Date"), "账户": ("賬戶", "Account"),
    "活动": ("活動", "Activity"), "来源": ("來源", "Source"), "摘要": ("摘要", "Description"),
    "状态": ("狀態", "Status"), "分录号": ("分錄號", "Entry No."),
    "借方合计": ("借方合計", "Total Debit"),
    "原币合计": ("原幣合計", "Total (Original)"), "折 HKD": ("折 HKD", "In HKD"),
    "原币余额": ("原幣餘額", "Balance (Original)"), "折HKD": ("折HKD", "In HKD"),
    "客户": ("客戶", "Customer"), "供应商": ("供應商", "Vendor"),
    "张数": ("張數", "Count"), "发票数": ("發票數", "Invoices"), "账单数": ("賬單數", "Bills"),
    "价税合计": ("價稅合計", "Gross"), "已开票": ("已開票", "Invoiced"),
    "已收款": ("已收款", "Received"), "未收": ("未收", "Outstanding"),
    "已收票": ("已收票", "Billed"), "已付款": ("已付款", "Paid"), "未付": ("未付", "Outstanding"),
    "不含税": ("不含稅", "Net"), "税额": ("稅額", "Tax"),
    "帐户类型": ("賬戶類型", "Account type"), "账户类型": ("賬戶類型", "Account type"),
    "借项": ("借項", "Debit"), "贷项": ("貸項", "Credit"),
    "交易明细": ("交易明細", "Transaction details"), "凭证号": ("憑證號", "Voucher No."),
    "说明": ("說明", "Description"), "性质": ("性質", "Nature"),
    "本期": ("本期", "Current period"), "上年": ("上年", "Prior year"),
    "变动": ("變動", "Change"), "有效期至": ("有效期至", "Valid until"),
    "原因": ("原因", "Reason"), "预计日期": ("預計日期", "Expected date"),
}


def column(lang: str, cn: str) -> str:
    pair = COLUMN_I18N.get(cn)
    if not pair:
        return cn
    return pair[1] if lang == "en" else (pair[0] if lang == "zh_hk" else cn)

# 报表正文里的行标签（段名、小计、状态词）。键为简体中文写法。
ROW_I18N = {
    "合计": ("合計", "Total"), "平衡": ("平衡", "Balanced"), "不平衡": ("不平衡", "Not balanced"),
    "净变动": ("淨變動", "Net change"), "勾稽差额": ("勾稽差額", "Check difference"),
    "收入": ("收入", "Revenue"), "销售成本": ("銷售成本", "Cost of sales"),
    "其他收入": ("其他收入", "Other income"),
    "其他收益／（亏损）": ("其他收益／（虧損）", "Other gains/(losses)"),
    "经营费用": ("經營費用", "Operating expenses"),
    "财务费用": ("財務費用", "Finance costs"), "税项": ("稅項", "Tax"),
    "毛利": ("毛利", "Gross profit"),
    "除税前溢利": ("除稅前溢利", "Profit before tax"),
    "本期溢利": ("本期溢利", "Profit for the period"),
    "资产": ("資產", "Assets"), "负债": ("負債", "Liabilities"), "权益": ("權益", "Equity"),
    "经营活动": ("經營活動", "Operating activities"),
    "投资活动": ("投資活動", "Investing activities"),
    "筹资活动": ("籌資活動", "Financing activities"),
    "期初现金": ("期初現金", "Cash at beginning"),
    "期末现金": ("期末現金", "Cash at end"),
    "期初现金及现金等价物": ("期初現金及現金等價物", "Cash and cash equivalents at beginning of period"),
    "期末现金余额": ("期末現金餘額", "Closing cash balance"),
    "本期净利／（亏损）": ("本期淨利／（虧損）", "Profit / (loss) for the period"),
    "经营活动带来的现金净额": ("經營活動帶來的現金淨額", "Net cash from operating activities"),
    "投资活动带来的现金净额": ("投資活動帶來的現金淨額", "Net cash from investing activities"),
    "融资活动带来的现金净额": ("籌資活動帶來的現金淨額", "Net cash from financing activities"),
    "现金净变动": ("現金淨變動", "Net change in cash"),
    "期初余额": ("期初餘額", "Opening balance"),
    "期末余额": ("期末餘額", "Closing balance"),
    "交易明细": ("交易明細", "Transaction details"),
    "凭证号": ("憑證號", "Voucher No."),
    "暂无数据": ("暫無數據", "No data"),
    # 财务比率
    "流动比率": ("流動比率", "Current ratio"),
    "速动比率": ("速動比率", "Quick ratio"),
    "资产负债率": ("資產負債率", "Liabilities to assets"),
    "毛利率": ("毛利率", "Gross margin"),
    "净利率": ("淨利率", "Net margin"),
    "费用率": ("費用率", "Expense ratio"),
    "成本率": ("成本率", "Cost ratio"),
    "权益回报率": ("權益回報率", "Return on equity"),
    "应收周转天数": ("應收週轉天數", "Receivable days"),
    "流动资产 ÷ 流动负债": ("流動資產 ÷ 流動負債", "Current assets / current liabilities"),
    "（流动资产 − 存货）÷ 流动负债": ("（流動資產 − 存貨）÷ 流動負債",
                                      "(Current assets - inventory) / current liabilities"),
    "总负债 ÷ 总资产": ("總負債 ÷ 總資產", "Total liabilities / total assets"),
    "毛利 ÷ 收入": ("毛利 ÷ 收入", "Gross profit / revenue"),
    "净利 ÷ 收入": ("淨利 ÷ 收入", "Net profit / revenue"),
    "经营费用 ÷ 收入": ("經營費用 ÷ 收入", "Operating expenses / revenue"),
    "销售成本 ÷ 收入": ("銷售成本 ÷ 收入", "Cost of sales / revenue"),
    "净利 ÷ 期末权益": ("淨利 ÷ 期末權益", "Net profit / closing equity"),
    "应收账款 ÷ 收入 × 365": ("應收賬款 ÷ 收入 × 365", "Receivables / revenue x 365"),
    "倍": ("倍", "x"), "天": ("天", "days"),
    "正数为汇兑收益，负数为汇兑损失": ("正數為匯兌收益，負數為匯兌損失",
                                  "Positive = exchange gain, negative = exchange loss"),
    "按客户与币种分列；HKD 合计仅取折算列": ("按客戶與幣種分列；HKD 合計僅取折算列",
                                    "Split by customer and currency; the HKD total uses the translated column only"),
    "按供应商与币种分列；HKD 合计仅取折算列": ("按供應商與幣種分列；HKD 合計僅取折算列",
                                      "Split by vendor and currency; the HKD total uses the translated column only"),
    "应收账款": ("應收賬款", "Trade receivables"),
    "应付账款": ("應付賬款", "Trade payables"),
    "合同资产": ("合同資產", "Contract assets"),
    "合同负债": ("合同負債", "Contract liabilities"),
    "预付费用": ("預付費用", "Prepayments"),
    "其他流动资产": ("其他流動資產", "Other current assets"),
    "其他流动负债": ("其他流動負債", "Other current liabilities"),
    "存货": ("存貨", "Inventories"),
    "其他应收款": ("其他應收款", "Other receivables"),
    "其他应付款": ("其他應付款", "Other payables"),
    "应计费用": ("應計費用", "Accrued expenses"),
    "可收回税项": ("可收回稅項", "Tax recoverable"),
    "应付税项": ("應付稅項", "Tax liabilities"),
    "信用卡": ("信用卡", "Credit cards"),
    "其他（未归类）": ("其他（未歸類）", "Other (unclassified)"),
    "所有者权益": ("所有者權益", "Equity"),
    "现金": ("現金", "Cash"), "银行": ("銀行", "Bank"),
    "库存": ("庫存", "Inventories"), "固定资产": ("固定資產", "Fixed assets"),
    "非流动资产": ("非流動資產", "Non-current assets"),
    "非流动负债": ("非流動負債", "Non-current liabilities"),
    "其他负债": ("其他負債", "Other liabilities"),
    "营业费用": ("營業費用", "Operating expenses"),
    "HKD 折算合计": ("HKD 折算合計", "Total in HKD"),
}


# 数据库存储的固定枚举值。仅做精确匹配，避免改写客户名称或自填摘要。
_FIXED_VALUE_I18N = {
    "manual": ("手工录入", "手工錄入", "Manual entry"),
    "journal": ("日记账", "日記賬", "Journal"),
    "invoice": ("发票", "發票", "Invoice"),
    "bill": ("账单", "賬單", "Bill"),
    "payment": ("付款", "付款", "Payment"),
    "payment_received": ("收款", "收款", "Receipt"),
    "payment_made": ("付款", "付款", "Payment"),
    "opening": ("期初", "期初", "Opening"),
    "expense": ("费用", "費用", "Expense"),
    "transfer": ("转账", "轉賬", "Transfer"),
    "bank_line": ("银行交易", "銀行交易", "Bank transaction"),
    "fx_reval": ("汇兑重估", "匯兌重估", "FX revaluation"),
    "contract_revenue": ("合同收入", "合約收入", "Contract revenue"),
    "settlement": ("结算", "結算", "Settlement"),
    "adjustment": ("调整", "調整", "Adjustment"),
    "reversal": ("冲销", "沖銷", "Reversal"),
    "draft": ("草稿", "草稿", "Draft"),
    "posted": ("已过账", "已過賬", "Posted"),
    "reversed": ("已冲销", "已沖銷", "Reversed"),
    "void": ("已作废", "已作廢", "Void"),
    "converted": ("已转换", "已轉換", "Converted"),
    "asset": ("资产", "資產", "Asset"),
    "liability": ("负债", "負債", "Liability"),
    "equity": ("权益", "權益", "Equity"),
    "revenue": ("收入", "收入", "Revenue"),
    "cogs": ("销售成本", "銷售成本", "Cost of sales"),
}
_FIXED_VALUE_ALIASES = {
    translated: key
    for key, translations in _FIXED_VALUE_I18N.items()
    for translated in translations
}


# 银行账户显示名（历史数据是中文），PDF 里按语言替换
_BANK_I18N = {
    "汇丰银行": ("滙豐銀行", "HSBC"), "恒生银行": ("恒生銀行", "Hang Seng Bank"),
    "中国银行": ("中國銀行", "Bank of China"), "渣打银行": ("渣打銀行", "Standard Chartered"),
    "往来账户": ("往來賬戶", "Current Account"), "储蓄账户": ("儲蓄賬戶", "Savings Account"),
    "外币账户": ("外幣賬戶", "Foreign Currency Account"),
    "美元账户": ("美元賬戶", "USD Account"), "港币账户": ("港幣賬戶", "HKD Account"),
    "人民币账户": ("人民幣賬戶", "CNY Account"), "加元账户": ("加元賬戶", "CAD Account"),
    "银行账户": ("銀行賬戶", "Bank Account"), "账户": ("賬戶", "Account"),
}


# 系统自动生成的凭证摘要（键为简体中文句式）。导出时按语言替换。
# 用户手写的摘要不会命中这些固定句式，保持原样。
# 每项为 (正则, (繁体模板, 英文模板))，模板用 {0}/{1} 引用捕获组。
_DESC_RULES = [
    # 月度计提
    (r"^(\d{4}-\d{2}) 薪酬及强积金$",
     ("{0} 薪酬及強積金", "Payroll and MPF for {0}")),
    (r"^(\d{4}-\d{2}) 固定资产折旧$",
     ("{0} 固定資產折舊", "Depreciation of fixed assets for {0}")),
    (r"^(\d{4})/(\d{2}) 年度利得税计提$",
     ("{0}/{1} 年度利得稅計提", "Profits tax accrual for {0}/{1}")),
    (r"^(\d{4})/(\d{2}) 年度审计费计提$",
     ("{0}/{1} 年度審計費計提", "Audit fee accrual for {0}/{1}")),
    (r"^(\d{4}) 年度审计费计提$",
     ("{0} 年度審計費計提", "Audit fee accrual for {0}")),
    (r"^(\d{4}) 年度利得税计提$",
     ("{0} 年度利得稅計提", "Profits tax accrual for {0}")),
    (r"^董事贷款利息计提$",
     ("董事貸款利息計提", "Interest accrual on director's loan")),
    (r"^董事貸款利息計提$",
     ("董事貸款利息計提", "Interest accrual on director's loan")),
    (r"^期初余额：银行、股本及保留盈利$",
     ("期初餘額：銀行、股本及保留盈利",
      "Opening balances: bank, share capital and retained earnings")),
    # 单据确认 / 收付款
    (r"^发票 (\S+) 确认$", ("發票 {0} 確認", "Invoice {0} recognised")),
    (r"^发票 (\S+)$", ("發票 {0}", "Invoice {0}")),
    (r"^应付董事贷款$", ("應付董事貸款", "Director's loan payable")),
    (r"^应付 (.+)$", ("應付 {0}", "Payable to {0}")),
    (r"^董事贷款利息$", ("董事貸款利息", "Interest on director's loan")),
    (r"^董事貸款利息$", ("董事貸款利息", "Interest on director's loan")),
    (r"^采购发票 (.+)$", ("採購發票 {0}", "Purchase invoice {0}")),
    (r"^收款 (\S+)$", ("收款 {0}", "Receipt {0}")),
    (r"^付款 (\S+)$", ("付款 {0}", "Payment {0}")),
    (r"^转账 (\S+)$", ("轉賬 {0}", "Transfer {0}")),
    # 分录行的固定说明
    (r"^期初银行存款$", ("期初銀行存款", "Opening bank balance")),
    (r"^银行支付$", ("銀行支付", "Bank payment")),
    (r"^银行收款$", ("銀行收款", "Bank receipt")),
    (r"^折旧费用$", ("折舊費用", "Depreciation expense")),
    (r"^累计折旧$", ("累計折舊", "Accumulated depreciation")),
    (r"^员工薪酬$", ("員工薪酬", "Employee salaries")),
    (r"^雇主强积金$", ("僱主強積金", "Employer's MPF contributions")),
    (r"^审计费$", ("審計費", "Audit fee")),
    (r"^应计费用$", ("應計費用", "Accrued expenses")),
    (r"^利得税$", ("利得稅", "Profits tax")),
    (r"^应交税项$", ("應交稅項", "Tax payable")),
    (r"^股本$", ("股本", "Share capital")),
    (r"^保留盈利$", ("保留盈利", "Retained earnings")),
]


def cell(lang: str, text: str) -> str:
    """报表正文单元格/行标签的翻译。未收录的原样返回。"""
    if not isinstance(text, str):
        return text
    key = text.strip()
    fixed_key = key if key in _FIXED_VALUE_I18N else _FIXED_VALUE_ALIASES.get(key)
    if fixed_key:
        values = _FIXED_VALUE_I18N[fixed_key]
        return values[2] if lang == "en" else (values[1] if lang == "zh_hk" else values[0])
    pair = ROW_I18N.get(key)
    if pair is None:
        pair = COLUMN_I18N.get(key)
    if pair is None:
        # 早期系统生成过繁体摘要；简体中文导出时统一回简体，避免同一表格简繁混杂。
        if lang == "zh_cn":
            legacy_cn = {"董事貸款利息計提": "董事贷款利息计提",
                         "董事貸款利息": "董事贷款利息"}
            if text in legacy_cn:
                return legacy_cn[text]
        # 系统生成的凭证摘要在导出时按语言显示（用户手写摘要不含这些固定句式，保持原样）
        if lang in ("en", "zh_hk") and re.search(r"[\u4e00-\u9fff]", text):
            for pat, (hk, en) in _DESC_RULES:
                mm = re.match(pat, text)
                if mm:
                    tpl = en if lang == "en" else hk
                    return tpl.format(*mm.groups())
        # 「非现金调整：xxx」「营运资金变动：xxx」这类前缀 + 数据，先换前缀
        for pre, hk, en in (("非现金调整：", "非現金調整：", "Non-cash adjustment: "),
                            ("营运资金变动：", "營運資金變動：", "Working capital movement: ")):
            if text.startswith(pre):
                tail = cell(lang, text[len(pre):])
                return (en if lang == "en" else (hk if lang == "zh_hk" else pre)) + tail
        # 银行账户名是历史中文数据：按已知词替换，避免英文报表里出现中文
        out = text
        for cn, (hk, en) in _BANK_I18N.items():
            if cn in out:
                out = out.replace(cn, en if lang == "en" else (hk if lang == "zh_hk" else cn))
        return out
    return pair[1] if lang == "en" else (pair[0] if lang == "zh_hk" else text)


_PDF_ERROR_I18N = {
    "没有可打印的凭证": ("沒有可列印的憑證", "No vouchers available to print"),
    "发票不存在": ("發票不存在", "Invoice not found"),
    "账单不存在": ("賬單不存在", "Bill not found"),
    "报价单不存在": ("報價單不存在", "Quotation not found"),
    "贷记单不存在": ("貸記單不存在", "Credit note not found"),
    "订单不存在": ("訂單不存在", "Order not found"),
    "没有启用的实体": ("沒有啟用的實體", "No active entity"),
}


def pdf_error(lang: str, text: str) -> str:
    """PDF 接口的固定错误文案按请求语言输出，动态参数保持原样。"""
    if lang == "zh_cn" or not isinstance(text, str):
        return text
    prefix = "不支持的报表类型："
    if text.startswith(prefix):
        kind = text[len(prefix):]
        return (f"Unsupported report type: {kind}" if lang == "en"
                else f"不支援的報表類型：{kind}")
    pair = _PDF_ERROR_I18N.get(text)
    if not pair:
        return text
    return pair[1] if lang == "en" else pair[0]


# 年度 PDF 包 MANIFEST 的三语文案；文件名保持英文以利跨平台，说明文字随语言。
PACK_MANIFEST = {
    "zh_cn": {
        "title": "{entity} — {year} 年度报表包",
        "generated": "生成于 {date}  语言={lang}",
        "fs_note": "损益表 · 资产负债表 · 现金流量 · 权益变动 · 附注",
        "notes": "说明：",
        "note1": "· 数字来自已过账和已冲销分录，按凭证日期归期。",
        "note2": "· 单据与单张导出使用同一模板。",
        "note3": "· 由确定性代码生成，无估算。",
        "invoices_unit": "{n} 张销售单",
        "bills_unit": "{n} 张采购单",
        "failed": "失败",
    },
    "zh_hk": {
        "title": "{entity} — {year} 年度報表包",
        "generated": "生成於 {date}  語言={lang}",
        "fs_note": "損益表 · 資產負債表 · 現金流量 · 權益變動 · 附註",
        "notes": "說明：",
        "note1": "· 數字來自已過賬和已沖銷分錄，按憑證日期歸期。",
        "note2": "· 單據與單張匯出使用同一範本。",
        "note3": "· 由確定性代碼生成，無估算。",
        "invoices_unit": "{n} 張銷售單",
        "bills_unit": "{n} 張採購單",
        "failed": "失敗",
    },
    "en": {
        "title": "{entity} — {year} annual pack",
        "generated": "generated {date}  lang={lang}",
        "fs_note": "P&L / position / cash flow / equity / notes",
        "notes": "Notes:",
        "note1": "· Figures come from posted and reversed entries, by entry_date.",
        "note2": "· Documents use the same template as single-document export.",
        "note3": "· Generated by deterministic code; no estimates.",
        "invoices_unit": "{n} invoices",
        "bills_unit": "{n} bills",
        "failed": "FAILED",
    },
}
