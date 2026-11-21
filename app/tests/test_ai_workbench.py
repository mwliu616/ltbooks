"""AI 工作台单据理解与确认链路回归测试。

测试不依赖模型或生产账套：OCR/模型字段提取用桩替代，方向、支出性质、
确认时改单等业务规则执行真实代码，防止销售发票误问支出性质或把未建档
供应商一律当成方向不明。
"""
from __future__ import annotations

import copy
import unittest
from unittest import mock

import api as webapi
from core import doc_analyze
from core.agents import actions, registry, runtime, toolbox, tools_write


class DocAnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.parties = [
            {"id": 11, "name": "Acme Customer Ltd", "kind": "customer"},
            {"id": 22, "name": "Global Vendor Ltd", "kind": "vendor"},
        ]
        patchers = [
            mock.patch.object(doc_analyze, "_rules_map", return_value={}),
            mock.patch.object(doc_analyze, "_party_history", return_value=[]),
            mock.patch.object(doc_analyze, "_entity_names",
                              return_value=["Example Ltd", "示例有限公司"]),
            mock.patch.object(doc_analyze, "_known_parties", return_value=self.parties),
            mock.patch.object(doc_analyze, "_suggest_for_line", side_effect=self._account),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _account(entity_id, line, direction, *, history, learned, party=""):
        description = str(line.get("description") or "line")
        basis = "travel" if any(word in description.lower() for word in ("travel", "hotel")) else "test"
        return {
            "line": description,
            "accountCode": "4100" if direction == "sale" else "6200",
            "accountName": "Revenue" if direction == "sale" else "Expense",
            "side": "credit" if direction == "sale" else "debit",
            "confidence": "high", "basis": basis, "alternatives": [],
        }

    def analyze(self, text, party="", action_type=""):
        extracted = {"amountOriginal": 100, "lines": [{"description": text, "amount": 100}]}
        if action_type:
            extracted["actionType"] = action_type
        return doc_analyze.analyze(text, entity_id=1, party=party, extracted=extracted)

    def test_our_sales_invoice_never_asks_expense_nature(self):
        got = self.analyze(
            "Example Ltd\nINVOICE\nBill To: Acme Customer Ltd\nConsulting service 100.00",
            "Acme Customer Ltd", "create_invoice")
        self.assertEqual((got["direction"], got["docType"]), ("sale", "invoice"))
        self.assertFalse(got["expenseNatureApplicable"])
        self.assertFalse(got["expenseNatureNeedsConfirmation"])
        self.assertNotIn("支出性质", " ".join(got["warnings"]))

    def test_our_company_as_recipient_is_purchase(self):
        got = self.analyze(
            "Global Vendor Ltd\nINVOICE\nBill To: Example Ltd\nOffice service 100.00",
            "Global Vendor Ltd")
        self.assertEqual((got["direction"], got["docType"]), ("purchase", "bill"))
        self.assertEqual(got["expenseNature"], "company")

    def test_registered_customer_and_vendor_determine_direction(self):
        cases = [
            ("Acme Customer Ltd", "INVOICE TO Acme Customer Ltd", "sale"),
            ("Global Vendor Ltd", "SUPPLIER Global Vendor Ltd\nBILL TO Example Ltd", "purchase"),
        ]
        for party, text, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.analyze(text, party)["direction"], expected)

    def test_generic_invoice_and_bill_to_text_does_not_reverse_sale(self):
        got = self.analyze(
            "Example Ltd\nInvoice\nBill To: New Client\nService fee 100.00", "New Client")
        self.assertEqual(got["direction"], "sale")
        self.assertFalse(got["expenseNatureApplicable"])

    def test_generic_invoice_and_bill_to_text_does_not_reverse_purchase(self):
        got = self.analyze(
            "New Supplier\nInvoice\nBill To: Example Ltd\nService 100.00", "New Supplier")
        self.assertEqual(got["direction"], "purchase")

    def test_sales_and_purchase_credit_notes_keep_their_direction(self):
        for party, expected in (("Acme Customer Ltd", "sale"),
                                ("Global Vendor Ltd", "purchase")):
            with self.subTest(expected=expected):
                got = self.analyze(f"CREDIT NOTE\n{party}\nService 100.00", party)
                self.assertEqual(got["direction"], expected)
                self.assertEqual(got["docType"], "credit_note")

    def test_explicit_staff_payment_wins_over_vendor_default(self):
        got = self.analyze(
            "Global Vendor Ltd\n员工垫付，后续报销\nTravel 100.00", "Global Vendor Ltd")
        self.assertEqual(got["expenseNature"], "reimburse")
        self.assertFalse(got["expenseNatureNeedsConfirmation"])

    def test_company_payment_evidence_is_automatic(self):
        got = self.analyze("Paid by company\nSoftware subscription 100.00", "ABC", "create_bill")
        self.assertEqual(got["expenseNature"], "company")

    def test_only_ambiguous_purchase_requires_nature_confirmation(self):
        got = self.analyze("Stationery 100.00", "ABC", "create_bill")
        self.assertEqual(got["expenseNature"], "")
        self.assertTrue(got["expenseNatureNeedsConfirmation"])
        self.assertTrue(any("支出" in warning for warning in got["warnings"]))

    def test_person_and_travel_evidence_suggests_reimbursement(self):
        got = self.analyze("Hotel and travel 100.00", "Chan Tai Man", "create_expense")
        self.assertEqual(got["expenseNature"], "reimburse")

    def test_sales_action_overrides_reimbursement_words(self):
        got = self.analyze("Example Ltd\n报销 INVOICE\nBill To: New Client", "New Client",
                           "create_invoice")
        self.assertFalse(got["expenseNatureApplicable"])
        self.assertEqual(got["expenseNature"], "")


