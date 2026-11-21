# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""PDF 固定界面文案的三语回归测试；只生成内存 HTML，不访问数据库。"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 核心模块只声明数据库驱动依赖；本测试不连接数据库，缺驱动时用最小桩隔离。
try:
    import pymysql  # noqa: F401
except ModuleNotFoundError:
    pymysql = types.ModuleType("pymysql")
    cursors = types.ModuleType("pymysql.cursors")
    cursors.DictCursor = type("DictCursor", (), {})
    pymysql.cursors = cursors
    pymysql.connect = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("PDF i18n tests must not connect to a database"))
    sys.modules["pymysql"] = pymysql
    sys.modules["pymysql.cursors"] = cursors

from core import financial_analysis, i18n, pdf, pdf_reports  # noqa: E402


LANGS = ("zh_cn", "zh_hk", "en")
ENTITY = {
    "entity_name": "Acme Limited",
    "legal_name": "Acme Limited",
    "functional_currency": "HKD",
    "email": "info@example.com",
    "phone": "+852 1234 5678",
    "website": "example.com",
}
BANK = {
    "account_holder": "Acme Limited",
    "bank_name": "Example Bank",
    "bank_code": "001",
    "swift_code": "EXAMPLEHK",
    "account_number": "123456789",
    "bank_address": "1 Example Road",
}


def invoice_fixture():
    return {
        "invoice_no": "INV-001", "status": "posted", "supplier_name": "Customer A",
        "invoice_date": "2026-11-01", "revenue_recognition_date": "2026-11-01",
        "currency": "USD", "amount_original": 100, "tax_original": 5,
        "gross_original": 105, "amount_functional": 780, "tax_functional": 39,
        "fx_rate": 7.8, "fx_rate_date": "2026-11-01", "lines": [],
    }


def bill_fixture():
    return {
        "bill_no": "BILL-001", "status": "posted", "vendor_name": "Vendor A",
        "date": "2026-11-01", "due_date": "2026-11-30", "currency": "HKD",
        "amount": 100, "tax_amount": 5, "gross_original": 105, "lines": [],
    }


def pl_fixture():
    def section(total=0):
        return {"items": [], "total": total}

    return {
        "revenue": section(100), "costOfSales": section(100), "grossProfit": 0,
        "otherIncome": section(), "otherGains": section(),
        "operatingExpenses": section(), "financeCosts": section(),
        "profitBeforeTax": 0, "taxExpense": section(), "netProfit": 0, "note": "",
    }


class LabelTests(unittest.TestCase):
    def test_all_label_keys_exist_in_every_language(self):
        expected = set(i18n.LABELS["zh_cn"])
        self.assertIn("generated_at", expected)
        for lang in LANGS:
            with self.subTest(lang=lang):
                self.assertEqual(set(i18n.LABELS[lang]), expected)
        self.assertEqual(set(pdf._SD_LABELS), set(LANGS))
        shared = set(pdf._SD_LABELS["en"])
        for lang in LANGS:
            self.assertEqual(set(pdf._SD_LABELS[lang]), shared)
            self.assertEqual(set(pdf.VOUCHER_I18N[lang]), set(pdf.VOUCHER_I18N["en"]))

    def test_missing_label_never_falls_back_to_simplified_chinese(self):
        for lang in ("zh_hk", "en"):
            with self.subTest(lang=lang):
                self.assertEqual(i18n.label(lang, "missing_test_key"), "missing_test_key")

    def test_fixed_source_status_and_category_values_are_localised(self):
        for key, values in i18n._FIXED_VALUE_I18N.items():
            for lang, expected in zip(LANGS, values):
                with self.subTest(key=key, lang=lang):
                    self.assertEqual(i18n.cell(lang, key), expected)
        self.assertEqual(i18n.cell("en", "手工錄入"), "Manual entry")
        self.assertEqual(i18n.cell("zh_cn", "已過賬"), "已过账")

    def test_dynamic_system_labels_translate_only_known_tail_values(self):
        self.assertEqual(i18n.cell("en", "营运资金变动：应收账款"),
                         "Working capital movement: Trade receivables")
        self.assertEqual(i18n.cell("zh_hk", "营运资金变动：应收账款"),
                         "營運資金變動：應收賬款")
        self.assertEqual(i18n.cell("en", "非现金调整：折旧费用"),
                         "Non-cash adjustment: Depreciation expense")
        self.assertEqual(i18n.cell("en", "营运资金变动：客户自填项目"),
                         "Working capital movement: 客户自填项目")
        for lang in LANGS:
            self.assertEqual(i18n.cell(lang, "客户完全自填的摘要"), "客户完全自填的摘要")


