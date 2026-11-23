# Copyright (c) 2026 LEDU TECH CO., LIMITED
# SPDX-License-Identifier: MIT
"""财务分析与底层报表的确定性回归测试。

测试不依赖业务账套，也不调用大模型；现金、损益和导出金额均由受控输入计算。
"""
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import financial_analysis, reports  # noqa: E402


def section(label=""):
    return {"label": label, "items": [], "total": 0.0}


def empty_pl():
    return {
        "revenue": section("Revenue"), "costOfSales": section("Cost of sales"),
        "grossProfit": 0.0, "otherIncome": section("Other income"),
        "otherGains": section("Other gains"), "operatingExpenses": section("Operating expenses"),
        "financeCosts": section("Finance costs"), "profitBeforeTax": 0.0,
        "taxExpense": section("Tax expense"), "netProfit": 0.0, "note": "",
    }


def empty_bs():
    return {
        "assets": {"items": [], "total": 0.0},
        "liabilities": {"items": [], "total": 0.0},
        "equity": {"items": [], "currentYearProfit": 0.0, "total": 0.0},
        "check": {"assetsTotal": 0.0, "liabilitiesPlusEquity": 0.0,
                  "difference": 0.0, "balanced": True},
    }


class PeriodAndLanguageTests(unittest.TestCase):
    def tearDown(self):
        reports.set_report_lang("en")

    def test_inception_ends_today_not_last_voucher(self):
        entity = {"entity_id": 1, "fiscal_year_end_mmdd": "03-31"}
        period = financial_analysis.resolve_period(
            entity, "inception", today=date(2026, 11, 19),
            bounds=(date(2025, 1, 1), date(2026, 3, 31)),
        )
        self.assertEqual(period["start"], "2025-01-01")
        self.assertEqual(period["end"], "2026-11-19")
        self.assertEqual(period["dataThrough"], "2026-03-31")

    def test_fiscal_year_uses_start_year_and_company_year_end(self):
        entity = {"entity_id": 1, "fiscal_year_end_mmdd": "03-31"}
        period = financial_analysis.resolve_period(
            entity, "fiscal_year", year="2025", today=date(2026, 11, 19),
            bounds=(date(2025, 1, 1), date(2026, 3, 31)),
        )
        self.assertEqual((period["start"], period["end"]),
                         ("2025-04-01", "2026-03-31"))

    def test_profit_or_loss_fixed_labels_are_localised(self):
        expected = {"zh_cn": "收入", "zh_hk": "收入", "en": "Revenue"}
        with mock.patch.object(reports, "_balances", return_value=[]):
            for lang, label in expected.items():
                reports.set_report_lang(lang)
                result = reports.profit_and_loss(1)
                self.assertEqual(result["revenue"]["label"], label)
                self.assertEqual(result["costOfSales"]["label"], {
                    "zh_cn": "销售成本", "zh_hk": "銷售成本", "en": "Cost of sales",
                }[lang])
        reports.set_report_lang("en")
        self.assertNotRegex(result["note"], r"[\u4e00-\u9fff]")

    def test_report_language_contexts_do_not_leak_between_requests(self):
        reports.set_report_lang("en")

        def render(lang):
            reports.set_report_lang(lang)
            return reports._t("收入", "收入", "Revenue"), reports._name_col()

        contexts = {lang: copy_context() for lang in ("zh_cn", "zh_hk", "en")}
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {lang: pool.submit(contexts[lang].run, render, lang)
                       for lang in contexts}
            values = {lang: future.result() for lang, future in futures.items()}
        self.assertEqual(values["zh_cn"][0], "收入")
        self.assertEqual(values["zh_hk"][0], "收入")
        self.assertEqual(values["en"][0], "Revenue")
        self.assertIn("name_zh_hk", values["zh_hk"][1])
        self.assertIn("name_en", values["en"][1])
        self.assertEqual(reports._t("收入", "收入", "Revenue"), "Revenue")


