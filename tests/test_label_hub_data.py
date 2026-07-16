import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.label_hub_data import CACHE_SECONDS, LabelHubDataService, _missing_metric_mskus


DETAILS = [
    {
        "label_id": 1,
        "label_name": "销售角色",
        "sub_label_id": 101,
        "sub_label_name": "明星产品",
        "tag_rule": "高销量高毛利",
        "business_definition": "重点经营",
        "business_owner": "运营",
        "label_category": "经营",
        "update_frequency": "日",
        "mutual_exclusion": "互斥",
        "status": "已启用",
        "tagging_method": "auto_sql",
    },
    {
        "label_id": 1,
        "label_name": "销售角色",
        "sub_label_id": 102,
        "sub_label_name": "潜力产品",
        "tag_rule": "高销量中低毛利",
        "business_definition": "提升毛利",
        "business_owner": "运营",
        "label_category": "经营",
        "update_frequency": "日",
        "mutual_exclusion": "互斥",
        "status": "已启用",
        "tagging_method": "auto_sql",
    },
    {
        "label_id": 2,
        "label_name": "生命周期",
        "sub_label_id": 201,
        "sub_label_name": "新品期",
        "tag_rule": "上架≤30天",
        "business_definition": "新品",
        "business_owner": "运营",
        "label_category": "经营",
        "update_frequency": "日",
        "mutual_exclusion": "",
        "status": "已启用",
        "tagging_method": "auto_sql",
    },
    {
        "label_id": 12,
        "label_name": "广告与营销",
        "sub_label_id": 1201,
        "sub_label_name": "广告标签",
        "tag_rule": "",
        "business_definition": "",
        "business_owner": "广告",
        "label_category": "广告",
        "update_frequency": "日",
        "mutual_exclusion": "",
        "status": "未启用",
        "tagging_method": "auto_sql",
    },
    {
        "label_id": 8,
        "label_name": "库存水平",
        "sub_label_id": 801,
        "sub_label_name": "库存健康",
        "tag_rule": "库存覆盖合理",
        "business_definition": "库存水平",
        "business_owner": "运营",
        "label_category": "库存",
        "update_frequency": "日",
        "mutual_exclusion": "互斥",
        "status": "已启用",
        "tagging_method": "auto_sql",
    },
    {
        "label_id": 13,
        "label_name": "国家销售角色",
        "sub_label_id": 1301,
        "sub_label_name": "国家角色",
        "tag_rule": "",
        "business_definition": "",
        "business_owner": "运营",
        "label_category": "经营",
        "update_frequency": "日",
        "mutual_exclusion": "",
        "status": "已启用",
        "tagging_method": "auto_sql",
    },
]


FACTS = [
    {"data_date": "2026-07-13", "country_category": "欧洲站", "store": "StoreA", "msku": "A1", "label_id": 101, "label_period": "30d"},
    {"data_date": "2026-07-13", "country_category": "欧洲站", "store": "StoreA", "msku": "A1", "label_id": 201, "label_period": "current"},
    {"data_date": "2026-07-13", "country_category": "欧洲站", "store": "StoreA", "msku": "A2", "label_id": 101, "label_period": "30d"},
    {"data_date": "2026-07-13", "country_category": "欧洲站", "store": "StoreA", "msku": "A2", "label_id": 102, "label_period": "30d"},
    {"data_date": "2026-07-13", "country_category": "美国站", "store": "StoreB", "msku": "Amazon.Found.B0", "label_id": 101, "label_period": "30d"},
]


METRICS = {
    ("欧洲站", "StoreA", "A1"): {"sales_qty": 3, "daily_sales": 0.1, "sales_amount": 100, "order_gross_profit": 20, "order_gross_margin": 0.2, "sales_role": "明星产品", "sales_role_code": "star", "sales_trend": "明显增长", "sales_trend_code": "accelerating", "sales_trend_ratio": 0.5, "daily_sales_band_code": "lt1", "margin_band_code": "15_25"},
    ("欧洲站", "StoreA", "A2"): {"sales_qty": 2, "daily_sales": 0, "sales_amount": 50, "order_gross_profit": -5, "order_gross_margin": -0.1, "sales_role": "问题产品", "sales_role_code": "eliminate", "sales_trend": "近期停销", "sales_trend_code": "stopped", "sales_trend_ratio": -1, "daily_sales_band_code": "zero", "margin_band_code": "lt5"},
}