class DocumentHtmlTests(unittest.TestCase):
    def test_invoice_fixed_fields_follow_language_without_localize(self):
        files = [{"file_name": "receipt.pdf", "file_size": 128, "sha256_hash": "a" * 64}]
        expected = {
            "zh_cn": ["客户", "发票日期", "收入确认日", "币种", "项目", "数量", "单价",
                      "合价", "税率", "税额", "不含税金额", "原币合计", "折合功能货币",
                      "汇率", "货物/服务", "附件", "文件", "大小", "收款账户", "收款人",
                      "账户号码", "开户银行", "银行地址", "已过账"],
            "zh_hk": ["客戶", "發票日期", "收入確認日", "幣種", "項目", "數量", "單價",
                      "合價", "稅率", "稅額", "不含稅金額", "原幣合計", "折合功能貨幣",
                      "匯率", "貨物/服務", "附件", "文件", "大小", "收款賬戶", "收款人",
                      "賬戶號碼", "開戶銀行", "銀行地址", "已過賬"],
            "en": ["Customer", "Invoice date", "Revenue recognition date", "Currency", "Item",
                   "Qty", "Unit price", "Line total", "Tax rate", "Tax", "Net amount",
                   "Total (original currency)", "In functional currency", "FX rate",
                   "Goods/services", "Attachments", "File", "Size", "Payment account",
                   "Account holder", "Account number", "Bank", "Bank address", "POSTED"],
        }
        forbidden = {
            "zh_cn": ["Generated", "客戶", "發票日期", "稅額", "收款賬戶", "賬戶號碼"],
            "zh_hk": ["Generated", "客户", "发票日期", "税额", "收款账户", "账户号码"],
            "en": ["客户", "客戶", "发票日期", "發票日期", "税额", "稅額", "收款账户",
                   "收款賬戶", "货物/服务", "貨物/服務"],
        }
        for lang in LANGS:
            with self.subTest(lang=lang):
                result = pdf.invoice_html(invoice_fixture(), ENTITY, files, BANK, lang)
                for text in expected[lang]:
                    self.assertIn(text, result)
                for text in forbidden[lang]:
                    self.assertNotIn(text, result)

    def test_bill_fixed_fields_follow_language(self):
        expected = {
            "zh_cn": ["供应商", "到期日", "币种", "项目", "采购", "不含税金额", "税额", "合计"],
            "zh_hk": ["供應商", "到期日", "幣種", "項目", "採購", "不含稅金額", "稅額", "合計"],
            "en": ["Vendor", "Due date", "Currency", "Item", "Purchase", "Net amount", "Tax", "Total"],
        }
        forbidden = {
            "zh_cn": ["Generated", "供應商", "幣種", "採購", "稅額", "合計"],
            "zh_hk": ["Generated", "供应商", "币种", "采购", "税额", "合计"],
            "en": ["供应商", "供應商", "采购", "採購", "税额", "稅額", "合计", "合計"],
        }
        for lang in LANGS:
            with self.subTest(lang=lang):
                result = pdf.bill_html(bill_fixture(), ENTITY, lang)
                for text in expected[lang]:
                    self.assertIn(text, result)
                for text in forbidden[lang]:
                    self.assertNotIn(text, result)

    def test_simple_document_party_and_meta_labels_have_direct_html_fallback(self):
        cases = [
            ("quote", "客户", "有效期至", {"zh_cn": "客户", "zh_hk": "客戶", "en": "Customer"},
             {"zh_cn": "有效期至", "zh_hk": "有效期至", "en": "Valid until"}),
            ("credit", "供应商", "原因", {"zh_cn": "供应商", "zh_hk": "供應商", "en": "Vendor"},
             {"zh_cn": "原因", "zh_hk": "原因", "en": "Reason"}),
            ("order_sales", "客户", "预计日期", {"zh_cn": "客户", "zh_hk": "客戶", "en": "Customer"},
             {"zh_cn": "预计日期", "zh_hk": "預計日期", "en": "Expected date"}),
        ]
        for kind, party_label, meta_label, parties, metas in cases:
            doc = {"no": "D-1", "date": "2026-11-01", "partyLabel": party_label,
                   "party": "Party A", "currency": "HKD", "total": 10,
                   "meta": [(meta_label, "2026-12-31")]}
            for lang in LANGS:
                with self.subTest(kind=kind, lang=lang):
                    result = pdf.simple_doc_html(kind, doc, ENTITY, lang=lang)
                    self.assertIn(parties[lang], result)
                    self.assertIn(metas[lang], result)
                    if lang != "en":
                        self.assertNotIn("Generated", result)

    def test_letterhead_contact_labels_follow_language_and_company_data_is_kept(self):
        entity = dict(ENTITY, legal_name_zh="示例註冊公司",
                      address_line1="1 Example Road", district="Central", region="HK")
        expected = {
            "zh_cn": ("地址", "邮箱", "网址", "电话"),
            "zh_hk": ("地址", "電郵", "網址", "電話"),
            "en": ("Address", "Email", "Website", "Tel"),
        }
        with mock.patch.object(pdf, "_logo_uri", return_value=""):
            for lang in LANGS:
                with self.subTest(lang=lang):
                    result = pdf.letterhead_html(entity, lang)
                    for text in expected[lang]:
                        self.assertIn(text, result)
                    self.assertIn("Acme Limited", result)
                    self.assertIn("Ledu Tech: Leading Technology, Diversified Services", result)

    def test_voucher_source_description_and_amount_words_follow_language(self):
        entry = {"entry_date": "2026-11-21", "entry_no": "J-1", "source_type": "fx_reval",
                 "description": "2026-11 薪酬及强积金", "total_debit": 300, "total_credit": 300}
        lines = [{"line_no": 1, "account_code": "6100", "account_name": "Staff costs",
                  "name_en": "Staff costs", "name_zh_cn": "员工成本", "name_zh_hk": "員工成本",
                  "description": "2026-11 薪酬及强积金", "debit": 300, "credit": 0}]
        expected = {
            "zh_cn": ["记账凭证", "汇兑重估", "薪酬及强积金", "金额大写", "叁佰元整"],
            "zh_hk": ["記賬憑證", "匯兌重估", "薪酬及強積金", "金額大寫", "參佰元整"],
            "en": ["ACCOUNTING VOUCHER", "FX revaluation", "Payroll and MPF for 2026-11",
                   "Amount in words", "Three Hundred only"],
        }
        for lang in LANGS:
            with self.subTest(lang=lang):
                result = pdf.voucher_html(entry, lines, ENTITY, lang=lang)
                for text in expected[lang]:
                    self.assertIn(text, result)
                if lang == "zh_hk":
                    self.assertNotIn("叁佰", result)
                if lang == "en":
                    self.assertNotIn("汇兑重估", result)
                    self.assertNotIn("薪酬及强积金", result)

    def test_user_entered_document_content_is_not_rewritten(self):
        doc = {"no": "C-1", "date": "2026-11-01", "partyLabel": "客户",
               "party": "客戶自填名稱", "currency": "HKD", "total": 0,
               "meta": [("原因", "客户自填原因：保留 Generated 与繁體字")]}
        result = pdf.simple_doc_html("credit", doc, ENTITY, lang="en")
        self.assertIn("客戶自填名稱", result)
        self.assertIn("客户自填原因：保留 Generated 与繁體字", result)


