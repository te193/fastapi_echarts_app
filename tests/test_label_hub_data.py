import sys
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.label_hub_data import (
    CACHE_SECONDS,
    DIAGNOSTIC_PARENT_IDS,
    SOURCE_INITIAL_CONTENT_CHECK_DELAY_SECONDS,
    LabelHubDataService,
    _missing_metric_units,
)


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
    def test_diagnostic_parents_are_filterable_but_hidden_from_analysis_categories(self):
        service = LabelHubDataService()
        details = DETAILS + [
            {
                "label_id": 15,
                "label_name": "全站点销售角色-产品问题标签",
                "sub_label_id": 1502,
                "sub_label_name": "潜力产品-低毛利",
                "tag_rule": "低毛利",
                "business_definition": "销售角色诊断",
                "business_owner": "运营",
                "label_category": "诊断",
                "update_frequency": "每日",
                "mutual_exclusion": "",
                "status": "已启用",
                "tagging_method": "auto_sql",
            }
        ]
        facts = FACTS + [
            {
                "data_date": "2026-07-13",
                "country_category": "欧洲站",
                "country": "",
                "store": "StoreA",
                "msku": "A1",
                "label_id": 1502,
                "label_period": "30d",
            }
        ]

        payload = service.build_payload(
            details=details,
            facts=facts,
            metrics=METRICS,
            data_date="2026-07-13",
            parent_label_id=1,
            compare_parent_id=2,
            conditions={15: {1502}},
            label_period="all",
            country_category="all",
            store="all",
            keyword="",
            page=1,
            page_size=20,
            sort_field="msku",
            sort_dir="asc",
        )

        self.assertEqual({15, 16}, DIAGNOSTIC_PARENT_IDS)
        self.assertNotIn(15, {item["id"] for item in payload["overview"]})
        self.assertEqual(["A1"], [row["msku"] for row in payload["rows"]])
        self.assertEqual("潜力产品-低毛利", payload["rows"][0]["role_diagnostic_summary"])

    def setUp(self):
        self.service = LabelHubDataService.__new__(LabelHubDataService)

    def test_label_fact_and_metric_cache_keeps_five_minutes(self):
        self.assertEqual(300, CACHE_SECONDS)

    def test_remote_invalidation_clears_label_caches_but_keeps_local_metrics(self):
        service = LabelHubDataService()
        service._meta_cache = {"default_data_date": "2026-07-21"}
        service._meta_cache_at = object()
        service._details_cache = (object(), [{"sub_label_id": 101}])
        service._facts_cache["2026-07-21"] = (object(), [{"label_id": 101}])
        service._metrics_cache[("2026-07-21", "30d")] = (object(), {"status": "available"})
        service._payload_cache[("cached",)] = (object(), {"rows": []})
        callback_calls = []
        service.register_source_invalidation_callback(lambda: callback_calls.append(True))

        service._invalidate_remote_caches()

        self.assertIsNone(service._meta_cache)
        self.assertIsNone(service._details_cache)
        self.assertEqual({}, service._facts_cache)
        self.assertEqual({}, service._payload_cache)
        self.assertIn(("2026-07-21", "30d"), service._metrics_cache)
        self.assertEqual([True], callback_calls)

    def test_quick_fingerprint_change_invalidates_cache_in_background(self):
        service = LabelHubDataService()
        service._source_quick_fingerprint = ("old",)
        service._source_content_fingerprint = ("old-content",)
        service._payload_cache[("cached",)] = (object(), {"rows": []})
        invalidated = threading.Event()
        service.register_source_invalidation_callback(invalidated.set)
        service._fetch_quick_source_fingerprint = lambda: ("new",)
        service._fetch_content_source_fingerprint = lambda: ("new-content",)

        service._schedule_source_validation()

        self.assertTrue(invalidated.wait(1))
        self.assertEqual({}, service._payload_cache)
        self.assertEqual(("new",), service._source_quick_fingerprint)

    def test_initial_source_validation_defers_the_deep_content_scan(self):
        service = LabelHubDataService()
        quick_finished = threading.Event()
        content_calls = []
        service._fetch_quick_source_fingerprint = lambda: quick_finished.set() or ("quick",)
        service._fetch_content_source_fingerprint = lambda: content_calls.append(True) or ("content",)

        service._schedule_source_validation()

        self.assertTrue(quick_finished.wait(1))
        self.assertEqual([], content_calls)

    def test_source_validation_runs_deep_scan_after_initial_delay(self):
        service = LabelHubDataService()
        service._source_validation_started_at = datetime.now() - timedelta(
            seconds=SOURCE_INITIAL_CONTENT_CHECK_DELAY_SECONDS + 1
        )
        content_finished = threading.Event()
        service._fetch_quick_source_fingerprint = lambda: ("quick",)
        service._fetch_content_source_fingerprint = lambda: content_finished.set() or ("content",)

        service._schedule_source_validation()

        self.assertTrue(content_finished.wait(1))
        self.assertEqual(("content",), service._source_content_fingerprint)

    def test_public_payload_reuses_the_same_filter_result(self):
        service = LabelHubDataService()
        build_calls = []
        service.get_meta = lambda: {"default_data_date": "2026-07-16"}
        service._cached_details = lambda: []
        service._cached_facts = lambda data_date: []
        service._cached_metrics = lambda data_date, period: {"status": "available", "window": {}, "metrics": {}}
        service._start_comparison_warmup = lambda period: None
        service.build_payload = lambda **kwargs: build_calls.append(kwargs) or {"build": len(build_calls)}

        first = service.get_payload(data_date="2026-07-16", metric_period="30d", page=1, page_size=20)
        second = service.get_payload(data_date="2026-07-16", metric_period="30d", page=1, page_size=20)
        third = service.get_payload(data_date="2026-07-16", metric_period="30d", page=2, page_size=20)

        self.assertIs(first, second)
        self.assertEqual(1, first["build"])
        self.assertEqual(2, third["build"])
        self.assertEqual(2, len(build_calls))

    def test_payload_honors_non_empty_requested_data_date(self):
        service = LabelHubDataService()
        requested_dates = []
        service.get_meta = lambda: {
            "default_data_date": "2026-07-16",
            "data_dates": ["2026-07-16"],
        }
        service._cached_details = lambda: DETAILS
        service._cached_facts = lambda data_date: requested_dates.append(data_date) or [
            {**FACTS[0], "data_date": data_date}
        ]
        service._cached_metrics = lambda data_date, period: {
            "status": "available", "window": {}, "metrics": {}
        }

        service.get_payload(data_date="2026-07-15", metric_period="30d", page_size=20)

        self.assertEqual(["2026-07-15"], requested_dates)

    def test_payload_uses_meta_date_when_requested_data_date_is_empty(self):
        service = LabelHubDataService()
        requested_dates = []
        service.get_meta = lambda: {"default_data_date": "2026-07-16", "data_dates": ["2026-07-16"]}
        service._cached_details = lambda: DETAILS
        service._cached_facts = lambda data_date: requested_dates.append(data_date) or [{**FACTS[0], "data_date": data_date}]
        service._cached_metrics = lambda data_date, period: {"status": "available", "window": {}, "metrics": {}}

        service.get_payload(data_date="", metric_period="30d", page_size=20)

        self.assertEqual(["2026-07-16"], requested_dates)

    def test_meta_bundle_limits_stats_filters_and_dates_to_latest_fact_date(self):
        class Cursor:
            def __init__(self):
                self.sql = ""
                self.params = None
                self.executions = []

            def execute(self, sql, params=None):
                self.sql, self.params = sql, params
                self.executions.append((sql, params))

            def fetchone(self):
                return {"data_date": "2026-07-16"}

            def fetchall(self):
                lowered = self.sql.lower()
                if "sub_label_id" in lowered and "order by label_id" in lowered:
                    return DETAILS
                if "select distinct data_date" in lowered:
                    return [{"data_date": "2026-07-16"}]
                return []

            def __enter__(self): return self
            def __exit__(self, *args): return False

        class Connection:
            def __init__(self): self.cursor_instance = Cursor()
            def cursor(self): return self.cursor_instance
            def __enter__(self): return self
            def __exit__(self, *args): return False

        connection = Connection()
        service = LabelHubDataService.__new__(LabelHubDataService)
        service._source_connection = lambda: connection
        service._facts_cache = {}
        service._fetch_facts = lambda *args, **kwargs: [
            {
                "data_date": "2026-07-16",
                "country_category": "欧洲站",
                "store": "StoreA",
                "msku": "A1",
                "label_id": 101,
                "label_period": "30d",
            },
            {
                "data_date": "2026-07-16",
                "country_category": "欧洲站",
                "store": "StoreA",
                "msku": "A2",
                "label_id": 101,
                "label_period": "30d",
            },
        ]

        _, stats, dates, filters = service._fetch_meta_bundle()

        self.assertEqual(["2026-07-16"], dates)
        self.assertEqual(2, stats[101]["fact_count"])
        self.assertEqual(["欧洲站"], filters["country_categories"])
        self.assertIn("2026-07-16", service._facts_cache)

    def test_missing_metric_units_only_merge_rows_within_the_same_business_unit(self):
        rows = [
            {"country_category": "欧洲站", "store": "StoreA", "msku": "A1", "_metric_present": False},
            {"country_category": "欧洲站", "store": "StoreA", "msku": "A1", "_metric_present": True},
            {"country_category": "英国站", "store": "StoreA", "msku": "A1", "_metric_present": False},
            {"country_category": "欧洲站", "store": "StoreA", "msku": "A2", "_metric_present": False},
        ]

        self.assertEqual(
            {("英国站", "StoreA", "A1"), ("欧洲站", "StoreA", "A2")},
            _missing_metric_units(rows),
        )

    def test_parse_conditions_uses_or_within_parent_and_and_across_parents(self):
        parsed = self.service.parse_conditions("1:101|102;2:201")

        self.assertEqual({1: {101, 102}, 2: {201}}, parsed)
        with self.assertRaises(ValueError):
            self.service.parse_conditions("broken")

    def test_analysis_categories_exclude_non_msku_grain_parents(self):
        station_role_detail = {
            "label_id": 21,
            "label_name": "断货前销售角色(站点)",
            "sub_label_id": 2101,
            "sub_label_name": "断货前-明星产品（站点）",
            "tag_rule": "站点断货前销售角色",
            "business_definition": "国家站点维度",
            "business_owner": "运营",
            "label_category": "经营",
            "update_frequency": "每日",
            "mutual_exclusion": "互斥",
            "status": "已启用",
            "tagging_method": "auto_sql",
        }
        details = DETAILS + [station_role_detail]

        analysis_ids = {
            item["id"] for item in self.service._analysis_categories(details, {})
        }
        filterable_ids = {
            item["id"] for item in self.service._filterable_categories(details, {})
        }

        self.assertNotIn(13, analysis_ids)
        self.assertNotIn(21, analysis_ids)
        self.assertIn(21, filterable_ids)

    def test_stockout_before_role_summary_uses_business_unit_key_period_and_coverage(self):
        def fact(country_category, store, msku, label_id, label_period):
            return {
                "country_category": country_category,
                "store": store,
                "msku": msku,
                "label_id": label_id,
                "label_period": label_period,
            }

        details = [
            {
                "label_id": 3,
                "label_name": "运营状态",
                "sub_label_id": 304,
                "sub_label_name": "断货中",
            },
            *[
                {
                    "label_id": 21,
                    "label_name": "断货前销售角色(站点)",
                    "sub_label_id": role_id,
                    "sub_label_name": name,
                }
                for role_id, name in (
                    (2101, "明星产品"),
                    (2102, "潜力产品"),
                    (2103, "瘦狗产品"),
                    (2104, "问题产品"),
                )
            ],
        ]
        facts = [
            fact("欧洲站", "StoreA", "M1", 304, "current"),
            fact("欧洲站", "StoreB", "M1", 304, "current"),
            fact("美国站", "StoreC", "M2", 304, "current"),
            fact("欧洲站", "StoreA", "M1", 2101, "30d"),
            fact("欧洲站", "StoreB", "M1", 2102, "30d"),
            fact("欧洲站", "StoreB", "M1", 2103, "30d"),
            fact("美国站", "StoreC", "M2", 2104, "7d"),
        ]

        payload = self.service.build_stockout_before_role_summary(
            details=details,
            facts=facts,
            role_period="30d",
        )

        self.assertEqual(3, payload["scope"]["business_unit_count"])
        self.assertEqual(2, payload["scope"]["unique_msku_count"])
        self.assertEqual(1, payload["coverage"]["identified_count"])
        self.assertEqual(1, payload["coverage"]["missing_count"])
        self.assertEqual(1, payload["coverage"]["conflict_count"])
        self.assertEqual(
            {2101: 1, 2102: 0, 2103: 0, 2104: 0},
            {item["id"]: item["business_unit_count"] for item in payload["roles"]},
        )

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

    def test_operation_distribution_counts_active_return_stage_intersections(self):
        details = [
            {
                "label_id": 3,
                "label_name": "运营状态",
                "sub_label_id": child_id,
                "sub_label_name": child_name,
                "tag_rule": "",
                "business_definition": "",
                "business_owner": "运营",
                "label_category": "经营",
                "update_frequency": "日",
                "mutual_exclusion": "互斥",
                "status": "已启用",
                "tagging_method": "auto_sql",
            }
            for child_id, child_name in (
                (301, "正常在售"),
                (302, "测款扶持"),
                (303, "返厂品"),
                (304, "断货中"),
                (305, "清仓中"),
                (306, "停售"),
            )
        ] + [
            {
                "label_id": 5,
                "label_name": "返厂品阶段下钻",
                "sub_label_id": child_id,
                "sub_label_name": child_name,
                "tag_rule": "",
                "business_definition": "",
                "business_owner": "运营",
                "label_category": "经营",
                "update_frequency": "日",
                "mutual_exclusion": "互斥",
                "status": "已启用",
                "tagging_method": "auto_sql",
            }
            for child_id, child_name in (
                (501, "观察期"),
                (502, "运营干预期"),
                (503, "持续干预期"),
            )
        ]
        facts = []
        for msku, operation_id, return_stage_id in (
            ("NORMAL", 301, None),
            ("TESTING", 302, None),
            ("RETURN", 303, 501),
            ("STOCKOUT", 304, 502),
            ("CLEARANCE", 305, None),
            ("STOPPED", 306, 503),
            ("PLAIN-STOCKOUT", 304, None),
        ):
            facts.append({
                "data_date": "2026-07-28",
                "country_category": "欧洲站",
                "store": "StoreA",
                "msku": msku,
                "label_id": operation_id,
                "label_period": "current",
            })
            if return_stage_id:
                facts.append({
                    "data_date": "2026-07-28",
                    "country_category": "欧洲站",
                    "store": "StoreA",
                    "msku": msku,
                    "label_id": return_stage_id,
                    "label_period": "current",
                })

        payload = self.service.build_payload(
            details=details,
            facts=facts,
            metrics={},
            data_date="2026-07-28",
            parent_label_id=3,
            compare_parent_id=5,
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

        distribution = {item["id"]: item for item in payload["distribution"]}
        self.assertEqual(1, distribution[304]["return_stage_count"])
        self.assertEqual(1, distribution[306]["return_stage_count"])
        self.assertEqual(3, payload["return_stage_attribution"]["active_return_count"])
        self.assertEqual(3, payload["return_stage_attribution"]["reconciled_count"])
        self.assertEqual(
            {
                "effective_stockout_count": 1,
                "operating_count": 5,
                "return_restockout_count": 1,
                "rate": 0.2,
            },
            payload["operating_stockout_rate"],
        )

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

    def test_analysis_panels_count_business_units_and_keep_unique_msku_auxiliary(self):
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
        self.assertEqual(4, payload["issue_counts"]["all"])
        self.assertEqual(0, payload["issue_counts"]["problem_role"])
        self.assertEqual(2, payload["issue_counts"]["zero_sales"])
        self.assertEqual(4, payload["diagnosis"]["subject"]["msku_count"])

        distribution = {item["id"]: item["count"] for item in payload["distribution"]}
        self.assertEqual(4, distribution[101])
        self.assertEqual(0, distribution[102])
        sales_trend = next(item for item in payload["breakdowns"] if item["key"] == "sales_trend")
        buckets = {item["key"]: item["msku_count"] for item in sales_trend["buckets"]}
        self.assertEqual(2, buckets["accelerating"])
        self.assertEqual(2, buckets["stopped"])
        lifecycle_cell = next(
            item for item in payload["matrix"]["cells"]
            if item["row_id"] == 101 and item["col_id"] == 201
        )
        self.assertEqual(2, lifecycle_cell["count"])

    def test_aggregated_panels_choose_labels_within_each_business_unit(self):
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
        self.assertEqual({101: 1, 102: 1, 103: 1, 104: 1}, distribution)
        self.assertEqual(payload["population_summary"]["business_unit_count"], sum(distribution.values()))
        self.assertEqual([101, 102, 103, 104], payload["rules"]["aggregation_priority_ids"])
        trend_panel = next(item for item in payload["breakdowns"] if item["key"] == "sales_trend")
        trend_counts = {item["key"]: item["msku_count"] for item in trend_panel["buckets"]}
        self.assertEqual(1, trend_counts["accelerating"])
        self.assertEqual(1, trend_counts["stable"])
        self.assertEqual(1, trend_counts["declining"])
        self.assertEqual(1, trend_counts["stopped"])
        self.assertEqual(1, payload["issue_counts"]["problem_role"])

    def test_problem_role_issue_uses_remote_sales_role_label_scope(self):
        details = [
            *DETAILS,
            {**DETAILS[0], "sub_label_id": 104, "sub_label_name": "问题产品"},
        ]
        facts = [
            {**FACTS[0], "msku": "A1", "label_id": 104, "label_period": "30d"},
            {**FACTS[0], "msku": "A2", "label_id": 101, "label_period": "30d"},
        ]
        metrics = {
            ("欧洲站", "StoreA", "A1"): {
                **METRICS[("欧洲站", "StoreA", "A1")],
                "sales_role": "明星产品",
                "sales_role_code": "star",
            },
            ("欧洲站", "StoreA", "A2"): {
                **METRICS[("欧洲站", "StoreA", "A2")],
                "sales_role": "问题产品",
                "sales_role_code": "eliminate",
            },
        }

        payload = self.service.build_payload(
            details=details, facts=facts, metrics=metrics, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="30d",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc",
            metric_scope={"status": "available", "window": {"period_code": "30d"}},
        )
        filtered = self.service.build_payload(
            details=details, facts=facts, metrics=metrics, data_date="2026-07-13",
            parent_label_id=1, compare_parent_id=2, conditions={}, label_period="30d",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="sales_amount", sort_dir="desc", problem="problem_role",
            metric_scope={"status": "available", "window": {"period_code": "30d"}},
        )

        problem_distribution = next(item for item in payload["distribution"] if item["id"] == 104)
        self.assertEqual(problem_distribution["count"], payload["issue_counts"]["problem_role"])
        self.assertEqual(["A1"], [row["msku"] for row in filtered["rows"]])
        self.assertIn("problem_role", filtered["rows"][0]["issue_codes"])

    def test_remote_breakdown_and_condition_use_the_selected_analysis_period(self):
        facts = [
            {**FACTS[1], "msku": "A1"},
            {**FACTS[1], "msku": "A2"},
            {**FACTS[0], "msku": "A1", "label_id": 101, "label_period": "7d"},
            {**FACTS[0], "msku": "A1", "label_id": 102, "label_period": "30d"},
            {**FACTS[0], "msku": "A2", "label_id": 102, "label_period": "7d"},
            {**FACTS[0], "msku": "A2", "label_id": 101, "label_period": "30d"},
        ]

        payload = self.service.build_payload(
            details=DETAILS, facts=facts, metrics=METRICS, data_date="2026-07-13",
            parent_label_id=2, compare_parent_id=1, conditions={1: {101}}, label_period="all",
            country_category="all", store="all", keyword="", page=1, page_size=20,
            sort_field="msku", sort_dir="asc", analysis_parent_ids=[1, 8],
            analysis_periods=["7d", "all"],
            metric_scope={"status": "available", "window": {"period_code": "30d"}},
        )

        sales_role = next(item for item in payload["breakdowns"] if item.get("parent_id") == 1)
        counts = {item["id"]: item["msku_count"] for item in sales_role["buckets"]}
        self.assertEqual({101: 1, 102: 1}, counts)
        self.assertEqual(0, sales_role["analysis_slot"])
        self.assertEqual("7d", sales_role["label_period"])
        self.assertEqual(["7d", "30d"], sales_role["periods"])
        self.assertEqual(["A1"], [row["msku"] for row in payload["rows"]])

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
                "settlement_gross_profit": 16,
                "settlement_gross_margin": 0.18,
                "ad_spend": 6,
                "ad_sales": 30,
                "ad_orders": 3,
                "ad_clicks": 12,
                "ad_impressions": 300,
                "acos": 0.12,
                "tacos": 0.06,
                "sessions_total": 80,
                "return_count": 2,
                "return_amount": 8,
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
            "settlement_gross_profit": 16,
            "settlement_gross_margin": 0.18,
            "ad_spend": 6,
            "ad_sales": 30,
            "ad_orders": 3,
            "ad_clicks": 12,
            "ad_impressions": 300,
            "acos": 0.12,
            "tacos": 0.06,
            "sessions_total": 80,
            "return_count": 2,
            "return_amount": 8,
            "net_amount": 92,
        }.items():
            self.assertEqual(value, rows["A1"][field])
        self.assertEqual([], rows["A1"]["issue_codes"])
        self.assertEqual(["标签冲突", "日销为 0", "订单毛利为负"], rows["A2"]["issue_labels"])

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
        service.get_meta = lambda: {"default_data_date": "2026-07-13"}
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

    def test_business_detail_base_rows_include_label_profile_fields(self):
        service = LabelHubDataService.__new__(LabelHubDataService)
        raw_row = {
            "country_category": "欧洲站",
            "store": "StoreA",
            "msku": "MSKU-1",
            "_metric_present": False,
            "_label_facts": [{**FACTS[0], "detail": DETAILS[0]}],
        }
        service.get_payload = lambda **kwargs: {
            "scope": {"local_metrics_status": "available"},
            "_comparison_rows": [raw_row],
        }

        payload = service.get_business_detail_base_rows()

        self.assertEqual([101], [item["id"] for item in payload["rows"][0]["labels"]])
        self.assertTrue(payload["rows"][0]["label_summary"])
        self.assertIs(payload["rows"][0]["metric_present"], False)

    def test_diagnostic_base_rows_cache_the_expensive_internal_payload(self):
        service = LabelHubDataService()
        service.get_meta = lambda: {"default_data_date": "2026-07-13"}
        calls = []
        expected_rows = [
            {
                "country_category": "欧洲站",
                "store": "StoreA",
                "msku": "MSKU-1",
            }
        ]

        def get_payload(**filters):
            calls.append(filters)
            return {"_comparison_rows": list(expected_rows)}

        service.get_payload = get_payload
        filters = {
            "data_date": "2026-07-13",
            "metric_period": "30d",
            "country_category": "all",
            "store": "all",
        }

        first = service.get_diagnostic_base_rows(**filters)
        second = service.get_diagnostic_base_rows(**filters)

        self.assertEqual(expected_rows, first)
        self.assertEqual(expected_rows, second)
        self.assertEqual(1, len(calls))

    def test_fact_fetch_aggregates_remote_rows_before_expanding_them_locally(self):
        class Cursor:
            def __init__(self):
                self.sql = ""

            def execute(self, sql, params):
                self.sql = sql

            def fetchall(self):
                return [{
                    "data_date": "2026-07-13", "country": "德国", "country_category": "欧洲站", "store": "StoreA", "msku": "A1",
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
        self.assertIn("group by data_date, country, country_category, store, msku", connection.cursor_instance.sql.lower())
        self.assertIn("dws_标签详情表", connection.cursor_instance.sql)
        self.assertIn("select sub_label_id", connection.cursor_instance.sql.lower())
        self.assertNotIn("not in (4, 7, 13", connection.cursor_instance.sql.lower())

        self.service._fetch_facts("2026-07-13", excluded_parent_ids={4, 7, 13, 14})
        self.assertIn("label_id not in (4,7,13,14)", connection.cursor_instance.sql.lower())


if __name__ == "__main__":
    unittest.main()
