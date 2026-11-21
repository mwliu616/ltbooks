"""草稿单据编辑、删除与权限回归测试。"""
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api as webapi  # noqa: E402


ENTITY = {"entity_id": 1, "entity_name": "Example Ltd", "functional_currency": "HKD"}


class _Cursor:
    """按草稿删除流程提供最小查询结果，并记录全部 SQL。"""

    def __init__(self, header, count=0, rows=None):
        self.header = header
        self.count = count
        self.rows = rows or []
        self.log = []
        self.last_sql = ""
        self.rowcount = 1
        self.lastrowid = 9

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.last_sql = " ".join(sql.split())
        self.log.append((self.last_sql, params))

    def fetchone(self):
        sql = self.last_sql.upper()
        if sql.startswith("SELECT * FROM"):
            return self.header
        if sql.startswith("SELECT COUNT(*)"):
            return {"n": self.count}
        return None

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self._cursor


class DraftDocumentTests(unittest.TestCase):
    def setUp(self):
        self.client = webapi.app.test_client()
        self.admin = {"X-Ledu-Token": webapi.API_TOKEN, "X-Ledu-Role": "admin",
                      "X-Ledu-User": "draft-test"}
        self.auditor = {**self.admin, "X-Ledu-Role": "auditor"}

    def _transaction(self, cursor):
        return mock.patch.object(webapi, "transaction", return_value=_Conn(cursor))

    def _header(self, kind, status="draft"):
        cfg = webapi._DRAFT_DELETE_KINDS[kind]
        return {cfg["id"]: 7, cfg["no"]: "DRAFT-7", "status": status,
                "reversal_of_entry_id": None, "reversed_by_entry_id": None}

    def test_every_document_kind_deletes_only_draft_and_appends_audit(self):
        for kind, cfg in webapi._DRAFT_DELETE_KINDS.items():
            with self.subTest(kind=kind):
                cursor = _Cursor(self._header(kind))
                with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                        self._transaction(cursor), \
                        mock.patch.object(webapi, "append_audit") as audit:
                    response = self.client.post(f"/drafts/{kind}/7/delete",
                                                json={"actor": "tester"}, headers=self.admin)
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                self.assertEqual(response.get_json()["status"], "deleted")
                sql = [item[0] for item in cursor.log]
                self.assertTrue(any(x.startswith(f"SELECT * FROM {cfg['table']}")
                                    and "FOR UPDATE" in x for x in sql))
                self.assertTrue(any(x.startswith(f"DELETE FROM {cfg['table']}")
                                    and "status='draft'" in x for x in sql))
                for table, column in cfg["details"]:
                    self.assertIn(f"DELETE FROM {table} WHERE {column}=%s", sql)
                self.assertTrue(any(x.startswith("UPDATE pending_review SET status='resolved'")
                                    for x in sql))
                self.assertFalse(any(x.startswith(("DELETE FROM audit_log", "UPDATE audit_log"))
                                     for x in sql))
                action = f"{kind.replace('_received', '').replace('_made', '')}.delete"
                audit.assert_called_once()
                self.assertEqual(audit.call_args.args[1]["action"], action)
                self.assertEqual(audit.call_args.args[1]["object_id"], "7")

    def test_every_document_kind_rejects_non_draft_delete(self):
        for kind, cfg in webapi._DRAFT_DELETE_KINDS.items():
            with self.subTest(kind=kind):
                cursor = _Cursor(self._header(kind, "posted"))
                with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                        self._transaction(cursor), \
                        mock.patch.object(webapi, "append_audit") as audit:
                    response = self.client.post(f"/drafts/{kind}/7/delete",
                                                json={}, headers=self.admin)
                self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
                self.assertIn("只有草稿状态", response.get_json()["message"])
                self.assertFalse(any(x[0].startswith(f"DELETE FROM {cfg['table']}")
                                     for x in cursor.log))
                audit.assert_not_called()

    def test_all_draft_write_endpoints_reject_auditor(self):
        urls = [
            "/quotes/7/update", "/invoices/7/update", "/bills/7/update",
            "/expenses/7/update", "/credit-notes/7/update", "/orders/7/update",
            "/payments/received/7/update", "/payments/made/7/update",
            "/journal/7/update",
        ]
        urls += [f"/drafts/{kind}/7/delete" for kind in webapi._DRAFT_DELETE_KINDS]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.post(url, json={}, headers=self.auditor)
                self.assertEqual(response.status_code, 403, response.get_data(as_text=True))

    def test_invoice_delete_rejects_settlement_dependency(self):
        cursor = _Cursor(self._header("invoice"), count=1)
        with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                self._transaction(cursor), mock.patch.object(webapi, "append_audit") as audit:
            response = self.client.post("/drafts/invoice/7/delete", json={}, headers=self.admin)
        self.assertEqual(response.status_code, 400)
        self.assertIn("核销记录", response.get_json()["message"])
        self.assertFalse(any(x[0].startswith("DELETE FROM invoices") for x in cursor.log))
        audit.assert_not_called()

    def test_payment_delete_rejects_linked_posted_journal(self):
        rows = [{"entry_id": 88, "entry_no": "JE-88", "status": "posted"}]
        cursor = _Cursor(self._header("payment_received"), rows=rows)
        with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                self._transaction(cursor), mock.patch.object(webapi, "append_audit") as audit:
            response = self.client.post("/drafts/payment_received/7/delete",
                                        json={}, headers=self.admin)
        self.assertEqual(response.status_code, 400)
        self.assertIn("非草稿分录", response.get_json()["message"])
        self.assertFalse(any(x[0].startswith("DELETE FROM payments_received") for x in cursor.log))
        audit.assert_not_called()

    def test_payment_delete_cascades_only_linked_draft_journal(self):
        rows = [{"entry_id": 88, "entry_no": "JE-88", "status": "draft"}]
        cursor = _Cursor(self._header("payment_received"), rows=rows)
        with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                self._transaction(cursor), mock.patch.object(webapi, "append_audit") as audit:
            response = self.client.post("/drafts/payment_received/7/delete",
                                        json={"actor": "tester"}, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        sql = [x[0] for x in cursor.log]
        self.assertIn("DELETE FROM journal_lines WHERE entry_id=%s", sql)
        self.assertTrue(any(x.startswith("DELETE FROM journal_entries")
                            and "status='draft'" in x for x in sql))
        self.assertEqual([c.args[1]["action"] for c in audit.call_args_list],
                         ["journal.delete", "payment.delete"])

    def test_payment_draft_update_has_no_posted_financial_side_effects(self):
        existing = {"payment_id": 7, "payment_no": "R-7", "status": "draft",
                    "amount": Decimal("100"), "currency": "HKD", "date": date(2026, 11, 20),
                    "bank_account_id": 3, "customer_id": 5}
        account = {"account_id": 3, "currency": "HKD"}

        class PaymentCursor(_Cursor):
            def fetchone(inner):
                sql = inner.last_sql.upper()
                if "SELECT PAYMENT_NO, STATUS" in sql:
                    return {"payment_no": "R-7", "status": "draft"}
                if "FROM INVOICES WHERE INVOICE_ID" in sql:
                    return {"id": 11, "doc_no": "INV-11", "status": "posted", "currency": "HKD",
                            "gross_original": Decimal("100"), "settled_original": Decimal("50"),
                            "fx_rate": Decimal("1")}
                return None

            def fetchall(inner):
                if "FROM SETTLEMENTS" in inner.last_sql.upper():
                    return [{"invoice_id": 11, "settled_original": Decimal("20")}]
                return []

        cursor = PaymentCursor({})
        fx = {"amount_functional": Decimal("100"), "fx_rate": Decimal("1"),
              "fx_rate_date": "2026-11-20"}
        with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                mock.patch.object(webapi, "query_one", side_effect=[existing, account]), \
                mock.patch.object(webapi, "_document_fx", return_value=fx), \
                self._transaction(cursor), mock.patch.object(webapi, "append_audit") as audit:
            response = self.client.post("/payments/received/7/update", json={
                "amount": 100, "currency": "HKD", "date": "2026-11-20",
                "bankAccountId": 3, "customerId": 5,
                "allocations": [{"docId": 11, "amount": 60}], "actor": "tester",
            }, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["status"], "draft")
        sql = [x[0] for x in cursor.log]
        self.assertTrue(any(x.startswith("UPDATE payments_received")
                            and "status='draft'" in x for x in sql))
        self.assertTrue(any(x.startswith("INSERT INTO settlements") for x in sql))
        forbidden = ("UPDATE invoices", "UPDATE bills", "UPDATE bank_accounts",
                     "INSERT INTO journal_entries", "UPDATE journal_entries")
        self.assertFalse(any(x.startswith(forbidden) for x in sql))
        self.assertEqual(audit.call_args.args[1]["action"], "payment.update")
        self.assertEqual(audit.call_args.args[1]["detail"]["status"], "draft")

    def test_payment_update_rechecks_status_after_lock(self):
        existing = {"payment_id": 7, "status": "draft", "amount": Decimal("100"),
                    "currency": "HKD", "date": date(2026, 11, 20), "bank_account_id": 3}
        account = {"account_id": 3, "currency": "HKD"}

        class PaymentCursor(_Cursor):
            def fetchone(inner):
                return {"payment_no": "R-7", "status": "posted"}

        cursor = PaymentCursor({})
        fx = {"amount_functional": Decimal("100"), "fx_rate": Decimal("1"),
              "fx_rate_date": "2026-11-20"}
        with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                mock.patch.object(webapi, "query_one", side_effect=[existing, account]), \
                mock.patch.object(webapi, "_document_fx", return_value=fx), \
                self._transaction(cursor), mock.patch.object(webapi, "append_audit") as audit:
            response = self.client.post("/payments/received/7/update", json={
                "amount": 100, "currency": "HKD", "date": "2026-11-20",
                "bankAccountId": 3, "allocations": [],
            }, headers=self.admin)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(any(x[0].startswith("UPDATE payments_received") for x in cursor.log))
        audit.assert_not_called()

    def test_journal_update_replaces_lines_but_stays_draft(self):
        class JournalCursor(_Cursor):
            def fetchone(inner):
                return {"entry_id": 7, "entry_no": "JE-7", "status": "draft"}

            def fetchall(inner):
                return [{"account_code": "1000"}, {"account_code": "4100"}]

        cursor = JournalCursor({})
        with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                self._transaction(cursor), mock.patch.object(webapi, "append_audit") as audit, \
                mock.patch("core.numbering.next_no") as next_no:
            response = self.client.post("/journal/7/update", json={
                "entryDate": "2026-11-20", "description": "修改草稿",
                "lines": [{"accountCode": "1000", "debit": 100},
                          {"accountCode": "4100", "credit": 100}],
                "actor": "tester",
            }, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["status"], "draft")
        sql = [x[0] for x in cursor.log]
        self.assertTrue(any(x.startswith("UPDATE journal_entries SET entry_date")
                            and "status='draft'" in x for x in sql))
        self.assertIn("DELETE FROM journal_lines WHERE entry_id=%s", sql)
        self.assertFalse(any("SET status='posted'" in x for x in sql))
        self.assertEqual(sum(x.startswith("INSERT INTO journal_lines") for x in sql), 2)
        next_no.assert_not_called()
        self.assertEqual(audit.call_args.args[1]["action"], "journal.update")

    def test_journal_update_rejects_non_draft_after_lock(self):
        class JournalCursor(_Cursor):
            def fetchone(inner):
                return {"entry_id": 7, "entry_no": "JE-7", "status": "posted"}

            def fetchall(inner):
                return [{"account_code": "1000"}, {"account_code": "4100"}]

        cursor = JournalCursor({})
        with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                self._transaction(cursor), mock.patch.object(webapi, "append_audit") as audit:
            response = self.client.post("/journal/7/update", json={
                "entryDate": "2026-11-20", "description": "不应保存",
                "lines": [{"accountCode": "1000", "debit": 100},
                          {"accountCode": "4100", "credit": 100}],
            }, headers=self.admin)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(any(x[0].startswith("DELETE FROM journal_lines") for x in cursor.log))
        audit.assert_not_called()

    def test_new_journal_still_creates_and_posts(self):
        class JournalCursor(_Cursor):
            def fetchall(inner):
                return [{"account_code": "1000"}, {"account_code": "4100"}]

        cursor = JournalCursor({})
        with mock.patch.object(webapi, "entity_or_404", return_value=ENTITY), \
                self._transaction(cursor), mock.patch.object(webapi, "append_audit") as audit, \
                mock.patch("core.numbering.next_no", return_value="JE-9"):
            response = self.client.post("/journal", json={
                "entryDate": "2026-11-20", "description": "新建并过账",
                "lines": [{"accountCode": "1000", "debit": 100},
                          {"accountCode": "4100", "credit": 100}],
            }, headers=self.admin)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["status"], "posted")
        self.assertTrue(any("SET status='posted'" in x[0] for x in cursor.log))
        self.assertEqual(audit.call_args.args[1]["action"], "journal.manual")


if __name__ == "__main__":
    unittest.main()