class LabelHubDataTests(unittest.TestCase):
    def setUp(self):
        self.service = LabelHubDataService.__new__(LabelHubDataService)

    def test_label_fact_and_metric_cache_keeps_five_minutes(self):
        self.assertEqual(300, CACHE_SECONDS)

    def test_missing_metric_mskus_treats_any_matched_scope_as_available(self):
        rows = [
            {"msku": "A1", "_metric_present": False},
            {"msku": "A1", "_metric_present": True},
            {"msku": "A2", "_metric_present": False},
        ]

        self.assertEqual({"A2"}, _missing_metric_mskus(rows))

    def test_parse_conditions_uses_or_within_parent_and_and_across_parents(self):
        parsed = self.service.parse_conditions("1:101|102;2:201")

        self.assertEqual({1: {101, 102}, 2: {201}}, parsed)
        with self.assertRaises(ValueError):
            self.service.parse_conditions("broken")

    def test_analysis_categories_exclude_non_msku_grain_parents(self):
        categories = self.service._analysis_categories(DETAILS, {})

        self.assertNotIn(13, {item["id"] for item in categories})

    def test_payload_rejects_conditions_for_excluded_parent(self):
        with self.assertRaisesRegex(ValueError, "不存在或归属错误"):
            self.service.build_payload(
                details=DETAILS, facts=FACTS, metrics=METRICS, data_date="2026-07-13",
                parent_label_id=1, compare_parent_id=2, conditions={13: {1301}}, label_period="all",
                country_category="all", store="all", keyword="", page=1, page_size=20,
                sort_field="sales_amount", sort_dir="desc",
            )

    def test_payload_drops_rows_that_only_have_excluded_grain_labels(self):
        excluded_fact = {**FACTS[0], "label_id": 1301, "label_period": "current"}

        payload = self.service.build_payload(
            details=DETAILS, facts=[excluded_fact], metrics={}, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc",
        )

        self.assertEqual(0, payload["total"])
        self.assertEqual(0, payload["kpis"]["sku_count"])

    def test_build_payload_excludes_refund_sku_and_marks_only_configured_conflicts(self):
        payload = self.service.build_payload(
            details=DETAILS,
            facts=FACTS,
            metrics=METRICS,
            data_date="2026-07-13",
            parent_label_id=1,
            compare_parent_id=2,
            conditions={},
            label_period="all",
            country_category="all",
            store="all",
            keyword="",
            page=1,
            page_size=20,
            sort_field="sales_amount",
            sort_dir="desc",
        )

        self.assertEqual(2, payload["kpis"]["sku_count"])
        self.assertEqual(1, payload["health"]["mutual_exclusion_conflict_count"])
        self.assertEqual(0, payload["category_date_counts"][12])
        self.assertEqual(["A1", "A2"], [row["msku"] for row in payload["rows"]])
        self.assertNotIn("Amazon.Found.B0", [row["msku"] for row in payload["rows"]])
        self.assertEqual(1, payload["matrix"]["total"])

    def test_overview_and_six_breakdowns_return_unique_msku_metrics(self):
        payload = self.service.build_payload(
            details=DETAILS, facts=FACTS, metrics=METRICS, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc", analysis_parent_ids=[2, 12, 13],
            sales_roles=set(), sales_trends=set(), daily_sales_bands=set(), margin_bands=set(), problem="all",
            metric_scope={"status": "available", "window": {"period_code": "30d"}},
        )

        overview = {item["id"]: item for item in payload["overview"]}
        self.assertEqual(2, overview[1]["msku_count"])
        self.assertEqual("available", overview[1]["state"])
        self.assertEqual(2, next(child for child in overview[1]["children"] if child["id"] == 101)["msku_count"])
        self.assertEqual(6, len(payload["breakdowns"]))
        self.assertEqual(2, payload["kpis"]["metric_msku_count"])
        self.assertEqual(1, payload["issue_counts"]["negative_profit"])

    def test_overview_exposes_unique_msku_and_business_unit_aggregation(self):
        cross_scope_fact = {
            **FACTS[0],
            "country_category": "美国站",
            "store": "StoreB",
        }

        payload = self.service.build_payload(
            details=DETAILS, facts=[*FACTS, cross_scope_fact], metrics=METRICS, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc",
        )

        self.assertEqual(
            {"business_unit_count": 3, "unique_msku_count": 2, "cross_scope_msku_count": 1},
            payload["population_summary"],
        )
        sales_role = next(item for item in payload["overview"] if item["id"] == 1)
        self.assertEqual(3, sales_role["business_unit_count"])
        self.assertEqual(2, sales_role["unique_msku_count"])
        self.assertEqual(1.0, sales_role["unique_msku_coverage_rate"])
        star = next(item for item in sales_role["children"] if item["id"] == 101)
        self.assertEqual(3, star["business_unit_count"])
        self.assertEqual(2, star["unique_msku_count"])

    def test_analysis_panels_deduplicate_msku_but_detail_keeps_business_units(self):
        cross_scope_facts = [
            {**FACTS[0], "country_category": "美国站", "store": "StoreB"},
            {**FACTS[1], "country_category": "美国站", "store": "StoreB"},
            {**FACTS[2], "country_category": "美国站", "store": "StoreB"},
            {**FACTS[3], "country_category": "美国站", "store": "StoreB"},
        ]
        metrics = {
            **METRICS,
            ("美国站", "StoreB", "A1"): {**METRICS[("欧洲站", "StoreA", "A1")]},
            ("美国站", "StoreB", "A2"): {**METRICS[("欧洲站", "StoreA", "A2")]},
        }

        payload = self.service.build_payload(
            details=DETAILS, facts=[*FACTS, *cross_scope_facts], metrics=metrics, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc",
            metric_scope={"status": "available", "window": {"period_code": "30d"}},
        )

        self.assertEqual(4, payload["total"])
        self.assertEqual(4, len(payload["rows"]))
        self.assertEqual(2, payload["kpis"]["sku_count"])
        self.assertEqual(2, payload["kpis"]["metric_msku_count"])
        self.assertEqual(2, payload["issue_counts"]["all"])
        self.assertEqual(1, payload["issue_counts"]["problem_role"])
        self.assertEqual(1, payload["issue_counts"]["zero_sales"])
        self.assertEqual(2, payload["diagnosis"]["subject"]["msku_count"])

        distribution = {item["id"]: item["count"] for item in payload["distribution"]}
        self.assertEqual(2, distribution[101])
        self.assertEqual(0, distribution[102])
        sales_trend = next(item for item in payload["breakdowns"] if item["key"] == "sales_trend")
        buckets = {item["key"]: item["msku_count"] for item in sales_trend["buckets"]}
        self.assertEqual(1, buckets["accelerating"])
        self.assertEqual(1, buckets["stopped"])
        lifecycle_cell = next(
            item for item in payload["matrix"]["cells"]
            if item["row_id"] == 101 and item["col_id"] == 201
        )
        self.assertEqual(1, lifecycle_cell["count"])

    def test_aggregated_panels_choose_best_label_per_msku(self):
        details = [
            *DETAILS,
            {**DETAILS[0], "sub_label_id": 103, "sub_label_name": "瘦狗产品"},
            {**DETAILS[0], "sub_label_id": 104, "sub_label_name": "问题产品"},
        ]
        facts = [
            {**FACTS[0], "label_period": "7d"},
            {**FACTS[0], "country_category": "美国站", "store": "StoreB", "label_id": 104, "label_period": "7d"},
            {**FACTS[2], "label_id": 103, "label_period": "7d"},
            {**FACTS[2], "country_category": "美国站", "store": "StoreB", "label_id": 102, "label_period": "7d"},
        ]
        metrics = {
            ("欧洲站", "StoreA", "A1"): {**METRICS[("欧洲站", "StoreA", "A1")]},
            ("美国站", "StoreB", "A1"): {
                **METRICS[("欧洲站", "StoreA", "A2")],
                "sales_trend": "明显下降",
                "sales_trend_code": "declining",
            },
            ("欧洲站", "StoreA", "A2"): {
                **METRICS[("欧洲站", "StoreA", "A2")],
                "sales_role": "瘦狗产品",
                "sales_role_code": "incubation",
            },
            ("美国站", "StoreB", "A2"): {
                **METRICS[("欧洲站", "StoreA", "A1")],
                "sales_role": "潜力产品",
                "sales_role_code": "potential",
                "sales_trend": "基本稳定",
                "sales_trend_code": "stable",
            },
        }

        payload = self.service.build_payload(
            details=details, facts=facts, metrics=metrics, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="7d",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc",
            metric_scope={"status": "available", "window": {"period_code": "30d"}},
        )

        distribution = {item["id"]: item["count"] for item in payload["distribution"]}
        self.assertEqual({101: 1, 102: 1, 103: 0, 104: 0}, distribution)
        self.assertEqual(payload["kpis"]["sku_count"], sum(distribution.values()))
        self.assertEqual([101, 102, 103, 104], payload["rules"]["aggregation_priority_ids"])
        trend_panel = next(item for item in payload["breakdowns"] if item["key"] == "sales_trend")
        trend_counts = {item["key"]: item["msku_count"] for item in trend_panel["buckets"]}
        self.assertEqual(1, trend_counts["accelerating"])
        self.assertEqual(1, trend_counts["stable"])
        self.assertEqual(0, trend_counts["declining"])
        self.assertEqual(0, payload["issue_counts"]["problem_role"])

    def test_sales_trend_breakdown_ignores_its_own_filter_but_final_rows_apply_it(self):
        payload = self.service.build_payload(
            details=DETAILS, facts=FACTS, metrics=METRICS, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc", analysis_parent_ids=[2, 12, 13],
            sales_roles=set(), sales_trends={"stopped"}, daily_sales_bands=set(), margin_bands=set(), problem="all",
            metric_scope={"status": "available", "window": {}},
        )

        self.assertEqual(["A2"], [row["msku"] for row in payload["rows"]])
        trend_panel = next(item for item in payload["breakdowns"] if item["key"] == "sales_trend")
        counts = {item["key"]: item["msku_count"] for item in trend_panel["buckets"]}
        self.assertEqual(1, counts["accelerating"])
        self.assertEqual(1, counts["stopped"])
        self.assertIn("近7日日均销量", trend_panel["description"])
        self.assertTrue(trend_panel["rules"])

    def test_diagnosis_compares_filtered_cohort_with_public_filter_baseline(self):
        payload = self.service.build_payload(
            details=DETAILS, facts=FACTS, metrics=METRICS, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc", analysis_parent_ids=[2, 12],
            sales_roles={"eliminate"}, daily_sales_bands=set(), margin_bands=set(), problem="all",
            metric_scope={"status": "available", "window": {"period_code": "30d"}},
        )

        diagnosis = payload["diagnosis"]
        items = {item["key"]: item for item in diagnosis["items"]}

        self.assertEqual(DETAILS[0]["label_name"], diagnosis["subject"]["parent_label"])
        self.assertEqual(1, diagnosis["subject"]["msku_count"])
        self.assertEqual(1, diagnosis["subject"]["condition_count"])
        self.assertEqual(1, items["zero_sales"]["current_count"])
        self.assertEqual(1.0, items["zero_sales"]["current_rate"])
        self.assertEqual(0.5, items["zero_sales"]["baseline_rate"])
        self.assertEqual(50.0, items["zero_sales"]["delta_pp"])
        self.assertEqual(1, items["negative_profit"]["current_count"])
        self.assertEqual(50.0, items["negative_profit"]["delta_pp"])
        self.assertEqual(50, diagnosis["business"]["sales_amount"])
        self.assertEqual(-5, diagnosis["business"]["order_gross_profit"])
        self.assertEqual(-0.1, diagnosis["business"]["order_gross_margin"])

    def test_conflicts_are_scoped_to_the_same_label_period(self):
        facts = [
            {**FACTS[0], "label_id": 101, "label_period": "7d"},
            {**FACTS[0], "label_id": 102, "label_period": "30d"},
        ]
        payload = self.service.build_payload(
            details=DETAILS, facts=facts, metrics={}, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc",
        )

        self.assertEqual(0, payload["health"]["mutual_exclusion_conflict_count"])

    def test_selected_label_period_scopes_current_parent_distribution_conditions_and_rows(self):
        facts = [
            {**FACTS[0], "msku": "A1", "label_id": 101, "label_period": "7d"},
            {**FACTS[0], "msku": "A1", "label_id": 102, "label_period": "30d"},
            {**FACTS[0], "msku": "A2", "label_id": 102, "label_period": "7d"},
            {**FACTS[0], "msku": "A2", "label_id": 101, "label_period": "30d"},
        ]
        payload = self.service.build_payload(
            details=DETAILS, facts=facts, metrics={}, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="7d",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="msku", sort_dir="asc",
        )

        self.assertEqual({101: 1, 102: 1}, {item["id"]: item["count"] for item in payload["distribution"]})
        self.assertEqual(
            [DETAILS[0]["sub_label_name"], DETAILS[1]["sub_label_name"]],
            [row["current_label"] for row in payload["rows"]],
        )

        filtered = self.service.build_payload(
            details=DETAILS, facts=facts, metrics={}, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={1: {101}}, label_period="7d",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="msku", sort_dir="asc",
        )
        self.assertEqual(["A1"], [row["msku"] for row in filtered["rows"]])

    def test_page_size_controls_pagination(self):
        facts = []
        for index in range(25):
            facts.append({**FACTS[0], "msku": f"A{index:02d}"})
        payload = self.service.build_payload(
            details=DETAILS, facts=facts, metrics={}, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=15,
            sort_field="msku", sort_dir="asc",
        )

        self.assertEqual(15, payload["page_size"])
        self.assertEqual(15, len(payload["rows"]))

    def test_detail_rows_expose_existing_operating_fields_and_issue_summary(self):
        metrics = {
            **METRICS,
            ("欧洲站", "StoreA", "A1"): {
                **METRICS[("欧洲站", "StoreA", "A1")],
                "sales_amount_ex_tax": 88,
                "ending_inventory_qty": 24,
                "avg_inventory_qty": 18,
                "ad_spend": 6,
                "acos": 0.12,
                "tacos": 0.06,
                "return_count": 2,
                "net_amount": 92,
            },
        }
        payload = self.service.build_payload(
            details=DETAILS, facts=FACTS, metrics=metrics, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="msku", sort_dir="asc",
            metric_scope={"status": "available", "window": {"period_code": "30d"}},
        )

        rows = {row["msku"]: row for row in payload["rows"]}
        for field, value in {
            "sales_amount_ex_tax": 88,
            "ending_inventory_qty": 24,
            "avg_inventory_qty": 18,
            "ad_spend": 6,
            "acos": 0.12,
            "tacos": 0.06,
            "return_count": 2,
            "net_amount": 92,
        }.items():
            self.assertEqual(value, rows["A1"][field])
        self.assertEqual([], rows["A1"]["issue_codes"])
        self.assertEqual(
            ["标签冲突", "日销为 0", "订单毛利为负", "问题产品"],
            rows["A2"]["issue_labels"],
        )

    def test_build_payload_keeps_label_rows_without_local_metric_match(self):
        payload = self.service.build_payload(
            details=DETAILS,
            facts=FACTS[:1],
            metrics={},
            data_date="2026-07-13",
            parent_label_id=1,
            compare_parent_id=2,
            conditions={},
            label_period="all",
            country_category="all",
            store="all",
            keyword="",
            page=1,
            page_size=20,
            sort_field="sales_amount",
            sort_dir="desc",
        )

        self.assertEqual(1, payload["total"])
        self.assertIsNone(payload["rows"][0]["sales_amount"])
        self.assertEqual("暂无数据", payload["rows"][0]["sales_role"])

    def test_local_service_failure_is_not_reported_as_missing_msku_metrics(self):
        payload = self.service.build_payload(
            details=DETAILS,
            facts=FACTS[:1],
            metrics={},
            metric_scope={"status": "unavailable", "window": {}},
            data_date="2026-07-13",
            parent_label_id=1,
            compare_parent_id=2,
            conditions={},
            label_period="all",
            country_category="all",
            store="all",
            keyword="",
            page=1,
            page_size=20,
            sort_field="sales_amount",
            sort_dir="desc",
        )

        self.assertEqual(0, payload["issue_counts"]["missing_metrics"])
        self.assertEqual("本地经营指标暂不可用", payload["rows"][0]["data_status"])
        trend_panel = next(item for item in payload["breakdowns"] if item["key"] == "sales_trend")
        self.assertEqual("本地经营指标暂不可用", trend_panel["buckets"][-1]["label"])

    def test_sort_keeps_missing_metrics_after_measured_rows(self):
        payload = self.service.build_payload(
            details=DETAILS,
            facts=FACTS[:3],
            metrics={METRICS.keys().__iter__().__next__(): METRICS[("欧洲站", "StoreA", "A1")]},
            data_date="2026-07-13", parent_label_id=1, compare_parent_id=2, conditions={}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20, sort_field="sales_amount", sort_dir="desc",
        )

        self.assertEqual(["A1", "A2"], [row["msku"] for row in payload["rows"]])

    def test_category_status_distinguishes_disabled_and_developing(self):
        categories = self.service.build_categories(DETAILS, {101: {"fact_count": 2, "latest_date": "2026-07-13"}})
        by_id = {item["id"]: item for item in categories}

        self.assertEqual("available", by_id[1]["state"])
        self.assertEqual("disabled", by_id[12]["state"])
        self.assertEqual("developing", by_id[13]["state"])

    def test_category_exposes_periods_from_fact_statistics(self):
        categories = self.service.build_categories(DETAILS, {101: {"fact_count": 2, "latest_date": "2026-07-13", "periods": ["7d", "30d"]}})
        child = next(item for item in categories if item["id"] == 1)["children"][0]

        self.assertEqual(["7d", "30d"], child["periods"])

    def test_msku_profile_splits_analysis_and_site_scope_labels(self):
        service = LabelHubDataService.__new__(LabelHubDataService)
        service._cached_details = lambda: DETAILS
        service._cached_facts = lambda data_date: [
            FACTS[0],
            {**FACTS[0], "label_id": 1301, "label_period": "current"},
        ]
        service._cached_metrics = lambda data_date, period: {"status": "available", "window": {}, "metrics": {}}

        profile = service.get_msku_profile(
            data_date="2026-07-13", country_category="欧洲站", store="StoreA", msku="A1", metric_period="30d"
        )

        self.assertEqual([101], [item["id"] for item in profile["tag_profile"]["analysis_labels"]])
        self.assertEqual([1301], [item["id"] for item in profile["tag_profile"]["site_scope_labels"]])
        self.assertEqual(2, len(profile["tag_profile"]["labels"]))

    def test_fact_fetch_aggregates_remote_rows_before_expanding_them_locally(self):
        class Cursor:
            def __init__(self):
                self.sql = ""

            def execute(self, sql, params):
                self.sql = sql

            def fetchall(self):
                return [{
                    "data_date": "2026-07-13", "country_category": "欧洲站", "store": "StoreA", "msku": "A1",
                    "fact_tokens": "101@30d|201@current",
                }]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        connection = Connection()
        self.service._source_connection = lambda: connection

        facts = self.service._fetch_facts("2026-07-13", country_category="欧洲站", store="all", keyword="")

        self.assertEqual([101, 201], [item["label_id"] for item in facts])
        self.assertIn("group_concat", connection.cursor_instance.sql.lower())
        self.assertIn("group by data_date, country_category, store, msku", connection.cursor_instance.sql.lower())
        self.assertIn("dws_标签详情表", connection.cursor_instance.sql)
        self.assertIn("not in (4, 7, 13)", connection.cursor_instance.sql.lower())


if __name__ == "__main__":
    unittest.main()