class ReportHtmlTests(unittest.TestCase):
    def tearDown(self):
        pdf_reports.set_lang("en")

    def test_both_footer_builders_use_the_selected_language(self):
        expected = {"zh_cn": "生成时间", "zh_hk": "生成時間", "en": "Generated"}
        for lang in LANGS:
            pdf_reports.set_lang(lang)
            with self.subTest(lang=lang):
                run_footer = pdf_reports._run_footer({"name": "Acme"})
                css = pdf_reports._footer_css({"name": "Acme"})
                self.assertIn(expected[lang], run_footer)
                self.assertIn(expected[lang], css)
                if lang != "en":
                    self.assertNotIn("Generated", run_footer)
                    self.assertNotIn("Generated", css)

    def test_generic_report_translates_comparison_columns_status_source_and_known_rows(self):
        columns = [{"label": "项目"}, {"label": "来源"}, {"label": "状态"},
                   {"label": "本期", "num": True}, {"label": "上年", "num": True},
                   {"label": "变动", "num": True}]
        rows = [["应收账款", "manual", "posted", "1", "2", "3"],
                ["客户自填摘要", "journal", "void", "1", "2", "3"]]
        subtitle = "2026-01-01 至 2026-12-31　·　上年 2025-01-01 ~ 2025-12-31"
        expected = {
            "zh_cn": ["客户自填摘要", "手工录入", "已过账", "日记账", "已作废", "应收账款", "变动"],
            "zh_hk": ["客户自填摘要", "手工錄入", "已過賬", "日記賬", "已作廢", "應收賬款", "變動"],
            "en": ["客户自填摘要", "Manual entry", "Posted", "Journal", "Void",
                   "Trade receivables", "Current period", "Prior year", "Change"],
        }
        for lang in LANGS:
            pdf_reports.set_lang(lang)
            with self.subTest(lang=lang):
                result = pdf_reports.generic_report("Report", subtitle, columns, rows, entity=ENTITY)
                for text in expected[lang]:
                    self.assertIn(text, result)
                if lang == "en":
                    self.assertNotIn("　·　上年 ", result)
                    self.assertNotIn("手工录入", result)

    def test_cash_flow_system_adjustment_labels_are_localised(self):
        expected = {
            "zh_cn": ["非现金调整：折旧费用", "营运资金变动：应收账款"],
            "zh_hk": ["非現金調整：折舊費用", "營運資金變動：應收賬款"],
            "en": ["Non-cash adjustment: Depreciation expense",
                   "Working capital movement: Trade receivables"],
        }
        for lang in LANGS:
            pdf_reports.set_lang(lang)
            fs = {"entity": ENTITY, "periodEnd": "2026-11-21", "statementOfCashFlows": {
                "openingCash": 0, "openingEntryCash": 0, "netProfit": 0,
                "nonCash": [{"account": "折旧费用", "amount": 10}],
                "workingCapital": [{"label": "应收账款", "amount": -10}],
                "operating": 0, "investing": 0, "financing": 0,
                "netChange": 0, "closingCash": 0, "note": "",
            }}
            with self.subTest(lang=lang):
                result = pdf_reports.statement_of_cash_flows(fs)
                for text in expected[lang]:
                    self.assertIn(text, result)

    def test_account_type_fixed_group_and_type_labels_are_localised(self):
        data = {"groups": [
            {"label": "资产", "items": [{"type": "现金", "debit": 1, "credit": 0}]},
            {"label": "所有者权益", "items": [{"type": "所有者权益", "debit": 0, "credit": 1}]},
            {"label": "费用", "items": [{"type": "营业费用", "debit": 1, "credit": 0}]},
        ], "debit": 2, "credit": 1}
        expected = {
            "zh_cn": ["资产", "现金", "所有者权益", "费用", "营业费用"],
            "zh_hk": ["資產", "現金", "所有者權益", "費用", "營業費用"],
            "en": ["Asset", "Cash", "Equity", "Expense", "Operating expenses"],
        }
        for lang in LANGS:
            pdf_reports.set_lang(lang)
            with self.subTest(lang=lang):
                result = pdf_reports.account_type_summary_pdf(data, ENTITY, "2026-11")
                for text in expected[lang]:
                    self.assertIn(text, result)

    def test_general_ledger_translates_known_description_but_keeps_user_text(self):
        data = {"accounts": [{"accountCode": "6100", "accountName": "Staff costs", "opening": 0,
                              "closing": 300, "lines": [
                                  {"date": "2026-11-21", "description": "2026-11 薪酬及强积金",
                                   "sourceType": "fx_reval", "entryNo": "J-1", "debit": 300,
                                   "credit": 0, "balance": 300},
                                  {"date": "2026-11-21", "description": "客户自填总账摘要",
                                   "sourceType": "manual", "entryNo": "J-2", "debit": 0,
                                   "credit": 0, "balance": 300},
                              ]}]}
        pdf_reports.set_lang("en")
        result = pdf_reports.general_ledger_detail_pdf(data, ENTITY, "2026-11-01", "2026-11-30")
        self.assertIn("Payroll and MPF for 2026-11", result)
        self.assertIn("FX Reval.", result)
        self.assertIn("客户自填总账摘要", result)
        self.assertNotIn("2026-11 薪酬及强积金", result)

    def test_profits_tax_notes_are_localised_and_adjustment_user_data_is_kept(self):
        reason = "实体两级制税率资格未确定（undetermined）；按规不得自行假定，须先确认资格"
        result_data = {
            "yearOfAssessment": "2025/26", "period": "2026-03-31", "accountingProfit": 100,
            "addBacks": [{"item_name": "用户税务调整项", "basis_note": "客户自填依据", "amount": 10}],
            "totalAddBack": 10, "deducts": [], "totalDeduct": 0, "adjustedAssessable": 110,
            "capitalAllowances": [], "totalCapitalAllowance": 0, "assessableProfit": 110,
            "computed": False, "twoTierStatus": "undetermined",
            "note": "以下中间数据仅供核对，不含税额", "reason": reason,
        }
        expected = {
            "zh_cn": ["以下中间数据仅供核对，不含税额", reason],
            "zh_hk": ["以下中間數據僅供核對，不含稅額",
                      "實體兩級制稅率資格未確定（undetermined）；按規不得自行假定，須先確認資格"],
            "en": ["Interim figures are for reconciliation only; no tax amount is computed",
                   "Two-tiered rate eligibility is undetermined; it must be confirmed before tax can be computed"],
        }
        for lang in LANGS:
            pdf_reports.set_lang(lang)
            with self.subTest(lang=lang):
                result = pdf_reports.profits_tax_pdf(ENTITY, result_data)
                for text in expected[lang]:
                    self.assertIn(text, result)
                self.assertIn("用户税务调整项", result)
                self.assertIn("客户自填依据", result)