class ActionRuleTests(unittest.TestCase):
    def test_nature_classifier_is_conservative(self):
        self.assertEqual(actions._classify_expense_nature("invoice", "ABC", {})["nature"], "")
        self.assertEqual(actions._classify_expense_nature(
            "invoice", "Global Vendor Ltd", {"partyId": 22})["nature"], "company")
        self.assertEqual(actions._classify_expense_nature(
            "员工垫付", "Global Vendor Ltd", {"partyId": 22})["nature"], "reimburse")

    def test_unregistered_party_alone_does_not_ask_direction(self):
        with mock.patch.object(actions, "match_party", return_value={"matched": False, "name": "ABC"}), \
                mock.patch.object(actions, "_suggest_account", return_value={"code": "6200", "why": "test"}), \
                mock.patch.object(actions, "_dup_check", return_value=[]):
            summary = actions.build_summary("create_bill", {
                "partyName": "ABC", "amountOriginal": 100,
                "directionWhy": "开票方不是本公司，按采购处理", "expenseNature": "",
            }, 1)
        self.assertNotIn("direction", {ask["key"] for ask in summary["asks"]})

    def test_only_real_direction_conflict_asks_direction(self):
        with mock.patch.object(actions, "match_party", return_value={"matched": True, "name": "ABC"}), \
                mock.patch.object(actions, "_suggest_account", return_value={"code": "6200", "why": "test"}), \
                mock.patch.object(actions, "_dup_check", return_value=[]):
            summary = actions.build_summary("create_bill", {
                "partyName": "ABC", "amountOriginal": 100, "expenseNature": "company",
                "directionNeedsConfirmation": True,
            }, 1)
        direction = next(ask for ask in summary["asks"] if ask["key"] == "direction")
        self.assertFalse(any(option.get("rec") for option in direction["options"]))


