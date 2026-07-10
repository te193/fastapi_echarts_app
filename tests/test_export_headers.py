import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class FakeDetailExportService:
    def get_detail_export_payload(self, filters):
        return {
            "columns": ["snapshot_date", "seller_name_new", "sales_qty"],
            "rows": [
                {
                    "snapshot_date": "2026-06-15",
                    "seller_name_new": "booyee",
                    "sales_qty": 12,
                }
            ],
            "start_date": "2026-06-01",
            "end_date": "2026-06-15",
        }


class ExportHeaderTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.service = FakeDetailExportService()

    def test_detail_export_uses_chinese_headers(self):
        with patch("app.main.dashboard_service", self.service):
            response = self.client.get("/api/detail/export")

        self.assertEqual(response.status_code, 200)
        first_line = response.text.splitlines()[0].lstrip("\ufeff")
        self.assertEqual(first_line, "快照日期,店铺,销量")


if __name__ == "__main__":
    unittest.main()
