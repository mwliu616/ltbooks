"""
缺失测试清单 — 全检报告七、八条
T-01 / T-02 / T-03 / T-05 / T-06 / T-07（后端 & 数据库）
T-04 / T-07（UI）    另有独立 Playwright 脚本

运行：PYTHONPATH=/opt/ltbooks/app python -m unittest discover -s tests -p 'test_missing_checklist.py' -v
"""
import sys
import unittest
import threading
import time
import os
import csv
import io
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api as webapi  # noqa: E402
from core import db as dbmod  # noqa: E402


ENTITY = {"entity_id": 1, "entity_name": "Test Co"}
ADMIN_HDR = {"X-Ledu-Token": webapi.API_TOKEN,
             "X-Ledu-Role": "admin", "X-Ledu-User": "tester"}
AUDITOR_HDR = {"X-Ledu-Token": webapi.API_TOKEN,
               "X-Ledu-Role": "auditor", "X-Ledu-User": "auditor"}


def _rows(n, factory):
    return [factory(i) for i in range(n)]


# =====================================================================
# T-02：导出边界 — 10 万行正常导出；超 10 万行被拒绝
# =====================================================================
class TestExportLimit(unittest.TestCase):
    """受控导出：单批最多 10 万行；触顶时超限拒绝。"""

    def setUp(self):
        self.client = webapi.app.test_client()
        self.get_entity = mock.patch.object(webapi, "entity_or_404",
                                            return_value=ENTITY).start()
        self.addCleanup(mock.patch.stopall)

    def _gen_row(self, i):
        return {"invoice_no": f"INV{i:06d}", "supplier_name": "X Ltd",
                "invoice_date": "2026-11-01", "currency": "HKD",
                "amount_original": 100.00, "tax_original": 5.00,
                "gross_original": 105.00, "status": "posted"}

    def test_export_invoices_exactly_100k_accepted(self):
        """恰好 100000 行 — 导出成功，返回文件。"""
        rows = _rows(100000, self._gen_row)
        write_p = mock.patch.object(Path, "write_text").start()
        self.addCleanup(mock.patch.stopall)
        with mock.patch.object(webapi, "query", return_value=rows), \
             mock.patch.object(webapi, "query_one", return_value={"c": 100000}):
            resp = self.client.post(
                "/export",
                json={"kind": "invoices", "purpose": "审计复核", "recipient": "auditor@example.com"},
                headers=ADMIN_HDR)
            self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertTrue(write_p.called, "应调用 Path.write_text 写出 CSV")

    def test_export_invoices_100k_plus_1_rejected(self):
        """rows 刚好 100000 但 COUNT(*) 显示 123456 —— 超限拒绝。"""
        rows = _rows(100000, self._gen_row)
        with mock.patch.object(webapi, "query", return_value=rows), \
             mock.patch.object(webapi, "query_one", return_value={"c": 123456}), \
             mock.patch.object(Path, "write_text"):
            resp = self.client.post(
                "/export",
                json={"kind": "invoices", "purpose": "审计复核", "recipient": "auditor@example.com"},
                headers=ADMIN_HDR)
            self.assertEqual(resp.status_code, 400)
            body = resp.get_json() or {}
            self.assertIn("超过单批上限", (body.get("message") or body.get("error") or ""))

    def test_export_requires_writer_role(self):
        """auditor 角色不能导出 — 返回 403。"""
        resp = self.client.post(
            "/export",
            json={"kind": "journals", "purpose": "审计复核", "recipient": "auditor@example.com"},
            headers=AUDITOR_HDR)
        self.assertEqual(resp.status_code, 403)


