"""Document FX regression tests for quotes, credit notes, posting and email.

Copyright (c) 2026 LEDU TECH CO., LIMITED
SPDX-License-Identifier: MIT
"""
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api as webapi  # noqa: E402


class DocumentFxTests(unittest.TestCase):
    def setUp(self):
        self.entity = {"entity_id": 1, "entity_name": "Example Ltd",
                       "functional_currency": "HKD"}
        self.client = webapi.app.test_client()
        self.admin = {"X-Ledu-Token": webapi.API_TOKEN, "X-Ledu-Role": "admin",
                      "X-Ledu-User": "document-test"}

    def test_identity_fx_does_not_query_rates(self):
        with mock.patch.object(webapi, "query") as query:
            result = webapi._document_fx(self.entity, "HKD", date(2026, 11, 19), "100.00")
        self.assertEqual(result["amount_functional"], Decimal("100.00"))
        self.assertEqual(result["fx_rate"], Decimal("1"))
        self.assertEqual(result["fx_rate_date"], "2026-11-19")
        query.assert_not_called()

    def test_foreign_fx_uses_full_policy_window_and_real_rate_date(self):
        rules = {"fx_policy": {"fallback_to_prior_business_day": True,
                               "fallback": {"max_lookback_days": 12}}}
        rows = [{"rate_date": date(2026, 11, 10), "from_ccy": "USD", "to_ccy": "HKD",
                 "rate": Decimal("7.8"), "source": "test"}]
        with mock.patch("core.service.load_rules", return_value=rules), \
                mock.patch.object(webapi, "query", return_value=rows) as query:
            result = webapi._document_fx(self.entity, "USD", date(2026, 11, 15), "100.00")
        self.assertEqual(result["amount_functional"], Decimal("780.00"))
        self.assertEqual(result["fx_rate"], Decimal("7.8"))
        self.assertEqual(result["fx_rate_date"], "2026-11-10")
        self.assertEqual(query.call_args.args[1],
                         ("USD", "HKD", date(2026, 11, 15), 12,
                          date(2026, 11, 15), 12))

    def test_missing_foreign_rate_is_never_estimated(self):
        rules = {"fx_policy": {"fallback": {"max_lookback_days": 5}}}
        with mock.patch("core.service.load_rules", return_value=rules), \
                mock.patch.object(webapi, "query", return_value=[]):
            with self.assertRaisesRegex(ValueError, "不得估算"):
                webapi._document_fx(self.entity, "USD", date(2026, 11, 15), "100.00")

    def test_credit_source_rejects_cross_currency_allocation(self):
        with mock.patch.object(webapi, "query_one", return_value={"id": 8, "currency": "USD"}):
            with self.assertRaisesRegex(ValueError, "相同币种"):
                webapi._credit_note_source(self.entity, "customer", "HKD", invoice_id=8)
        with mock.patch.object(webapi, "query_one", return_value={"id": 8, "currency": "USD"}):
            source = webapi._credit_note_source(self.entity, "customer", "USD", invoice_id=8)
        self.assertEqual(source["id"], 8)

    def test_quote_create_persists_fx_fields(self):
        fx = {"amount_functional": Decimal("858.00"), "fx_rate": Decimal("7.8"),
              "fx_rate_date": "2026-11-19"}
        conn = mock.MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.lastrowid = 44
        cursor.fetchone.return_value = None
        with mock.patch.object(webapi, "entity_or_404", return_value=self.entity), \
                mock.patch.object(webapi, "_document_fx", return_value=fx), \
                mock.patch.object(webapi, "transaction") as transaction, \
                mock.patch.object(webapi, "append_audit"):
            transaction.return_value.__enter__.return_value = conn
            response = self.client.post("/quotes", json={
                "quoteNo": "Q-44", "customerName": "Customer", "quoteDate": "2026-11-19",
                "currency": "USD", "amountOriginal": 100, "taxOriginal": 10,
            }, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        insert = next(call for call in cursor.execute.call_args_list
                      if "INSERT INTO quotes" in call.args[0])
        params = insert.args[1]
        self.assertEqual(params[13:17], (Decimal("110.00"), Decimal("858.00"),
                                         Decimal("7.8"), "2026-11-19"))

    def test_credit_pdf_receives_real_fx_and_single_language_labels(self):
        credit = {"credit_id": 7, "credit_no": "CN-7", "credit_type": "customer",
                  "party_name": "Customer", "credit_date": date(2026, 11, 19),
                  "currency": "USD", "gross_original": Decimal("110.00"),
                  "amount_functional": Decimal("858.00"), "fx_rate": Decimal("7.8"),
                  "fx_rate_date": date(2026, 11, 18), "reason": "Return"}
        expected = {"zh_cn": "客户", "zh_hk": "客戶", "en": "Customer"}
        for lang, party_label in expected.items():
            with self.subTest(lang=lang), \
                    mock.patch.object(webapi, "entity_or_404", return_value=self.entity), \
                    mock.patch.object(webapi, "query", return_value=[]), \
                    mock.patch.object(webapi, "_simple_doc_pdf", return_value="pdf") as simple:
                self.assertEqual(webapi._credit_note_pdf_response(credit, lang), "pdf")
                doc = simple.call_args.args[1]
                self.assertEqual(doc["partyLabel"], party_label)
                self.assertEqual(doc["amount_functional"], Decimal("858.00"))
                self.assertEqual(doc["fx_rate"], Decimal("7.8"))
                self.assertEqual(doc["functional_currency"], "HKD")

    def test_foreign_credit_post_uses_functional_amounts_for_journal(self):
        credit = {"credit_id": 9, "credit_no": "CN-9", "credit_type": "customer",
                  "party_name": "Customer", "credit_date": date(2026, 11, 19),
                  "currency": "USD", "gross_original": Decimal("110.00"),
                  "tax_original": Decimal("10.00"), "amount_functional": Decimal("220.00"),
                  "fx_rate": Decimal("2.0"), "status": "draft",
                  "source_invoice_id": None, "source_bill_id": None,
                  "revenue_account_code": None}
        conn = mock.MagicMock()
        captured = {}

        def fake_journal(payload):
            captured.update(payload)
            return webapi.J({"entryId": 88, "entryNo": "JE-88"})

        with mock.patch.object(webapi, "entity_or_404", return_value=self.entity), \
                mock.patch.object(webapi, "query_one", return_value=credit), \
                mock.patch.object(webapi, "journal_create_core", side_effect=fake_journal), \
                mock.patch.object(webapi, "transaction") as transaction, \
                mock.patch.object(webapi, "append_audit"):
            transaction.return_value.__enter__.return_value = conn
            response = self.client.post("/credit-notes/9/post", json={}, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(captured["lines"], [
            {"accountCode": "4100", "debit": 200.0},
            {"accountCode": "1130", "credit": 220.0},
            {"accountCode": "2140", "debit": 20.0},
        ])
        self.assertEqual(response.get_json()["entryId"], 88)

    def test_order_pdf_and_email_info_cover_sales_and_purchase(self):
        for direction, doc_type, party_type in (
                ("sales", "sales_order", "customer"),
                ("purchase", "purchase_order", "vendor")):
            order = {"order_id": 5, "direction": direction, "order_no": direction.upper() + "-5",
                     "party_name": "Party", "order_date": date(2026, 11, 19),
                     "expected_date": date(2026, 11, 25), "currency": "USD",
                     "gross_original": Decimal("110.00"), "exchange_rate": Decimal("7.8"),
                     "amount_functional": Decimal("858.00"), "status": "open"}
            with self.subTest(direction=direction), \
                    mock.patch.object(webapi, "entity_or_404", return_value=self.entity), \
                    mock.patch.object(webapi, "query", return_value=[]), \
                    mock.patch.object(webapi, "_simple_doc_pdf", return_value="pdf") as simple:
                self.assertEqual(webapi._order_pdf_response(order, "en"), "pdf")
                self.assertEqual(simple.call_args.args[0],
                                 "order_sales" if direction == "sales" else "order_purchase")
                self.assertEqual(simple.call_args.args[1]["amount_functional"], Decimal("858.00"))
            contact = {"email": "party@example.com"}
            with mock.patch.object(webapi, "entity_or_404", return_value=self.entity), \
                    mock.patch.object(webapi, "query_one", side_effect=[order, contact]):
                response = self.client.get(
                    f"/email/doc-info?docType={doc_type}&docId=5&lang=en", headers=self.admin)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            info = response.get_json()
            self.assertEqual(info["resolvedDocType"], doc_type)
            self.assertEqual(info["partyType"], party_type)
            self.assertEqual(info["partyEmail"], "party@example.com")
            self.assertEqual(info["pdfPath"], "/orders/5/pdf")

    def test_credit_note_email_uses_same_pdf_and_english_template(self):
        credit = {"credit_id": 7, "credit_no": "CN-7", "credit_type": "customer",
                  "party_name": "Customer", "credit_date": date(2026, 11, 19),
                  "currency": "USD", "gross_original": Decimal("110.00"), "status": "draft"}
        conn = mock.MagicMock()
        pdf_response = webapi.app.response_class(b"%PDF-1.7 test", mimetype="application/pdf")
        sent = {"messageId": "message-1", "to": ["customer@example.com"],
                "attachments": ["CN-7.pdf"]}
        with mock.patch.object(webapi, "entity_or_404", return_value=self.entity), \
                mock.patch.object(webapi, "query_one", return_value=credit), \
                mock.patch.object(webapi, "_credit_note_pdf_response", return_value=pdf_response), \
                mock.patch("core.mailer.send", return_value=sent) as send, \
                mock.patch.object(webapi, "transaction") as transaction, \
                mock.patch.object(webapi, "append_audit"):
            transaction.return_value.__enter__.return_value = conn
            response = self.client.post("/email/send-document", json={
                "docType": "credit_note", "docId": 7, "to": "customer@example.com",
                "lang": "en",
            }, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["attachments"], [(b"%PDF-1.7 test", "CN-7.pdf")])
        self.assertEqual(kwargs["subject"], "Credit Note CN-7 — Example Ltd")
        self.assertIn("Amount: USD 110.00", kwargs["body_text"])
        self.assertNotIn("贷记单", kwargs["body_text"])

    def test_draft_update_route_requires_writer_and_passes_id(self):
        denied = self.client.post("/invoices/7/update", json={"subject": "x"},
                                  headers={**self.admin, "X-Ledu-Role": "auditor"})
        self.assertEqual(denied.status_code, 403)
        with mock.patch.object(webapi, "create_invoice",
                               return_value={"invoiceId": 7, "status": "draft"}) as create:
            response = self.client.post("/invoices/7/update",
                                        json={"subject": "修正", "actor": "tester"},
                                        headers=self.admin)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["invoiceId"], 7)
        self.assertEqual(create.call_args.kwargs.get("invoice_id"), 7)

    def test_invoice_pdf_never_prints_internal_notes_or_terms(self):
        from core.pdf import invoice_html

        doc = {
            "invoice_no": "INV-0001", "invoice_date": "2026-11-19",
            "due_date": "2026-12-19", "supplier_name": "Acme Ltd",
            "currency": "HKD", "amount_original": 100, "tax_original": 0,
            "gross_original": 100, "amount_functional": 100, "tax_functional": 0,
            "fx_rate": 1, "status": "draft", "lines": [],
            "customer_notes": "INTERNAL-NOTE-XYZ",
            "terms_conditions": "INTERNAL-TERMS-XYZ",
        }
        html = invoice_html(doc, self.entity, [], None, "en")
        self.assertNotIn("INTERNAL-NOTE-XYZ", html)
        self.assertNotIn("INTERNAL-TERMS-XYZ", html)


if __name__ == "__main__":
    unittest.main()