class CashFlowTests(unittest.TestCase):
    def setUp(self):
        reports.set_report_lang("zh_cn")

    def tearDown(self):
        reports.set_report_lang("en")

    def run_cash_flow(self, *, move=(0, 0), profit=0, noncash=None,
                      working_capital=None, entries=None, lines=None,
                      same_day_opening=(0, 0), later_opening=(0, 0)):
        """以受控账簿输入执行现金流量表，保留真实函数的分类和方向逻辑。"""
        noncash = noncash or []
        working_capital = working_capital or []
        entries = entries or []
        lines = lines or []

        def fake_query(sql, params=None):
            if "SELECT account_code FROM accounts" in sql:
                return [{"account_code": "1000"}]
            if "a.category IN ('expense','cogs')" in sql:
                return noncash
            if "a.fs_line_item IN" in sql and "GROUP BY a.account_code, a.category, a.fs_line_item" in sql:
                return working_capital
            if "SELECT DISTINCT e.entry_id" in sql:
                return entries
            if "SELECT l.entry_id, l.account_code" in sql:
                return lines
            self.fail("Unexpected query: " + sql)

        def fake_query_one(sql, params=None):
            if "a.category IN ('revenue','cogs','expense')" in sql:
                return {"dr": 0, "cr": 0}
            self.assertIn("l.account_code IN", sql)
            if "e.source_type='opening'" in sql and "e.entry_date > %s" in sql:
                return {"dr": later_opening[0], "cr": later_opening[1]}
            if "e.source_type='opening'" in sql and "e.entry_date = %s" in sql:
                return {"dr": same_day_opening[0], "cr": same_day_opening[1]}
            if "e.entry_date >= %s AND e.entry_date <= %s" in sql:
                return {"dr": move[0], "cr": move[1]}
            return {"dr": 0, "cr": 0}

        with mock.patch.object(reports, "query", side_effect=fake_query), \
                mock.patch.object(reports, "query_one", side_effect=fake_query_one), \
                mock.patch.object(reports, "profit_and_loss", return_value={"netProfit": profit}):
            return reports.cash_flow(1, "2025-01-01", "2025-12-31")

    def test_working_capital_uses_one_debit_minus_credit_direction(self):
        result = self.run_cash_flow(
            move=(60, 0),
            working_capital=[
                {"account_code": "1200", "category": "asset", "fs_line_item": "TRADE_RECEIVABLES",
                 "dr": 40, "cr": 0},
                {"account_code": "2100", "category": "liability", "fs_line_item": "TRADE_PAYABLES",
                 "dr": 0, "cr": 100},
            ],
        )
        amounts = {row["label"]: row["amount"] for row in result["workingCapital"]}
        self.assertEqual(amounts, {"应收账款": -40.0, "应付账款": 100.0})
        self.assertEqual(result["operating"], 60.0)
        self.assertNotIn("其他（未归类）", amounts)

    def test_depreciation_is_a_non_cash_adjustment(self):
        result = self.run_cash_flow(
            profit=-50,
            noncash=[{"account_code": "6700", "account_name": "折旧", "category": "expense",
                      "fs_line_item": "DEPRECIATION", "dr": 50, "cr": 0}],
        )
        self.assertEqual(result["nonCashTotal"], 50.0)
        self.assertEqual(result["nonCash"][0]["accountName"], "折旧")
        self.assertEqual(result["workingCapital"], [])
        self.assertEqual(result["operating"], 0.0)

    def test_borrowings_and_fixed_assets_are_financing_and_investing(self):
        result = self.run_cash_flow(
            move=(100, 40),
            entries=[{"entry_id": 1}, {"entry_id": 2}],
            lines=[
                {"entry_id": 1, "account_code": "1000", "debit": 100, "credit": 0,
                 "category": "asset", "fs_line_item": "CASH"},
                {"entry_id": 1, "account_code": "2500", "debit": 0, "credit": 100,
                 "category": "liability", "fs_line_item": "NON_CURRENT_LIABILITIES"},
                {"entry_id": 2, "account_code": "1000", "debit": 0, "credit": 40,
                 "category": "asset", "fs_line_item": "CASH"},
                {"entry_id": 2, "account_code": "1500", "debit": 40, "credit": 0,
                 "category": "asset", "fs_line_item": "NON_CURRENT_ASSETS"},
            ],
        )
        self.assertEqual(result["financing"], 100.0)
        self.assertEqual(result["investing"], -40.0)
        self.assertEqual(result["operating"], 0.0)

    def test_later_opening_entries_are_separate_not_historical_opening_cash(self):
        result = self.run_cash_flow(
            move=(20, 0), same_day_opening=(100, 0), later_opening=(50, 0),
        )
        self.assertEqual(result["openingCash"], 100.0)
        self.assertEqual(result["openingEntryCash"], 50.0)
        self.assertEqual(result["operating"], 20.0)
        self.assertEqual(result["netChange"], 70.0)
        self.assertEqual(result["closingCash"], 170.0)
        self.assertEqual(result["check"], 0.0)

    def test_no_cash_accounts_still_returns_complete_structure(self):
        with mock.patch.object(reports, "query", return_value=[]):
            result = reports.cash_flow(1, "2025-01-01", "2025-12-31")
        expected = {"openingCash", "openingEntryCash", "netProfit", "netProfitReported",
                    "nonCash", "workingCapital", "operating", "investing", "financing",
                    "netChange", "closingCash", "check", "note"}
        self.assertTrue(expected.issubset(result))


