import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from fastapi import HTTPException

from app import main


class FakeLabelHubService:
    def __init__(self):
        self.calls = []

    def get_meta(self):
        self.calls.append(("meta", {}))
        return {"categories": []}

    def get_payload(self, **kwargs):
        self.calls.append(("payload", kwargs))
        return {"rows": [], "total": 0}

    def get_msku_profile(self, **kwargs):
        self.calls.append(("profile", kwargs))
        return {"msku": "MSKU1"}


class LabelHubApiTests(unittest.TestCase):
    def test_label_hub_page_route_exists(self):
        response = TestClient(main.app).get("/label-hub")

        self.assertEqual(200, response.status_code)
        self.assertIn("标签看板", response.text)

    def test_payload_forwards_supported_filter_contract(self):
        service = FakeLabelHubService()
        with patch("app.main.label_hub_service", service):
            payload = main.api_label_hub(
                data_date="2026-07-13",
                country_category="欧洲站",
                store="StoreA",
                keyword="MSKU1",
                parent_label_id=3,
                compare_parent_id=2,
                conditions="3:301|304;2:201",
                label_period="current",
                metric_period="30d",
                analysis_parent_ids="2|8|9",
                sales_roles="eliminate|incubation",
                daily_sales_bands="zero|lt1",
                margin_bands="lt5",
                problem="negative_profit",
                page=2,
                page_size=50,
                sort_field="sales_amount",
                sort_dir="asc",
            )

        self.assertEqual({"rows": [], "total": 0}, payload)
        self.assertEqual("payload", service.calls[0][0])
        self.assertEqual("3:301|304;2:201", service.calls[0][1]["conditions"])
        self.assertEqual("2|8|9", service.calls[0][1]["analysis_parent_ids"])
        self.assertEqual("negative_profit", service.calls[0][1]["problem"])
        self.assertEqual(50, service.calls[0][1]["page_size"])

    def test_payload_surfaces_source_failure_as_service_unavailable(self):
        class FailingService:
            def get_payload(self, **kwargs):
                raise RuntimeError("source offline")

        with patch("app.main.label_hub_service", FailingService()), self.assertRaises(HTTPException) as ctx:
            main.api_label_hub()

        self.assertEqual(503, ctx.exception.status_code)


if __name__ == "__main__":
    unittest.main()
