import json
import sys
import threading
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.label_hub_data import (
    CACHE_SECONDS,
    DIAGNOSTIC_PARENT_IDS,
    FACT_FETCH_EXCLUDED_PARENT_IDS,
    SOURCE_CONTENT_CHECK_SECONDS,
    SOURCE_INITIAL_CONTENT_CHECK_DELAY_SECONDS,
    LabelHubDataService,
    _evidence_object,
    _historical_role_history,
    _missing_metric_units,
    _public_business_row,
    _stockout_evidence_result,
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

    def test_stockout_historical_rows_select_v3_big_label_fields(self):
        class Cursor:
            def __init__(self):
                self.sql = ""

            def execute(self, sql, _params):
                self.sql = sql

            def fetchall(self):
                return []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Connection:
            def __init__(self):
                self.cursor_instance = Cursor()

            def cursor(self):
                return self.cursor_instance

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        connection = Connection()
        self.service._source_connection = lambda: connection

        self.service._fetch_stockout_historical_rows(
            data_date="2026-08-24",
            scope="business_unit",
        )

        sql = connection.cursor_instance.sql.lower()
        self.assertIn("pre_oos_role", sql)
        self.assertIn("combined_label_code", sql)
        self.assertIn("combined_label", sql)
        self.assertIn("auxiliary_json", sql)
        self.assertIn("evidence_json", sql)

    def test_label_fact_and_metric_cache_keeps_five_minutes(self):
        self.assertEqual(300, CACHE_SECONDS)

    def test_evidence_object_decodes_database_bytes_before_parsing_json(self):
        evidence = _evidence_object(b'{"metrics": {"daily_sales": 2}}')

        self.assertEqual({"metrics": {"daily_sales": 2}}, evidence)

    def test_historical_role_history_exposes_daily_sellable_inventory(self):
        history = _historical_role_history(
            {
                "confirmed_role_nodes": [
                    {
                        "node_date": "2026-07-29",
                        "window_start": "2026-06-30",
                        "window_end": "2026-07-29",
                        "role": "star",
                        "state": "normal",
                        "selected_for_stability": True,
                        "fba_available": 12,
                    },
                    {
                        "node_date": "2026-07-30",
                        "window_start": "2026-07-01",
                        "window_end": "2026-07-30",
                        "role": "unavailable",
                        "state": "data_anomaly",
                        "fba_available": None,
                    },
                ]
            }
        )

        self.assertEqual(12, history["nodes"][0]["sellable_inventory"])
        self.assertIsNone(history["nodes"][1]["sellable_inventory"])

    def test_stockout_evidence_result_distinguishes_confirmed_observed_and_pending_dates(self):
        cases = (
            (
                {"oos_start_date": "2026-08-23", "oos_start_confidence": "complete"},
                ("recent_start", "最近断货开始日", "2026-08-23"),
            ),
            (
                {"observed_oos_since_date": "2026-01-01", "oos_start_confidence": "left_boundary_incomplete"},
                ("observed_since", "最早观察到断货", "2026-01-01"),
            ),
            (
                {"oos_start_date": "2026-08-23", "oos_start_confidence": "event_boundary_incomplete"},
                ("pending", "断货起点待确认", "2026-08-23"),
            ),
        )

        for row, expected in cases:
            with self.subTest(confidence=row["oos_start_confidence"]):
                event = _stockout_evidence_result(row, {"nodes": []})["stockout_event"]
                self.assertEqual(expected, (event["date_kind"], event["date_label"], event["date"]))

    def test_stockout_evidence_result_translates_component_stability_codes(self):
        result = _stockout_evidence_result(
            {
                "historical_stability": "light_fluctuation",
                "role_stability": "normal",
                "sales_stability": "high",
                "margin_stability": "unavailable",
            },
            {"nodes": []},
        )

        self.assertEqual("轻度波动", result["stability"]["role_label"])
        self.assertEqual("波动", result["stability"]["sales_label"])
        self.assertEqual("依据不足", result["stability"]["margin_label"])

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
        quick_finished = threading.Event()
        content_calls = []
        service._fetch_quick_source_fingerprint = lambda: quick_finished.set() or ("quick",)
        service._fetch_content_source_fingerprint = lambda: content_calls.append(True) or ("content",)

        service._schedule_source_validation()

        self.assertTrue(quick_finished.wait(1))
        self.assertEqual([], content_calls)
        self.assertIsNotNone(service._source_content_checked_at)

    def test_source_validation_runs_deep_scan_after_content_interval(self):
        service = LabelHubDataService()
        service._source_content_checked_at = datetime.now() - timedelta(
            seconds=SOURCE_CONTENT_CHECK_SECONDS + 1
        )
        content_finished = threading.Event()
        service._fetch_quick_source_fingerprint = lambda: ("quick",)
        service._fetch_content_source_fingerprint = lambda: content_finished.set() or ("content",)

        service._schedule_source_validation()

        self.assertTrue(content_finished.wait(1))
        self.assertEqual(("content",), service._source_content_fingerprint)

    def test_cached_facts_fetches_diagnostic_labels_in_the_main_query(self):
        service = LabelHubDataService()
        calls = []
        service._fetch_facts = lambda data_date, **kwargs: calls.append(
            (data_date, kwargs)
        ) or [{"label_id": 1502}]
        service._cached_diagnostic_facts = lambda *args, **kwargs: self.fail(
            "main fact loading must not issue separate diagnostic scans"
        )

        facts = service._cached_facts("2026-08-17")

        self.assertEqual([{"label_id": 1502}], facts)
        self.assertEqual(
            [(
                "2026-08-17",
                {"excluded_parent_ids": FACT_FETCH_EXCLUDED_PARENT_IDS},
            )],
            calls,
        )

    def test_cached_facts_shares_one_inflight_load_between_threads(self):
        service = LabelHubDataService()
        fetch_started = threading.Event()
        release_fetch = threading.Event()
        calls = []

        def fetch(data_date, **kwargs):
            calls.append((data_date, kwargs))
            fetch_started.set()
            self.assertTrue(release_fetch.wait(1))
            return [{"label_id": 1502}]

        service._fetch_facts = fetch
        results = []
        first = threading.Thread(
            target=lambda: results.append(service._cached_facts("2026-08-17"))
        )
        second = threading.Thread(
            target=lambda: results.append(service._cached_facts("2026-08-17"))
        )

        first.start()
        self.assertTrue(fetch_started.wait(1))
        second.start()
        release_fetch.set()
        first.join(1)
        second.join(1)

        self.assertEqual(1, len(calls))
        self.assertEqual(
            [[{"label_id": 1502}], [{"label_id": 1502}]],
            results,
        )

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
                    "label_id": 20,
                    "label_name": "断货前销售角色",
                    "sub_label_id": role_id,
                    "sub_label_name": name,
                }
                for role_id, name in (
                    (2001, "明星产品"),
                    (2002, "潜力产品"),
                    (2003, "瘦狗产品"),
                    (2004, "问题产品"),
                )
            ],
        ]
        facts = [
            fact("欧洲站", "StoreA", "M1", 304, "current"),
            fact("欧洲站", "StoreB", "M1", 304, "current"),
            fact("美国站", "StoreC", "M2", 304, "current"),
            fact("欧洲站", "StoreA", "M1", 2001, "30d"),
            fact("欧洲站", "StoreB", "M1", 2002, "30d"),
            fact("欧洲站", "StoreB", "M1", 2003, "30d"),
            fact("美国站", "StoreC", "M2", 2004, "7d"),
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
            {2001: 1, 2002: 0, 2003: 0, 2004: 0},
            {item["id"]: item["business_unit_count"] for item in payload["roles"]},
        )

    def test_stockout_operating_status_partitions_current_stockout_into_eight_exclusive_labels(self):
        def fact(msku, label_id, label_period, evidence=None):
            return {
                "country_category": "欧洲站",
                "store": "StoreA",
                "msku": msku,
                "label_id": label_id,
                "label_period": label_period,
                "evidence_json": evidence or {},
            }

        def stockout_evidence(in_transit, local_quantity, fba_available=0):
            return {
                "metrics": {
                    "fba_available": fba_available,
                    "fba_in_transit": in_transit,
                    "local_quantity": local_quantity,
                }
            }

        def role_evidence(sales_qty, margin_rate=10, history_start="2026-07-01"):
            return {
                "type": "pre_oos_sales_role",
                "metrics": {
                    "daily_sales": sales_qty / 30,
                    "period_sales_qty": sales_qty,
                    "tag_margin_rate": margin_rate,
                },
                "oos": {"history_start_date": history_start, "oos_start_date": "2026-08-01"},
                "window": {
                    "period": "30d",
                    "days": 30,
                    "start": "2026-07-01",
                    "end": "2026-07-30",
                },
                "calculation": {"mode": "historical_backtrack", "status": "matched"},
            }

        facts = [
            fact("LOW", 304, "current", stockout_evidence(2, 2)),
            fact("NO_ROLE", 304, "current", stockout_evidence(5, 0)),
            fact("ZERO", 304, "current", stockout_evidence(5, 0)),
            fact("STAR", 304, "current", stockout_evidence(5, 0)),
            fact("POTENTIAL", 304, "current", stockout_evidence(5, 0)),
            fact("DOG", 304, "current", stockout_evidence(5, 0)),
            fact("LOSS", 304, "current", stockout_evidence(5, 0)),
            fact("MARGIN", 304, "current", stockout_evidence(5, 0)),
            fact("ZERO", 2004, "30d", role_evidence(0, 0)),
            fact("STAR", 2001, "30d", role_evidence(30, 20)),
            fact("POTENTIAL", 2002, "30d", role_evidence(20, 12)),
            fact("DOG", 2003, "30d", role_evidence(10, 8)),
            fact("LOSS", 2004, "30d", role_evidence(15, -3)),
            fact("MARGIN", 2004, "30d", role_evidence(15, 3)),
        ]

        payload = self.service.build_stockout_operating_status_summary(facts=facts, role_period="30d")

        self.assertEqual(8, payload["scope"]["business_unit_count"])
        self.assertEqual(
            {
                "low_inventory_edge": 1,
                "pre_oos_evidence_insufficient": 1,
                "full_period_zero_sales": 1,
                "star": 1,
                "potential": 1,
                "dog": 1,
                "loss_issue": 1,
                "low_margin_issue": 1,
            },
            {item["code"]: item["business_unit_count"] for item in payload["statuses"]},
        )
        self.assertEqual(6, payload["coverage"]["evaluable_count"])
        self.assertEqual(2, payload["coverage"]["non_evaluable_count"])
        self.assertEqual(0.75, payload["coverage"]["evaluable_rate"])
        self.assertEqual(0.25, payload["coverage"]["non_evaluable_rate"])
        self.assertEqual(
            {
                "low_inventory_edge": 0.5,
                "pre_oos_evidence_insufficient": 0.5,
                "full_period_zero_sales": 0.1667,
                "star": 0.1667,
                "potential": 0.1667,
                "dog": 0.1667,
                "loss_issue": 0.1667,
                "low_margin_issue": 0.1667,
            },
            {item["code"]: item["group_share"] for item in payload["statuses"]},
        )
        self.assertEqual(8, sum(item["business_unit_count"] for item in payload["statuses"]))

    def test_stockout_operating_status_uses_strict_less_than_five_inventory_boundary(self):
        def fact(msku, label_id, evidence):
            return {
                "country_category": "欧洲站",
                "store": "StoreA",
                "msku": msku,
                "label_id": label_id,
                "label_period": "current" if label_id == 304 else "30d",
                "evidence_json": evidence,
            }

        role_evidence = {
            "type": "pre_oos_sales_role",
            "metrics": {"daily_sales": 1, "period_sales_qty": 30, "tag_margin_rate": 20},
            "oos": {"history_start_date": "2026-07-01", "oos_start_date": "2026-08-01"},
            "window": {"period": "30d", "days": 30, "start": "2026-07-01", "end": "2026-07-30"},
            "calculation": {"mode": "historical_backtrack", "status": "matched"},
        }
        facts = [
            fact("FOUR", 304, {"metrics": {"fba_available": 0, "fba_in_transit": 1, "local_quantity": 3}}),
            fact("FIVE", 304, {"metrics": {"fba_available": 0, "fba_in_transit": 2, "local_quantity": 3}}),
            fact("FOUR", 2001, role_evidence),
            fact("FIVE", 2001, role_evidence),
        ]

        payload = self.service.build_stockout_operating_status_summary(facts=facts, role_period="30d")
        counts = {item["code"]: item["business_unit_count"] for item in payload["statuses"]}

        self.assertEqual(1, counts["low_inventory_edge"])
        self.assertEqual(1, counts["star"])
        self.assertEqual("<", payload["supply"]["threshold_operator"])

    def test_stockout_operating_status_tracks_insufficient_evidence_reasons_and_accepts_frozen_previous_day_role(self):
        def fact(msku, label_id, evidence):
            return {
                "country_category": "欧洲站",
                "store": "StoreA",
                "msku": msku,
                "label_id": label_id,
                "label_period": "current" if label_id == 304 else "30d",
                "evidence_json": evidence,
            }

        stockout = {"metrics": {"fba_available": 0, "fba_in_transit": 5, "local_quantity": 0}}
        short_history = {
            "type": "pre_oos_sales_role",
            "metrics": {"daily_sales": 1, "period_sales_qty": 30, "tag_margin_rate": 20},
            "oos": {"history_start_date": "2026-07-15", "oos_start_date": "2026-08-01"},
            "window": {"period": "30d", "days": 30, "start": "2026-07-01", "end": "2026-07-30"},
            "calculation": {"mode": "historical_backtrack", "status": "matched"},
        }
        copied_role = {
            "type": "pre_oos_sales_role",
            "metrics": {"daily_sales": 2, "period_sales_qty": 60, "tag_margin_rate": 18},
            "oos": {"oos_start_date": "2026-08-01"},
            "window": {"period": "30d", "days": 30, "start": "2026-07-01", "end": "2026-07-30"},
            "calculation": {"mode": "copy_previous_day_sales_role", "source_role_data_date": "2026-07-30"},
            "source_sales_role": {"sub_label_id": 101},
        }
        facts = [
            fact("MISSING", 304, stockout),
            fact("SHORT", 304, stockout),
            fact("COPIED", 304, stockout),
            fact("SHORT", 2001, short_history),
            fact("COPIED", 2001, copied_role),
        ]

        payload = self.service.build_stockout_operating_status_summary(facts=facts, role_period="30d")
        counts = {item["code"]: item["business_unit_count"] for item in payload["statuses"]}

        self.assertEqual(2, counts["pre_oos_evidence_insufficient"])
        self.assertEqual(1, counts["star"])
        self.assertEqual(
            {"role_missing": 1, "history_coverage_insufficient": 1},
            {item["code"]: item["count"] for item in payload["insufficient_reasons"]},
        )
        self.assertEqual(
            {"role_missing": 0.5, "history_coverage_insufficient": 0.5},
            {item["code"]: item["share"] for item in payload["insufficient_reasons"]},
        )
        self.assertEqual(
            [
                {
                    "code": "history_data_insufficient",
                    "label": "历史数据不足",
                    "count": 1,
                    "share": 0.5,
                }
            ],
            payload["display_insufficient_breakdown"],
        )

    def test_stockout_operating_status_members_reuse_the_summary_classification(self):
        stockout = {"metrics": {"fba_available": 0, "fba_in_transit": 5, "local_quantity": 0}}
        complete_role = {
            "type": "pre_oos_sales_role",
            "metrics": {"daily_sales": 1, "period_sales_qty": 30, "tag_margin_rate": 20},
            "oos": {"history_start_date": "2026-07-01", "oos_start_date": "2026-08-01"},
            "window": {"period": "30d", "days": 30, "start": "2026-07-01", "end": "2026-07-30"},
            "calculation": {"mode": "historical_backtrack", "status": "matched"},
        }
        short_history_role = {
            **complete_role,
            "oos": {"history_start_date": "2026-07-15", "oos_start_date": "2026-08-01"},
        }

        def fact(msku, label_id, evidence):
            return {
                "country_category": "欧洲站", "store": "StoreA", "msku": msku,
                "label_id": label_id, "label_period": "current" if label_id == 304 else "30d",
                "evidence_json": evidence,
            }

        facts = [
            fact("STAR", 304, stockout),
            fact("SHORT", 304, stockout),
            fact("STAR", 2001, complete_role),
            fact("SHORT", 2001, short_history_role),
        ]
        self.service.get_meta = lambda: {"default_data_date": "2026-08-01"}
        self.service._fetch_stockout_operating_status_facts = lambda data_date: facts

        star_members = self.service.get_stockout_operating_status_members(
            data_date="2026-08-01", role_period="30d", status_code="star"
        )
        history_members = self.service.get_stockout_operating_status_members(
            data_date="2026-08-01", role_period="30d",
            status_code="pre_oos_evidence_insufficient", reason_code="history_data_insufficient",
        )

        self.assertEqual({("欧洲站", "StoreA", "STAR")}, star_members)
        self.assertEqual({("欧洲站", "StoreA", "SHORT")}, history_members)

    def test_problem_status_members_combine_loss_and_low_margin_problem_products(self):
        stockout = {"metrics": {"fba_available": 0, "fba_in_transit": 5, "local_quantity": 0}}

        def role_evidence(margin_rate):
            return {
                "type": "pre_oos_sales_role",
                "metrics": {"daily_sales": 1, "period_sales_qty": 30, "tag_margin_rate": margin_rate},
                "oos": {"history_start_date": "2026-07-01", "oos_start_date": "2026-08-01"},
                "window": {"period": "30d", "days": 30, "start": "2026-07-01", "end": "2026-07-30"},
                "calculation": {"mode": "historical_backtrack", "status": "matched"},
            }

        def fact(msku, label_id, evidence):
            return {
                "country_category": "欧洲站", "store": "StoreA", "msku": msku,
                "label_id": label_id, "label_period": "current" if label_id == 304 else "30d",
                "evidence_json": evidence,
            }

        facts = [
            fact("LOSS", 304, stockout),
            fact("LOW_MARGIN", 304, stockout),
            fact("LOSS", 2004, role_evidence(-2)),
            fact("LOW_MARGIN", 2004, role_evidence(3)),
        ]
        self.service.get_meta = lambda: {"default_data_date": "2026-08-01"}
        self.service._fetch_stockout_operating_status_facts = lambda data_date: facts

        problem_members = self.service.get_stockout_operating_status_members(
            data_date="2026-08-01", role_period="30d", status_code="problem"
        )

        self.assertEqual(
            {("欧洲站", "StoreA", "LOSS"), ("欧洲站", "StoreA", "LOW_MARGIN")},
            problem_members,
        )

    def test_stockout_operating_status_fetches_compressed_evidence_from_local_snapshot(self):
        executed = {}

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, params):
                executed["sql"] = sql
                executed["params"] = params

            def fetchall(self):
                return []

        class Connection:
            def cursor(self):
                return Cursor()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        self.service._source_connection = lambda: Connection()

        self.assertEqual([], self.service._fetch_stockout_operating_status_facts("2026-08-17"))
        self.assertIn("uncompress(evidence_blob) as evidence_json", executed["sql"])
        self.assertNotIn("label_period, evidence_json", executed["sql"])

    def test_stockout_operating_trend_uses_non_overlapping_pre_oos_windows(self):
        def evidence(period, qty, role_id=2002, end="2026-07-31"):
            days = int(period.removesuffix("d"))
            start = (date.fromisoformat(end) - timedelta(days=days - 1)).isoformat()
            return {
                "label_id": role_id,
                "label_period": period,
                "evidence_json": {
                    "type": "pre_oos_sales_role",
                    "metrics": {"period_sales_qty": qty, "daily_sales": qty / days},
                    "oos": {"oos_start_date": "2026-08-01"},
                    "window": {"period": period, "days": days, "start": start, "end": end},
                },
            }

        cases = {
            "stable": {"7d": 7, "14d": 14, "30d": 30, "90d": 90},
            "accelerating": {"7d": 14, "14d": 21, "30d": 37, "90d": 97},
            "slowing": {"7d": 7, "14d": 21, "30d": 53, "90d": 173},
            "recent_start": {"7d": 7, "14d": 7, "30d": 23, "90d": 83},
            "stopped": {"7d": 0, "14d": 7, "30d": 23, "90d": 83},
            "volatile": {"7d": 14, "14d": 21, "30d": 53, "90d": 113},
        }

        for expected, quantities in cases.items():
            with self.subTest(expected=expected):
                result = self.service.derive_stockout_operating_trend(
                    {period: evidence(period, qty) for period, qty in quantities.items()},
                    baseline_role_id=2002,
                )
                self.assertEqual(expected, result["trend_code"])

        accelerating = self.service.derive_stockout_operating_trend(
            {
                "7d": evidence("7d", 14, 2001),
                "14d": evidence("14d", 21, 2002),
                "30d": evidence("30d", 37, 2002),
                "90d": evidence("90d", 97, 2003),
            },
            baseline_role_id=2002,
        )
        self.assertEqual(1.0, accelerating["interval_metrics"]["last7_vs_prior7_change"])
        self.assertEqual(0.5, accelerating["interval_metrics"]["last14_vs_prior16_change"])
        self.assertEqual("higher_than_long_term", accelerating["long_term_consistency"])

    def test_stockout_operating_trend_marks_bad_windows_and_non_monotonic_totals_unavailable(self):
        def evidence(period, qty, end="2026-07-31"):
            days = int(period.removesuffix("d"))
            start = (date.fromisoformat(end) - timedelta(days=days - 1)).isoformat()
            return {
                "label_id": 2002,
                "label_period": period,
                "evidence_json": {
                    "type": "pre_oos_sales_role",
                    "metrics": {"period_sales_qty": qty, "daily_sales": qty / days},
                    "oos": {"oos_start_date": "2026-08-01"},
                    "window": {"period": period, "days": days, "start": start, "end": end},
                },
            }

        bad_window = {period: evidence(period, qty) for period, qty in {"7d": 7, "14d": 14, "30d": 30}.items()}
        bad_window["7d"] = evidence("7d", 7, end="2026-07-30")
        result = self.service.derive_stockout_operating_trend(bad_window, baseline_role_id=2002)
        self.assertEqual("unavailable", result["trend_code"])
        self.assertIn("window_not_anchored_before_stockout", result["quality_reasons"])

        non_monotonic = {
            "7d": evidence("7d", 15),
            "14d": evidence("14d", 14),
            "30d": evidence("30d", 30),
        }
        result = self.service.derive_stockout_operating_trend(non_monotonic, baseline_role_id=2002)
        self.assertEqual("unavailable", result["trend_code"])
        self.assertIn("cumulative_metrics_non_monotonic", result["quality_reasons"])

    def test_stockout_operating_trend_does_not_require_90d_evidence(self):
        def evidence(period, qty):
            days = int(period.removesuffix("d"))
            end = date(2026, 7, 31)
            return {
                "label_id": 2002,
                "label_period": period,
                "evidence_json": {
                    "type": "pre_oos_sales_role",
                    "metrics": {"period_sales_qty": qty, "daily_sales": qty / days},
                    "oos": {"oos_start_date": "2026-08-01"},
                    "window": {
                        "period": period,
                        "days": days,
                        "start": (end - timedelta(days=days - 1)).isoformat(),
                        "end": end.isoformat(),
                    },
                },
            }

        result = self.service.derive_stockout_operating_trend(
            {"7d": evidence("7d", 7), "14d": evidence("14d", 14), "30d": evidence("30d", 30)},
            baseline_role_id=2002,
        )

        self.assertEqual("stable", result["trend_code"])
        self.assertEqual("unavailable", result["long_term_consistency"])

    def test_stockout_operating_country_scope_keeps_country_universe_rows_without_roles(self):
        stockout = {"metrics": {"fba_available": 0, "fba_in_transit": 5, "local_quantity": 0}}
        role = {
            "type": "pre_oos_sales_role",
            "metrics": {"daily_sales": 1, "period_sales_qty": 30, "tag_margin_rate": 20, "small_rank": 12},
            "oos": {"history_start_date": "2026-07-01", "oos_start_date": "2026-08-01"},
            "window": {"period": "30d", "days": 30, "start": "2026-07-02", "end": "2026-07-31"},
            "calculation": {"mode": "historical_backtrack", "status": "matched"},
        }

        def fact(label_id, period, country="", evidence=None):
            return {
                "country": country,
                "country_category": "欧洲站",
                "store": "StoreA",
                "msku": "M1",
                "label_id": label_id,
                "label_period": period,
                "evidence_json": evidence or {},
            }

        facts = [
            fact(304, "current", evidence=stockout),
            fact(401, "current", country="德国"),
            fact(401, "current", country="法国"),
            fact(2101, "30d", country="德国", evidence=role),
            # A 200x fact must never fill the missing French country role.
            fact(2001, "30d", evidence=role),
        ]

        payload = self.service.build_stockout_operating_status_summary(
            facts=facts,
            role_period="30d",
            scope="country",
        )
        counts = {item["code"]: item["business_unit_count"] for item in payload["statuses"]}

        self.assertEqual("country", payload["scope_mode"])
        self.assertEqual(2, payload["scope"]["country_record_count"])
        self.assertEqual(1, payload["scope"]["matched_business_unit_count"])
        self.assertEqual(1, counts["star"])
        self.assertEqual(1, counts["pre_oos_evidence_insufficient"])
        self.assertEqual(0.5, payload["coverage"]["role_evidence_rate"])
        self.assertTrue(all(item["record_count"] == item["business_unit_count"] for item in payload["statuses"]))

    def test_public_business_row_exposes_msku_stockout_before_role(self):
        public = _public_business_row({
            "country_category": "欧洲站",
            "store": "StoreA",
            "msku": "M1",
            "_label_facts": [
                {
                    "detail": {
                        "label_id": 20,
                        "label_name": "断货前销售角色",
                        "sub_label_name": "断货前-明星产品",
                    },
                    "label_id": 2001,
                    "label_period": "30d",
                }
            ],
        })

        self.assertEqual(
            [{"id": 2001, "label": "明星产品", "period": "30d"}],
            public["stockout_before_roles"],
        )
        self.assertEqual(20, public["labels"][0]["parent_id"])

    def test_stockout_before_role_evidence_queries_exact_msku_role_and_parses_json(self):
        class Cursor:
            def __init__(self):
                self.sql = ""
                self.params = {}

            def execute(self, sql, params):
                self.sql = sql
                self.params = params

            def fetchone(self):
                return {
                    "data_date": "2026-08-13",
                    "country_category": "欧洲站",
                    "store": "ShChu",
                    "msku": "SCH6038a",
                    "label_id": 2001,
                    "label_period": "30d",
                    "current_oos_flag": 1,
                    "oos_start_date": "2026-08-13",
                    "oos_start_method": "label_304_current_plus_most_recent_inventory_zero_run",
                    "oos_start_confidence": "complete",
                    "observed_oos_since_date": "2026-08-13",
                    "history_window_start": "2026-01-01",
                    "history_window_end": "2026-08-12",
                    "pre_oos_role": "potential",
                    "role_evidence_status": "available",
                    "role_source_date": "2026-08-12",
                    "valid_window_count": 4,
                    "dominant_role": "potential",
                    "dominant_role_share": 0.5,
                    "role_switch_rate": 0.5,
                    "recent_trend": "stable",
                    "daily_sales_trend": "improving",
                    "margin_trend": "stable",
                    "combined_label_code": "potential_daily_sales_improving",
                    "combined_label": "潜力·日销改善",
                    "historical_stability": "stable",
                    "role_stability": "stable",
                    "sales_stability": "stable",
                    "margin_stability": "light_fluctuation",
                    "evidence_json": '{"schema_version":"1.0","oos":{"oos_start_date":"2026-08-13"}}',
                    "historical_operating_evidence_json": json.dumps(
                        {
                            "pre_oos_role": "potential",
                            "confirmed_role_nodes": [
                                {"node_date": "2026-01-30", "window_start": "2026-01-01", "window_end": "2026-01-30", "role": "star", "state": "normal", "selected_for_stability": True, "daily_sales": 6.2, "margin_rate": 0.2},
                                {"node_date": "2026-03-01", "window_start": "2026-01-31", "window_end": "2026-03-01", "role": "potential", "state": "normal", "selected_for_stability": True, "daily_sales": 4.1, "margin_rate": 0.16},
                                {"node_date": "2026-03-31", "window_start": "2026-03-02", "window_end": "2026-03-31", "role": "potential", "state": "normal", "selected_for_stability": True, "daily_sales": 4.6, "margin_rate": 0.17},
                                {"node_date": "2026-04-30", "window_start": "2026-04-01", "window_end": "2026-04-30", "role": "dog", "state": "normal", "selected_for_stability": True, "daily_sales": 0.8, "margin_rate": 0.08},
                                {
                                    "node_date": "2026-05-01",
                                    "window_start": "2026-04-02",
                                    "window_end": "2026-05-01",
                                    "role": "dog",
                                    "state": "carried_oos",
                                    "source_node_date": "2026-04-30",
                                    "selected_for_stability": False,
                                },
                            ],
                        },
                        ensure_ascii=False,
                    ),
                }

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

        payload = self.service.get_stockout_before_role_evidence(
            data_date="2026-08-13",
            country_category="欧洲站",
            store="ShChu",
            msku="SCH6038a",
            role_period="30d",
        )

        self.assertEqual(2001, payload["role"]["id"])
        self.assertEqual("明星产品", payload["role"]["label"])
        self.assertEqual("2026-08-13", payload["evidence"]["oos"]["oos_start_date"])
        history = payload["historical_role_history"]
        self.assertEqual("insufficient", history["status"])
        self.assertEqual(4, history["valid_node_count"])
        self.assertEqual(4, history["calculated_node_count"])
        self.assertEqual(1, history["carried_node_count"])
        self.assertEqual(0, history["recovery_node_count"])
        self.assertEqual(0, history["unavailable_node_count"])
        self.assertEqual(
            {"code": "potential", "label": "潜力产品", "count": 2, "share": 0.5},
            history["dominant_role"],
        )
        self.assertEqual(
            [
                ("star", 1, 0.25),
                ("potential", 2, 0.5),
                ("dog", 1, 0.25),
                ("problem", 0, 0.0),
            ],
            [(item["code"], item["count"], item["share"]) for item in history["distribution"]],
        )
        self.assertEqual("2026-05-01", history["nodes"][-1]["window_end"])
        self.assertEqual("瘦狗产品", history["nodes"][-1]["label"])
        self.assertEqual("断货前角色沿用", history["nodes"][-1]["state_label"])
        self.assertEqual("2026-04-30", history["nodes"][-1]["source_node_date"])
        self.assertFalse(history["nodes"][-1]["selected_for_stability"])
        self.assertEqual("recent_start", payload["stockout_event"]["date_kind"])
        self.assertEqual("最近断货开始日", payload["stockout_event"]["date_label"])
        self.assertEqual("potential", payload["pre_oos_role"]["code"])
        self.assertEqual("potential", payload["historical_primary_role"]["code"])
        self.assertEqual(0.5, payload["historical_primary_role"]["share"])
        self.assertEqual("stable", payload["stability"]["code"])
        self.assertEqual("潜力·日销改善", payload["combined_conclusion"]["label"])
        self.assertEqual(
            ["2026-03-01", "2026-03-31", "2026-04-30"],
            [item["node_date"] for item in payload["metric_trend_nodes"]],
        )
        self.assertEqual(0.8, payload["metric_trend_nodes"][-1]["daily_sales"])
        self.assertEqual(0.08, payload["metric_trend_nodes"][-1]["margin_rate"])
        self.assertIn("s.oos_start_method", connection.cursor_instance.sql.lower())
        self.assertIn("s.combined_label", connection.cursor_instance.sql.lower())
        self.assertIn("label_id in (2001,2002,2003,2004)", connection.cursor_instance.sql.lower())
        self.assertIn("dashboard_stockout_historical_operating_snapshot", connection.cursor_instance.sql.lower())
        self.assertEqual("SCH6038a", connection.cursor_instance.params["msku"])
        self.assertEqual("business_unit", connection.cursor_instance.params["scope_mode"])

    def test_stockout_before_role_evidence_queries_exact_country_role(self):
        class Cursor:
            def __init__(self):
                self.sql = ""
                self.params = {}

            def execute(self, sql, params):
                self.sql = sql
                self.params = params

            def fetchone(self):
                return {
                    "data_date": "2026-08-13",
                    "country": "法国",
                    "country_category": "欧洲站",
                    "store": "ShChu",
                    "msku": "SCH6038a",
                    "label_id": 2102,
                    "label_period": "30d",
                    "evidence_json": '{"schema_version":"1.0","dimension":{"country":"法国"}}',
                }

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

        payload = self.service.get_stockout_before_role_evidence(
            data_date="2026-08-13",
            country_category="欧洲站",
            store="ShChu",
            msku="SCH6038a",
            role_period="30d",
            country="法国",
        )

        self.assertEqual("country", payload["scope"])
        self.assertEqual("法国", payload["identity"]["country"])
        self.assertEqual(2102, payload["role"]["id"])
        self.assertEqual("潜力产品", payload["role"]["label"])
        self.assertIn("country = %(country)s", connection.cursor_instance.sql.lower())
        self.assertIn("label_id in (2101,2102,2103,2104)", connection.cursor_instance.sql.lower())
        self.assertEqual("法国", connection.cursor_instance.params["country"])

    def test_stockout_before_role_evidence_rejects_invalid_period(self):
        with self.assertRaisesRegex(ValueError, "周期"):
            self.service.get_stockout_before_role_evidence(
                data_date="2026-08-13",
                country_category="欧洲站",
                store="ShChu",
                msku="SCH6038a",
                role_period="current",
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

    def test_unique_msku_metrics_ignore_case_without_merging_business_units(self):
        case_variant_fact = {
            **FACTS[0],
            "country_category": "Case variant scope",
            "store": "StoreB",
            "msku": "a1",
        }

        payload = self.service.build_payload(
            details=DETAILS,
            facts=[*FACTS, case_variant_fact],
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

        self.assertEqual(
            {
                "business_unit_count": 3,
                "unique_msku_count": 2,
                "cross_scope_msku_count": 1,
            },
            payload["population_summary"],
        )
        sales_role = next(item for item in payload["overview"] if item["id"] == 1)
        self.assertEqual(3, sales_role["business_unit_count"])
        self.assertEqual(2, sales_role["unique_msku_count"])
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
        self.assertIn("dashboard_label_detail_snapshot", connection.cursor_instance.sql)
        self.assertIn("dashboard_label_fact_snapshot", connection.cursor_instance.sql)
        self.assertIn("select sub_label_id", connection.cursor_instance.sql.lower())
        self.assertNotIn("not in (4, 7, 13", connection.cursor_instance.sql.lower())

        self.service._fetch_facts("2026-07-13", excluded_parent_ids={4, 7, 13, 14})
        self.assertIn("label_id not in (4,7,13,14)", connection.cursor_instance.sql.lower())


if __name__ == "__main__":
    unittest.main()