class FinancialAnalysisLabelTests(unittest.TestCase):
    def tearDown(self):
        financial_analysis.reports.set_report_lang("en")

    def test_total_only_cost_of_sales_has_localised_section_label(self):
        bs = {"assets": {"items": [], "total": 0},
              "liabilities": {"items": [], "total": 0},
              "equity": {"items": [], "currentYearProfit": 0, "total": 0},
              "check": {"assetsTotal": 0, "liabilitiesPlusEquity": 0,
                        "difference": 0, "balanced": True}}
        cf = {"closingCash": 0, "operating": 0, "netChange": 0,
              "netProfitReported": 0, "workingCapital": []}
        aging = {"byCurrency": [], "items": []}
        expected = {"zh_cn": "销售成本", "zh_hk": "銷售成本", "en": "Cost of sales"}
        period = {"start": "2026-11-01", "end": "2026-11-21", "dataThrough": "2026-11-21"}
        for lang in LANGS:
            with self.subTest(lang=lang), \
                    mock.patch.object(financial_analysis, "resolve_period", return_value=period), \
                    mock.patch.object(financial_analysis, "_month_slices", return_value=[]), \
                    mock.patch.object(financial_analysis, "_entry_checks", return_value=(0, 0, [])), \
                    mock.patch.object(financial_analysis, "_attach_narrative"), \
                    mock.patch.object(financial_analysis.reports, "profit_and_loss", return_value=pl_fixture()), \
                    mock.patch.object(financial_analysis.reports, "balance_sheet", return_value=bs), \
                    mock.patch.object(financial_analysis.reports, "cash_flow", return_value=cf), \
                    mock.patch.object(financial_analysis.reports, "trial_balance",
                                      return_value={"balanced": True, "difference": 0}), \
                    mock.patch.object(financial_analysis.reports, "aging", return_value=aging):
                report = financial_analysis.build_report(dict(ENTITY, entity_id=1), lang=lang)
            self.assertEqual(len(report["expenseBreakdown"]), 1)
            item = report["expenseBreakdown"][0]
            self.assertEqual(item["section"], "costOfSales")
            self.assertEqual(item["sectionLabel"], expected[lang])
            self.assertEqual(item["label"], expected[lang])


