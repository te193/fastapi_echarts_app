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


class FakeLabelHubDetailService:
    def __init__(self):
        self.calls = []

    def get_details(self, **kwargs):
        self.calls.append(kwargs)
        return {"rows": [], "total": 0}


class FakeLabelHubChangeService:
    def __init__(self):
        self.calls = []

    def get_changes(self, **kwargs):
        self.calls.append(kwargs)
        return {"summary": {"current": 425}}


class FakeCountryProfileService:
    def __init__(self):
        self.calls = []

    def get_label_hub_country_profile(self, **kwargs):
        self.calls.append(kwargs)
        return {"countries": []}


class LabelHubApiTests(unittest.TestCase):
    def test_detail_payload_forwards_post_request_contract(self):
        service = FakeLabelHubDetailService()
        request = main.LabelHubDetailRequest(
            detail_view="business_unit",
            data_date="2026-07-13",
            metric_period="30d",
            country_category="Europe",
            store="StoreA",
            keyword="needle",
            parent_label_id=1,
            compare_parent_id=2,
            conditions="1:101",
            label_period="7d",
            analysis_parent_ids=[2, 8],
            analysis_periods=["7d", "30d"],
            identifiers=["MSKU-1"],
            country_categories=["Europe"],
            stores=["StoreA"],
            countries=["DE"],
            sales_roles=["star"],
            sales_trends=["growing"],
            daily_sales_bands=["gt5"],
            margin_bands=["gt25"],
            ranking_bands=["11_20"],
            problems=["conflict"],
            detail_conditions="2:201",
            problem_mode="all",
            page=2,
            page_size=50,
            sort_field="msku",
            sort_dir="asc",
        )

        with patch("app.main.label_hub_detail_service", service):
            payload = main.api_label_hub_details(request)

        self.assertEqual({"rows": [], "total": 0}, payload)
        self.assertEqual(["MSKU-1"], service.calls[0]["identifiers"])
        self.assertEqual([2, 8], service.calls[0]["analysis_parent_ids"])
        self.assertEqual("2:201", service.calls[0]["detail_conditions"])
        self.assertEqual(["11_20"], service.calls[0]["ranking_bands"])
        self.assertEqual(50, service.calls[0]["page_size"])

    def test_detail_payload_maps_value_error_to_400_and_unexpected_failure_to_503(self):
        class FailingService:
            def __init__(self, error):
                self.error = error

            def get_details(self, **kwargs):
                raise self.error

        request = main.LabelHubDetailRequest()
        for error, expected_status in ((ValueError("bad input"), 400), (RuntimeError("offline"), 503)):
            with self.subTest(expected_status=expected_status):
                with patch("app.main.label_hub_detail_service", FailingService(error)), self.assertRaises(HTTPException) as ctx:
                    main.api_label_hub_details(request)
                self.assertEqual(expected_status, ctx.exception.status_code)
                if expected_status == 503:
                    self.assertEqual("标签明细数据暂不可用，请稍后重试", ctx.exception.detail)
                    self.assertNotIn("offline", ctx.exception.detail)

    def test_detail_http_validation_rejects_non_positive_page_and_invalid_sort(self):
        client = TestClient(main.app)

        invalid_page = client.post("/api/label-hub/details", json={"page": 0})
        invalid_sort = client.post("/api/label-hub/details", json={"sort_field": "not_a_column"})

        self.assertEqual(422, invalid_page.status_code)
        self.assertEqual(400, invalid_sort.status_code)
        self.assertIn("排序字段", invalid_sort.json()["detail"])

    def test_label_hub_page_route_exists(self):
        response = TestClient(main.app).get("/label-hub")

        self.assertEqual(200, response.status_code)
        self.assertIn('main class="main-content page-loading"', response.text)
        self.assertIn('aria-busy="true"', response.text)
        self.assertIn("标签看板", response.text)
        self.assertIn('id="labelHubSectionNav"', response.text)
        self.assertNotIn('id="labelHubHighlightsSection"', response.text)
        self.assertNotIn("当前组合变化</h2>", response.text)

    def test_country_label_hub_page_route_exists(self):
        response = TestClient(main.app).get("/country-label-hub")

        self.assertEqual(200, response.status_code)
        self.assertIn("国家标签看板", response.text)
        self.assertIn('main class="main-content page-loading"', response.text)
        self.assertIn('aria-busy="true"', response.text)
        self.assertIn('id="countryTableView"', response.text)
        self.assertIn("综合视图", response.text)
        self.assertIn("标签视图", response.text)
        self.assertIn("经营视图", response.text)
        self.assertIn('id="countryLabelPeriod"', response.text)
        self.assertIn("标签周期", response.text)
        self.assertIn("slimselect.js", response.text)

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
                analysis_periods="7d|current|30d",
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
        self.assertEqual("7d|current|30d", service.calls[0][1]["analysis_periods"])
        self.assertEqual("negative_profit", service.calls[0][1]["problem"])
        self.assertEqual(50, service.calls[0][1]["page_size"])

    def test_payload_surfaces_source_failure_as_service_unavailable(self):
        class FailingService:
            def get_payload(self, **kwargs):
                raise RuntimeError("source offline")

        with patch("app.main.label_hub_service", FailingService()), self.assertRaises(HTTPException) as ctx:
            main.api_label_hub()

        self.assertEqual(503, ctx.exception.status_code)

    def test_changes_forwards_clicked_layer_contract(self):
        service = FakeLabelHubChangeService()
        with patch("app.main.label_hub_change_service", service):
            payload = main.api_label_hub_changes(
                parent_label_id=3,
                conditions="1:103",
                layer_change_parent=1,
                layer_change_bucket="103",
                layer_change_period="all",
                layer_transition_from="瘦狗产品",
                layer_transition_to="问题产品",
            )

        self.assertEqual({"summary": {"current": 425}}, payload)
        self.assertEqual(1, service.calls[0]["layer_change_parent"])
        self.assertEqual("103", service.calls[0]["layer_change_bucket"])
        self.assertEqual("all", service.calls[0]["layer_change_period"])
        self.assertEqual("瘦狗产品", service.calls[0]["layer_transition_from"])
        self.assertEqual("问题产品", service.calls[0]["layer_transition_to"])

    def test_country_profile_route_keeps_row_identity_only(self):
        service = FakeCountryProfileService()
        with patch("app.main.country_label_hub_service", service):
            payload = main.api_label_hub_msku_country_profile(
                country_category="欧洲站",
                store="StoreA",
                msku="A1",
            )

        self.assertEqual({"countries": []}, payload)
        self.assertEqual({"country_category": "欧洲站", "store": "StoreA", "msku": "A1", "metric_period": "30d"}, service.calls[0])


if __name__ == "__main__":
    unittest.main()