class AINarrativeTests(unittest.TestCase):
    def minimal_report(self):
        return {"lang": "en", "entity": {}, "period": {"start": "2025-04-01", "end": "2026-03-31"},
                "kpis": {}, "monthlyTrend": [], "expenseBreakdown": [], "checks": []}

    def test_ai_text_is_qualitative_and_contains_no_figures(self):
        content = json.dumps({"summary": "Performance improved while cash requires attention.",
                              "paragraphs": ["Revenue quality remains the main consideration."]})
        with mock.patch("core.agents.llm.available", return_value=True), \
                mock.patch("core.agents.llm.chat", return_value={"message": {"content": content}, "model": "test-model"}):
            narrative, status, model = financial_analysis._ai_narrative(self.minimal_report())
        self.assertEqual(status, "generated")
        self.assertEqual(model, "test-model")
        self.assertNotRegex(narrative["summary"] + narrative["paragraphs"][0], r"\d")

    def test_ai_figures_are_rejected_and_deterministic_text_is_preserved(self):
        content = json.dumps({"summary": "Revenue rose by twenty percent 20%.", "paragraphs": ["Cash changed."]})
        with mock.patch("core.agents.llm.available", return_value=True), \
                mock.patch("core.agents.llm.chat", return_value={"message": {"content": content}}):
            with self.assertRaises(ValueError):
                financial_analysis._ai_narrative(self.minimal_report())
        report = self.minimal_report()
        deterministic = {"summary": "Deterministic summary", "paragraphs": ["Deterministic detail"]}
        with mock.patch.object(financial_analysis, "_deterministic_narrative", return_value=deterministic), \
                mock.patch.object(financial_analysis, "_ai_narrative", side_effect=ValueError("figures")):
            financial_analysis._attach_narrative(report, True)
        self.assertFalse(report["analysis"]["usedAi"])
        self.assertEqual(report["analysis"]["status"], "failed")
        self.assertEqual(report["analysis"]["summary"], "Deterministic summary")
        self.assertEqual(report["analysis"]["dataSummary"], "Deterministic summary")


class StatementRegressionTests(unittest.TestCase):
    def tearDown(self):
        reports.set_report_lang("en")

    def test_export_filename_fits_audit_object_id(self):
        report = {"period": {"start": "2025-04-01", "end": "2026-03-31"}, "lang": "zh_hk"}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(financial_analysis, "_chart_files", return_value={}), \
                mock.patch.object(financial_analysis, "_docx") as docx:
            docx.side_effect = lambda _report, _charts, path: Path(path).write_bytes(b"PK")
            path = financial_analysis.export_report(report, "docx", directory)
        self.assertLessEqual(len(path.name), 64)
        self.assertTrue(path.name.startswith("Lt-AI-Books-FA-"))

    def test_reclassification_lookup_is_scoped_to_entity(self):
        row = {"account_code": "1100", "account_name": "Contra", "category": "liability",
               "fs_line_item": "TRADE_PAYABLES", "normal_balance": "credit",
               "contra_reclass_target": "2100", "dr": Decimal(0), "cr": Decimal(0),
               "net": Decimal(10)}
        with mock.patch.object(reports, "query_one", return_value=None) as lookup:
            reports._presentation_rows([row], 7)
        self.assertIn("a.entity_id=%s", lookup.call_args.args[0])
        self.assertEqual(lookup.call_args.args[1], (7, "2100"))

    def test_equity_period_profit_starts_on_period_start(self):
        with mock.patch.object(reports, "_account_balance_at", return_value=[]), \
                mock.patch.object(reports, "_profit_between",
                                  return_value={"profit": 0}) as profit:
            reports.equity_changes(1, "2025-04-01", "2026-03-31")
        self.assertEqual(profit.call_args_list, [
            mock.call(1, "0000-01-01", "2025-03-31"),
            mock.call(1, "2025-04-01", "2026-03-31"),
        ])

    def test_complete_statement_pack_uses_selected_period(self):
        entity = {
            "entity_id": 1, "entity_code": "E1", "entity_name": "Entity",
            "functional_currency": "USD", "reporting_framework": "full_hkfrs",
            "two_tier_status": "undetermined",
        }
        with mock.patch.object(reports, "profit_and_loss", return_value=empty_pl()) as pl, \
                mock.patch.object(reports, "balance_sheet", return_value=empty_bs()) as bs, \
                mock.patch.object(reports, "cash_flow", return_value={}) as cf, \
                mock.patch.object(reports, "equity_changes", return_value={}), \
                mock.patch.object(reports, "query", return_value=[]), \
                mock.patch.object(reports, "_related_party_notes", return_value=[]):
            result = reports.financial_statements(1, entity, "2025-04-01", "2026-03-31")
        pl.assert_called_once_with(1, "2025-04-01", "2026-03-31")
        bs.assert_called_once_with(1, "2026-03-31")
        cf.assert_called_once_with(1, "2025-04-01", "2026-03-31")
        self.assertIn("USD", result["notes"]["basis"][1])
        self.assertNotIn("HKD", result["notes"]["basis"][2])

    def test_ratio_receivables_and_payables_sum_functional_currency(self):
        with mock.patch.object(reports, "balance_sheet", return_value=empty_bs()), \
                mock.patch.object(reports, "profit_and_loss", return_value=empty_pl()), \
                mock.patch.object(reports, "trial_balance", return_value={}), \
                mock.patch.object(reports, "aging", side_effect=[
                    {"buckets": {}, "byCurrency": [{"functionalHkd": 100.25}, {"functionalHkd": 20.0}]},
                    {"buckets": {}, "byCurrency": [{"functionalHkd": 80.0}]},
                ]):
            result = reports.financial_ratios(1)
        self.assertEqual(result["basis"]["receivables"], 120.25)
        self.assertEqual(result["basis"]["payables"], 80.0)


if __name__ == "__main__":
    unittest.main()