class PdfErrorTests(unittest.TestCase):
    def test_fixed_pdf_errors_follow_request_language(self):
        expected = {
            "zh_cn": ("没有可打印的凭证", "发票不存在", "不支持的报表类型：not-a-kind"),
            "zh_hk": ("沒有可列印的憑證", "發票不存在", "不支援的報表類型：not-a-kind"),
            "en": ("No vouchers available to print", "Invoice not found",
                   "Unsupported report type: not-a-kind"),
        }
        sources = ("没有可打印的凭证", "发票不存在", "不支持的报表类型：not-a-kind")
        for lang in LANGS:
            with self.subTest(lang=lang):
                actual = tuple(i18n.pdf_error(lang, text) for text in sources)
                self.assertEqual(actual, expected[lang])


class PackManifestTests(unittest.TestCase):
    def test_keys_complete_and_format(self):
        keys = {"title", "generated", "fs_note", "notes", "note1", "note2",
                "note3", "invoices_unit", "bills_unit", "failed"}
        for lang in LANGS:
            with self.subTest(lang=lang):
                m = i18n.PACK_MANIFEST[lang]
                self.assertEqual(set(m), keys)
                m["title"].format(entity="X Ltd", year=2026)
                m["generated"].format(date="2026-01-01", lang=lang)
                m["invoices_unit"].format(n=3)
                m["bills_unit"].format(n=3)

    def test_english_manifest_has_no_han(self):
        import re
        han = re.compile(r"[\u4e00-\u9fff]")
        for k, v in i18n.PACK_MANIFEST["en"].items():
            rendered = v.format(entity="X", year=2026, date="2026-01-01",
                                lang="en", n=3)
            self.assertFalse(han.search(rendered),
                             f"en PACK_MANIFEST['{k}'] contains Han characters")


if __name__ == "__main__":
    unittest.main()