class ConfirmTests(unittest.TestCase):
    def row(self, kind="create_bill", **payload):
        base = {
            "partyName": "Vendor", "amountOriginal": 100, "taxOriginal": 0,
            "expenseNature": "company", "_supplierName": "Vendor",
            "_customerName": "Customer",
        }
        base.update(payload)
        return {"action_id": 9, "action_type": kind, "title": "Original title",
                "status": "proposed", "payload": base}

    def confirm(self, row, options=None, execute=None):
        conn = mock.MagicMock()
        with mock.patch.object(actions, "get", return_value=row), \
                mock.patch.object(actions, "_execute", side_effect=execute or self._result) as runner, \
                mock.patch.object(actions, "transaction") as transaction, \
                mock.patch.object(actions, "append_audit"), \
                mock.patch.object(actions, "match_party", return_value={"matched": False, "candidates": []}):
            transaction.return_value.__enter__.return_value = conn
            result = actions.confirm(9, "tester", 1, "admin", options=options or {})
        return result, runner

    @staticmethod
    def _result(kind, payload, *args):
        return {"docType": kind, "partyName": payload.get("partyName")}

    def test_ambiguous_nature_cannot_be_confirmed_through_api(self):
        with mock.patch.object(actions, "get", return_value=self.row(expenseNature="")), \
                mock.patch.object(actions, "_execute") as runner:
            with self.assertRaisesRegex(ValueError, "支出性质"):
                actions.confirm(9, "tester", 1, "admin")
        runner.assert_not_called()

    def test_direction_conflict_cannot_be_confirmed_without_answer(self):
        with mock.patch.object(actions, "get",
                               return_value=self.row(directionNeedsConfirmation=True)), \
                mock.patch.object(actions, "_execute") as runner:
            with self.assertRaisesRegex(ValueError, "购销方向"):
                actions.confirm(9, "tester", 1, "admin")
        runner.assert_not_called()

    def test_changing_direction_also_changes_party(self):
        result, runner = self.confirm(self.row(), {"answers": {"direction": "invoice"}})
        payload = runner.call_args.args[1]
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(payload["partyName"], "Customer")
        self.assertEqual(payload["_direction"], "invoice")

    def test_party_pick_keeps_proposal_and_scopes_lookup_to_entity(self):
        party_row = {"id": 7, "name": "Customer Seven"}
        conn = mock.MagicMock()
        with mock.patch.object(actions, "get", return_value=self.row("create_invoice")), \
                mock.patch.object(actions, "query_one", return_value=party_row) as query_one, \
                mock.patch.object(actions, "_execute", side_effect=self._result) as runner, \
                mock.patch.object(actions, "transaction") as transaction, \
                mock.patch.object(actions, "append_audit"):
            transaction.return_value.__enter__.return_value = conn
            result = actions.confirm(9, "tester", 1, "admin",
                                     options={"answers": {"party": "pick:7"}})
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(runner.call_args.args[1]["partyName"], "Customer Seven")
        self.assertIn("entity_id=%s", query_one.call_args.args[0])
        self.assertEqual(query_one.call_args.args[1], (7, 1))

    def test_editing_party_name_does_not_keep_stale_party_id(self):
        _, runner = self.confirm(self.row("create_invoice", partyId=3),
                                 {"fields": {"partyName": "Renamed Customer"}})
        self.assertNotIn("partyId", runner.call_args.args[1])


