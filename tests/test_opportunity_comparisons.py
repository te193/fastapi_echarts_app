import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class FakeOpportunityService:
    def __init__(self):
        self.calls = []

    def get_opportunities_payload(self, filters, **kwargs):
        self.calls.append((filters, kwargs))
        return {
            "items": [],
            "types": [{"key": "all", "label": "全部机会", "rule": "show all"}],
            "analysis": {"type_distribution": [], "margin_transition": {"rows": [], "nodes": [], "links": [], "summary": {}}, "rank_transition": {"rows": [], "nodes": [], "links": [], "summary": {}}},
            "stats": {"total": 0},
            "window": "窗口",
            "comparison_window": "对比窗口",
            "compare_days": kwargs.get("compare_days", 14),
            "empty_text": "empty",
            "total_count": 0,
            "total": 0,
            "page": 1,
            "page_size": 20,
            "total_pages": 1,
        }

    def get_opportunities_export_payload(self, filters, **kwargs):
        self.calls.append((filters, kwargs))
        return {
            "items": [],
            "window": "窗口",
            "comparison_window": "对比窗口",
            "compare_days": kwargs.get("compare_days", 14),
        }


class OpportunityComparisonApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.service = FakeOpportunityService()

    def test_api_accepts_ninety_day_comparison(self):
        with patch("app.main.dashboard_service", self.service):
            response = self.client.get("/api/opportunities?compare_days=90")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["compare_days"], 90)
        self.assertEqual(self.service.calls[0][1]["compare_days"], 90)

    def test_api_accepts_month_comparison_arguments(self):
        with patch("app.main.dashboard_service", self.service):
            response = self.client.get(
                "/api/opportunities?comparison_mode=month&previous_month=2026-01&recent_month=2026-06"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.calls[0][1]["comparison_mode"], "month")
        self.assertEqual(self.service.calls[0][1]["previous_month"], "2026-01")
        self.assertEqual(self.service.calls[0][1]["recent_month"], "2026-06")


if __name__ == "__main__":
    unittest.main()