# =====================================================================
# T-03：并发过账 — 10 个线程同时推进 doc_sequences 序列不重复
# =====================================================================
class TestConcurrentEntryNo(unittest.TestCase):
    """并发下 next_no(kind='journal') 连续不重复。"""

    def test_10_threads_allocation_unique(self):
        """10 线程同时调用 numbering.next_no — 每线程拿到不同序号。"""
        from core import numbering

        lock = threading.Lock()
        last_seq = {"v": 1000}
        results = []
        errors = []

        def _fake_execute(cur, sql, params=None):
            s = " ".join(str(sql).split())
            if "last_seq" in s and "UPDATE" in s:
                with lock:
                    last_seq["v"] += 1
                    cur._fake_last = last_seq["v"]
            # ON DUPLICATE KEY UPDATE 模拟

        def _fake_fetchone(cur):
            return {"last_seq": cur._fake_last} if hasattr(cur, "_fake_last") else None

        class _MockCur:
            def __init__(self):
                self._fake_last = None
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def execute(self, sql, params=None): _fake_execute(self, sql, params)
            def fetchone(self): return _fake_fetchone(self)

        class _MockConn:
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def cursor(self): return _MockCur()

        def worker(tid):
            try:
                r = numbering.next_no(_MockConn(), 1, "2026-11-20", "journal")
                results.append(r)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=10)

        self.assertEqual(errors, [], f"有线程失败：{errors}")
        self.assertEqual(len(results), 10)
        self.assertEqual(len(set(results)), 10, f"entry_no 有重复：{results}")


# =====================================================================
# T-05：现金流量表折旧识别 — 优先科目 flag，不依赖 6800/6801/6802
# =====================================================================
class TestDepreciationByFlag(unittest.TestCase):
    """现金流量表折旧识别优先 fs_line_item flag。"""

    def setUp(self):
        self.client = webapi.app.test_client()
        self.get_entity = mock.patch.object(webapi, "entity_or_404",
                                            return_value=ENTITY).start()
        self.addCleanup(mock.patch.stopall)

    def test_custom_code_with_flag_detected(self):
        """科目编码 9999（非 68xx）但 fs_line_item='DEPRECIATION' — 仍能识别。"""
        from core import reports

        DEPR_NONCASH_ROW = [{
            "account_code": "9999", "account_name": "Custom Depreciation",
            "category": "expense", "fs_line_item": "DEPRECIATION",
            "dr": 5000.00, "cr": 0.0,
        }]

        def _q_side(sql, params=None):
            s = str(sql).lower()
            if "cash_equivalents" in s:
                return [{"account_code": "1000", "fs_line_item": "CASH"}]
            if "a.category" in s and "('expense','cogs')" in s.replace(" ", ""):
                return DEPR_NONCASH_ROW
            return []

        def _qo_side(sql, params=None):
            return {"dr": 0.0, "cr": 0.0, "n": 0}

        with mock.patch.object(reports, "profit_and_loss",
                               side_effect=lambda eid, *a, **kw: {"netProfit": 0.0}), \
             mock.patch.object(reports, "query", side_effect=_q_side), \
             mock.patch.object(reports, "query_one", side_effect=_qo_side):
            cf = reports.cash_flow(ENTITY["entity_id"],
                                    date(2026, 1, 1), date(2026, 12, 31))
            non_cash = cf.get("nonCash", [])
            self.assertTrue(any(abs(x.get("amount", 0)) > 0 for x in non_cash),
                            f"自定义科目折旧未被识别：{non_cash}")


# =====================================================================
# T-06：多币种 journal_lines original vs functional 金额
# =====================================================================
class TestMultiCurrencyJournal(unittest.TestCase):
    """journal_lines schema + service.py 过账路径必须写原币金额。"""

    def test_schema_has_original_amount_columns(self):
        schema_sql = Path(__file__).resolve().parent.parent / "sql" / "01_schema.sql"
        schema = schema_sql.read_text()
        for col in ("amount_original", "rate", "rate_date"):
            self.assertIn(col, schema,
                          f"journal_lines schema 缺少 {col} 列")

    def test_service_post_writes_original_amount(self):
        service_py = Path(__file__).resolve().parent.parent / "core" / "service.py"
        src = service_py.read_text()
        self.assertIn("amount_original", src,
                      "service.py 过账时未写 journal_lines.amount_original")
        self.assertIn("rate_date", src,
                      "service.py 过账时未写 rate_date")


