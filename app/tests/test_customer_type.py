import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api as webapi  # noqa: E402


class _Cursor:
    lastrowid = 42

    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))

    def fetchone(self):
        return None


class _Conn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _Cursor(self.log)


class CustomerTypeTests(unittest.TestCase):
    """客户主数据区分「公司 / 个人」：写入时落库，读取时原样返回。"""

    ENTITY = {"entity_id": 1, "entity_name": "Example Ltd"}

    def setUp(self):
        self.client = webapi.app.test_client()
        self.headers = {"X-Ledu-Token": webapi.API_TOKEN, "X-Ledu-Role": "admin",
                        "X-Ledu-User": "customer-type-test"}

    def test_unsupported_type_falls_back_to_company(self):
        self.assertEqual(webapi._customer_type("individual"), "individual")
        self.assertEqual(webapi._customer_type(" Individual "), "individual")
        for value in (None, "", "company", "partnership", 0):
            self.assertEqual(webapi._customer_type(value), "company")

    def _save(self, payload):
        log = []
        with mock.patch.object(webapi, "require_writer"), \
                mock.patch.object(webapi, "entity_or_404", return_value=self.ENTITY), \
                mock.patch.object(webapi, "transaction", return_value=_Conn(log)), \
                mock.patch.object(webapi, "append_audit"):
            response = self.client.post("/customers", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return log

    def test_individual_customer_is_persisted_as_individual(self):
        log = self._save({"customerName": "陈大文", "customerType": "individual"})
        insert = next(item for item in log if item[0].startswith("INSERT INTO customers"))
        self.assertIn("customer_type", insert[0])
        self.assertIn("individual", insert[1])

    def test_missing_type_defaults_to_company(self):
        log = self._save({"customerCode": "C-9001", "customerName": "ABC Trading Limited"})
        insert = next(item for item in log if item[0].startswith("INSERT INTO customers"))
        self.assertIn("company", insert[1])

    def test_edit_updates_type_and_keeps_id(self):
        log = self._save({"customerId": 7, "customerCode": "C-9002",
                          "customerName": "陈大文", "customerType": "individual"})
        update = next(item for item in log if item[0].startswith("UPDATE customers"))
        self.assertIn("customer_type=%s", update[0])
        self.assertIn("individual", update[1])

    def test_list_returns_type(self):
        row = {"customer_id": 1, "customer_code": "C-0001", "customer_name": "陈大文",
               "customer_type": "individual"}
        with mock.patch.object(webapi, "entity_or_404", return_value=self.ENTITY), \
                mock.patch.object(webapi, "query_one", return_value={"n": 1}), \
                mock.patch.object(webapi, "query", return_value=[row]) as query:
            response = self.client.get("/customers", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["customers"][0]["customer_type"], "individual")
        self.assertIn("customer_type", query.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
