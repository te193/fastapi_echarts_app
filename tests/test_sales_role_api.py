import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app import main


class FakeSalesRoleService:
    def __init__(self):
        self.calls = []

    def get_sales_role_meta(self):
        self.calls.append({"method": "meta"})
        return {"default_period": "30d"}

    def get_sales_role_payload(self, **kwargs):
        self.calls.append({"method": "payload", **kwargs})
        return {"ok": True, "rows": [{"sales_role": "明星产品", "seller_sku_adj": "MSKU1"}]}

    def get_sales_role_export_payload(self, **kwargs):
        self.calls.append({"method": "export", **kwargs})
        return {
            "rows": [
                {
                    "sales_role": "明星产品",
                    "country_category": "欧洲站",
                    "seller_name_new": "StoreA",
                    "seller_sku_adj": "MSKU1",
                    "sales_qty": 12,
                }
            ]
        }


class SalesRoleApiTests(unittest.TestCase):
    def test_sales_role_page_route_exists(self):
        client = TestClient(main.app)

        response = client.get("/sales-role")

        self.assertEqual(200, response.status_code)
        self.assertIn("销售角色分析", response.text)

    def test_sales_role_meta_uses_dashboard_service(self):
        service = FakeSalesRoleService()

        with patch("app.main.dashboard_service", service):
            payload = main.api_sales_role_meta()

        self.assertEqual({"default_period": "30d"}, payload)
        self.assertEqual({"method": "meta"}, service.calls[0])

    def test_sales_role_payload_passes_query_params_to_service(self):
        service = FakeSalesRoleService()

        with patch("app.main.dashboard_service", service):
            payload = main.api_sales_role(
                period="90d",
                country_category="欧洲站",
                seller_name_new="StoreA",
                sales_role="star",
                daily_sales_band="日销 >5",
                margin_band=">25%",
                keyword="MSKU1",
                page=2,
                page_size=50,
                sort_field="sales_amount",
                sort_dir="desc",
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(
            {
                "method": "payload",
                "period": "90d",
                "country_category": "欧洲站",
                "seller_name_new": "StoreA",
                "sales_role": "star",
                "daily_sales_band": "日销 >5",
                "margin_band": ">25%",
                "keyword": "MSKU1",
                "page": 2,
                "page_size": 50,
                "sort_field": "sales_amount",
                "sort_dir": "desc",
            },
            service.calls[0],
        )

    def test_sales_role_export_returns_csv(self):
        service = FakeSalesRoleService()

        with patch("app.main.dashboard_service", service):
            response = main.api_sales_role_export(period="7d", country_category="欧洲站")

        self.assertEqual("text/csv; charset=utf-8", response.media_type)
        self.assertIn("attachment;", response.headers["content-disposition"])
        self.assertEqual(
            {"method": "export", "period": "7d", "country_category": "欧洲站", "seller_name_new": "all", "sales_role": "all", "daily_sales_band": "all", "margin_band": "all", "keyword": "", "sort_field": "sales_amount", "sort_dir": "desc"},
            service.calls[0],
        )


if __name__ == "__main__":
    unittest.main()