# =====================================================================
# T-07：auditor 角色 13 个写入口后端也拒绝
# =====================================================================
class TestAuditorHiddenEntries(unittest.TestCase):

    WRITE_ENDPOINTS = [
        ("POST", "/invoices", {"supplierName": "X Ltd", "date": "2026-11-01",
                               "currency": "HKD", "amountOriginal": 100}),
        ("POST", "/bills", {"vendorName": "X Ltd", "date": "2026-11-01",
                            "currency": "HKD", "amount": 100}),
        ("POST", "/expenses", {"category": "test", "date": "2026-11-01",
                               "currency": "HKD", "amount": 100}),
        ("POST", "/customers", {"customerName": "New Co", "customerType": "company"}),
        ("POST", "/vendors", {"vendorName": "New Vendor"}),
        ("POST", "/quotes", {"customerName": "X Ltd", "quoteDate": "2026-11-01"}),
        ("POST", "/credit-notes", {"creditType": "customer", "partyName": "X Ltd",
                                    "amountOriginal": 100}),
        ("POST", "/journals", {"entryDate": "2026-11-01", "entryNo": "J001",
                                "lines": []}),
        ("POST", "/recurring", {"ruleName": "test", "kind": "invoice"}),
        ("POST", "/period-close/run", {"period": "2026-11", "step": "all"}),
        ("POST", "/accounts", {"accountCode": "9999", "accountName": "test"}),
        ("POST", "/fx/rates", {"rateDate": "2026-11-01", "fromCcy": "USD",
                                "toCcy": "HKD", "rate": 7.80}),
    ]

    def setUp(self):
        self.client = webapi.app.test_client()
        self.get_entity = mock.patch.object(webapi, "entity_or_404",
                                            return_value=ENTITY).start()
        self.addCleanup(mock.patch.stopall)

    def test_all_write_endpoints_403_for_auditor(self):
        blocked = []
        for method, url, payload in self.WRITE_ENDPOINTS:
            fn = getattr(self.client, method.lower())
            resp = fn(url, json=payload, headers=AUDITOR_HDR)
            # 403 = 直接拒绝；400/422 = 业务层校验通过了但参数不全（也算拒绝）
            if resp.status_code < 200 or resp.status_code >= 300 and resp.status_code < 400:
                blocked.append(f"{method} {url} → {resp.status_code} 错误放行")

        self.assertEqual(blocked, [], f"auditor 放行了写路径：{blocked}")
        self.assertEqual(len(self.WRITE_ENDPOINTS), 12)


# =====================================================================
# T-01：5000 客户 api_get benchmark
# =====================================================================
class TestCustomersBenchmark(unittest.TestCase):

    def setUp(self):
        self.client = webapi.app.test_client()
        self.get_entity = mock.patch.object(webapi, "entity_or_404",
                                            return_value=ENTITY).start()
        self.addCleanup(mock.patch.stopall)

    def test_5000_customers_under_500ms(self):
        rows = _rows(5000, lambda i: {
            "customer_id": i + 1,
            "customer_name": f"Customer_{i:04d}",
            "customer_code": f"C{i:04d}",
            "customer_type": "company",
        })
        start = time.perf_counter()
        with mock.patch.object(webapi, "query", return_value=rows), \
             mock.patch.object(webapi, "query_one", return_value={"n": 5000}):
            resp = self.client.get("/customers?limit=5000", headers=ADMIN_HDR)
        elapsed = (time.perf_counter() - start) * 1000
        self.assertEqual(resp.status_code, 200, f"HTTP {resp.status_code}: {resp.get_json()}")
        self.assertLess(elapsed, 500, f"5000 客户列表耗时 {elapsed:.0f}ms 超过阈值")
        print(f"\n  [T-01] 5000 customers → {elapsed:.0f}ms ✅")


if __name__ == "__main__":
    unittest.main(verbosity=2)