class ImportApiTests(unittest.TestCase):
    def setUp(self):
        self.client = webapi.app.test_client()
        self.headers = {"X-Ledu-Token": webapi.API_TOKEN, "X-Ledu-Role": "admin",
                        "X-Ledu-User": "ai-import-test"}
        self.entity = {"entity_id": 1, "entity_name": "Example Ltd",
                       "legal_name": "Example Legal Limited", "legal_name_zh": "示例有限公司"}

    def import_document(self, data):
        extracted = {
            "invoiceNo": "INV-1", "invoiceDate": "2026-11-19", "currency": "HKD",
            "amountOriginal": 100, "taxOriginal": 0, "lines": [], **data,
        }
        captured = {}

        def propose(entity_id, action_type, payload, **kwargs):
            captured.update(payload)
            captured["actionType"] = action_type
            return {"actionId": 1, "actionType": action_type, "title": "test",
                    "summary": {"rows": [], "asks": []}, "status": "proposed"}

        def analyze(text, **kwargs):
            action_type = kwargs["extracted"]["actionType"]
            sale = action_type == "create_invoice"
            return {"expenseNature": "" if sale else "company",
                    "expenseNatureWhy": "test",
                    "expenseNatureApplicable": not sale,
                    "expenseNatureNeedsConfirmation": False}

        with mock.patch.object(webapi, "entity_or_404", return_value=self.entity), \
                mock.patch.object(webapi, "set_progress"), \
                mock.patch("core.opening.looks_like_trial_balance", return_value=False), \
                mock.patch("core.ai.looks_like_statement", return_value={"isStatement": False}), \
                mock.patch("core.ai.extract_invoice", return_value=extracted) as extract, \
                mock.patch("core.agents.extractor_learning.guess_vendor", return_value=""), \
                mock.patch("core.agents.extractor_learning.hints_text", return_value=""), \
                mock.patch("core.agents.extractor_learning.apply_rules", side_effect=lambda value, _: value), \
                mock.patch("core.agents.actions.match_party",
                           return_value={"matched": False, "candidates": [], "historyUses": 0}), \
                mock.patch("core.agents.actions.propose", side_effect=propose), \
                mock.patch("core.doc_analyze.analyze", side_effect=analyze):
            response = self.client.post("/ai/import", json={"text": "Invoice text long enough"},
                                        headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(extract.call_count, 1)
        return response.get_json(), captured

    def test_import_our_legal_name_sales_invoice(self):
        body, payload = self.import_document({
            "supplierName": "Example Legal Limited", "customerName": "New Customer",
        })
        self.assertEqual(body["kind"], "invoice")
        self.assertEqual(payload["actionType"], "create_invoice")
        self.assertEqual(payload["partyName"], "New Customer")
        self.assertEqual(payload["expenseNature"], "")

    def test_import_unregistered_supplier_is_not_direction_conflict(self):
        body, payload = self.import_document({
            "supplierName": "Unregistered Supplier", "customerName": "Example Ltd",
        })
        self.assertEqual(body["kind"], "bill")
        self.assertEqual(payload["actionType"], "create_bill")
        self.assertFalse(payload["directionNeedsConfirmation"])
        self.assertIn("受票方是本公司", payload["directionWhy"])


class WorkbenchToolTests(unittest.TestCase):
    """固定工作台指令必须读取正式接口，且查看与写操作严格分离。"""

    def test_read_tools_registered_and_available_to_all_roles(self):
        for name in ("workbench_todo", "period_close_status", "document_detail", "reconciliation_detail"):
            with self.subTest(tool=name):
                self.assertEqual(toolbox.TOOLS[name]["level"], "read")
                for role in ("controller", "accountant", "cashier"):
                    self.assertIn(name, registry.AGENTS[role]["tools"])

    def test_period_close_write_tool_cannot_be_used_for_status(self):
        schema = tools_write.WRITE_TOOLS["run_period_close"]["schema"]
        self.assertEqual(schema["properties"]["action"]["enum"], ["run"])
        self.assertNotIn("list", schema["properties"]["action"]["enum"])

    def test_workbench_todo_filters_and_removes_manual_links(self):
        source = {"items": [
            {"kind": "invoice_draft", "docNo": "INV-D1", "href": "?p=invoice-view&id=1"},
            {"kind": "overdue_ar", "docNo": "INV-9", "dueDate": "2026-10-01",
             "daysOverdue": 49, "agingBucket": "31-60", "href": "?p=invoice-view&id=9"},
            {"kind": "pending_review", "docNo": "bills#2", "href": "?p=bill-view&id=2"},
            {"kind": "bank_unmatched", "docNo": "3 笔", "href": "?p=reconcile"},
        ], "summary": {"total": 4}}
        with mock.patch.object(webapi, "_agent_read_json",
                               side_effect=lambda _: copy.deepcopy(source)):
            overdue = webapi._agent_workbench_todo({"section": "overdue"})
            self.assertEqual(overdue["visibleCount"], 1)
            self.assertEqual(list(overdue)[:2], ["section", "visibleCount"])
            self.assertEqual(overdue["items"][0]["docNo"], "INV-9")
            self.assertEqual(overdue["items"][0]["daysOverdue"], 49)
            self.assertEqual(overdue["items"][0]["agingBucket"], "31-60")
            self.assertNotIn("href", overdue["items"][0])
            self.assertIn("availableActions", overdue["items"][0])

            drafts = webapi._agent_workbench_todo({"section": "draft"})
            self.assertEqual([x["docNo"] for x in drafts["items"]], ["INV-D1"])
            self.assertNotIn("href", drafts["items"][0])

    def test_workbench_todo_rejects_unknown_section(self):
        with self.assertRaisesRegex(ValueError, "section"):
            webapi._agent_workbench_todo({"section": "everything"})

    def test_period_close_status_uses_formal_get_endpoint(self):
        with mock.patch.object(webapi, "_agent_read_json",
                               return_value={"steps": [], "completed": 0}) as read:
            result = webapi._agent_period_close_status({"period": "2026-10"})
        read.assert_called_once_with("/period-close?period=2026-10")
        self.assertIn("只读", result["note"])

    def test_document_detail_returns_formal_document_and_outstanding(self):
        document = {"invoice_no": "INV-100", "status": "posted", "currency": "USD",
                    "due_date": "2025-11-09", "gross_original": 1200, "settled_original": 200,
                    "lines": [{"description": "Consulting", "amount": 1200}]}
        with mock.patch.object(webapi, "entity_or_404", return_value={"entity_id": 1}), \
                mock.patch.object(webapi, "query_one", return_value={"id": 7}) as query, \
                mock.patch.object(webapi, "_agent_read_json", return_value=document) as read:
            result = webapi._agent_document_detail({"kind": "invoice", "docNo": "INV-100"})
        self.assertEqual(query.call_args.args[1], (1, "INV-100"))
        read.assert_called_once_with("/invoices/7")
        self.assertEqual(result["outstanding"], 1000)
        self.assertEqual(result["document"]["lines"], document["lines"])
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(result["dueDate"], "2025-11-09")
        self.assertGreater(result["daysOverdue"], 90)
        self.assertEqual(result["agingBucket"], "91+")
        self.assertTrue(any("export_document_pdf" in x for x in result["availableActions"]))

    def test_document_detail_can_find_bill_without_kind(self):
        with mock.patch.object(webapi, "entity_or_404", return_value={"entity_id": 1}), \
                mock.patch.object(webapi, "query_one",
                                  side_effect=[None, {"id": 22}]), \
                mock.patch.object(webapi, "_agent_read_json",
                                  return_value={"status": "draft", "gross_original": 80,
                                                "settled_original": 0}) as read:
            result = webapi._agent_document_detail({"docNo": "BILL-22"})
        self.assertEqual(result["kind"], "bill")
        read.assert_called_once_with("/bills/22")
        self.assertTrue(any("post_document" in x for x in result["availableActions"]))

    def test_document_detail_rejects_missing_unknown_and_ambiguous_numbers(self):
        with self.assertRaisesRegex(ValueError, "完整单号"):
            webapi._agent_document_detail({})
        with self.assertRaisesRegex(ValueError, "kind"):
            webapi._agent_document_detail({"kind": "quote", "docNo": "Q-1"})
        with mock.patch.object(webapi, "entity_or_404", return_value={"entity_id": 1}), \
                mock.patch.object(webapi, "query_one", return_value=None):
            with self.assertRaisesRegex(ValueError, "找不到"):
                webapi._agent_document_detail({"docNo": "NONE"})
        with mock.patch.object(webapi, "entity_or_404", return_value={"entity_id": 1}), \
                mock.patch.object(webapi, "query_one",
                                  side_effect=[{"id": 1}, {"id": 2}]):
            with self.assertRaisesRegex(ValueError, "补充 kind"):
                webapi._agent_document_detail({"docNo": "SAME-1"})

    def test_reconciliation_detail_restores_requested_batch(self):
        batch = {"batch_id": 12, "bank_account_id": 3, "account_currency": "HKD",
                 "file_name": "november.csv", "period_start": "2026-11-01",
                 "period_end": "2026-11-30", "line_count": 2, "status": "imported",
                 "imported_at": "2026-11-19 09:00:00"}
        base = {"txn_date": "2026-11-10", "bank_ref": "REF", "counterparty_name": "Customer",
                "amount_original": 100, "currency": "HKD", "amount_functional": 100,
                "matched_type": None, "matched_id": None, "match_rule": None,
                "match_confidence": None, "matched_currency": None,
                "matched_amount_at_rate": None, "match_rate": None, "match_rate_date": None,
                "invoice_no": None, "bill_no": None}
        rows = [dict(base, line_id=1, match_status="matched", matched_type="invoice",
                     matched_id=7, match_rule="P1", invoice_no="INV-7"),
                dict(base, line_id=2, match_status="unmatched")]
        with mock.patch.object(webapi, "entity_or_404", return_value={"entity_id": 1}), \
                mock.patch.object(webapi, "query_one", return_value=batch) as get_batch, \
                mock.patch.object(webapi, "query", return_value=rows):
            result = webapi._agent_reconciliation_detail({"batchId": 12})
        self.assertEqual(get_batch.call_args.args[1], (1, 12))
        self.assertEqual(result["batchId"], 12)
        self.assertEqual(result["summary"],
                         {"total": 2, "matched": 1, "unmatched": 1, "pending": 0, "excluded": 0})
        self.assertEqual(result["lines"][0]["matchedDocNo"], "INV-7")
        self.assertIn("availableActions", result["lines"][1])
        self.assertNotIn("href", result["lines"][0])

    def test_reconciliation_detail_handles_empty_and_wrong_entity_batch(self):
        with mock.patch.object(webapi, "entity_or_404", return_value={"entity_id": 1}), \
                mock.patch.object(webapi, "query_one", return_value=None):
            empty = webapi._agent_reconciliation_detail({})
            self.assertIsNone(empty["batchId"])
            self.assertEqual(empty["summary"]["total"], 0)
            with self.assertRaisesRegex(ValueError, "当前实体"):
                webapi._agent_reconciliation_detail({"batchId": 999})
        with self.assertRaisesRegex(ValueError, "整数"):
            webapi._agent_reconciliation_detail({"batchId": "bad"})

    def test_runtime_failure_response_preserves_write_audit(self):
        writes = [{"tool": "create_bill", "ok": False, "error": "validation"}]
        with mock.patch.object(runtime, "_audit", return_value=88):
            result = runtime._fail(1, "controller", "tester", "test", " instruction ",
                                   "failed", 0, 0, "test-model", [], writes)
        self.assertFalse(result["ok"])
        self.assertEqual(result["runId"], 88)
        self.assertEqual(result["writes"], writes)


if __name__ == "__main__":
    unittest.main()
