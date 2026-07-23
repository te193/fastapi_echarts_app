import unittest
from datetime import date, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from app.services import country_label_hub_data
from app.services.country_label_hub_data import CountryLabelHubDataService
from app.services.label_hub_data import LabelHubDataService


def detail(parent, parent_label, child, child_label, periods=None, mutual="互斥"):
    return {
        "label_id": parent, "label_name": parent_label, "sub_label_id": child,
        "sub_label_name": child_label, "tag_rule": f"{child_label}规则",
        "business_definition": f"{child_label}定义", "business_owner": "运营",
        "label_category": "国家", "update_frequency": "每天",
        "mutual_exclusion": mutual, "status": "已启用", "tagging_method": "auto_sql",
    }


DETAILS = [
    detail(4, "定价", 401, "健康利润区"), detail(4, "定价", 402, "低毛利区"),
    detail(7, "站点状态", 701, "正常覆盖"), detail(7, "站点状态", 702, "部分覆盖"),
    detail(13, "国家销售角色", 1301, "明星产品"), detail(13, "国家销售角色", 1304, "问题产品"),
    detail(14, "站点生命周期", 1401, "成长期"), detail(14, "站点生命周期", 1402, "成熟期"),
]

FACTS = [
    {"data_date": "2026-07-15", "country": "美国", "country_category": "北美站", "store": "StoreA", "msku": "A1", "label_id": 401, "label_period": "current"},
    {"data_date": "2026-07-15", "country": "美国", "country_category": "北美站", "store": "StoreA", "msku": "A1", "label_id": 701, "label_period": "current"},
    {"data_date": "2026-07-15", "country": "美国", "country_category": "北美站", "store": "StoreA", "msku": "A1", "label_id": 1301, "label_period": "30d"},
    {"data_date": "2026-07-15", "country": "美国", "country_category": "北美站", "store": "StoreA", "msku": "A1", "label_id": 1401, "label_period": "30d"},
    {"data_date": "2026-07-15", "country": "墨西哥", "country_category": "墨西哥站", "store": "StoreA", "msku": "A1", "label_id": 402, "label_period": "current"},
    {"data_date": "2026-07-15", "country": "墨西哥", "country_category": "墨西哥站", "store": "StoreA", "msku": "A1", "label_id": 702, "label_period": "current"},
    {"data_date": "2026-07-15", "country": "墨西哥", "country_category": "墨西哥站", "store": "StoreA", "msku": "A1", "label_id": 1304, "label_period": "30d"},
    {"data_date": "2026-07-15", "country": "墨西哥", "country_category": "墨西哥站", "store": "StoreA", "msku": "A1", "label_id": 1402, "label_period": "30d"},
]

METRICS = {
    ("北美站", "StoreA", "A1"): {"sales_qty": 10, "daily_sales": 1, "sales_amount": 100, "order_gross_profit": 20, "order_gross_margin": 0.2, "ending_inventory_qty": 50, "sales_role_code": "star", "sales_trend_code": "stable", "sales_trend": "基本稳定", "daily_sales_band_code": "1_5", "daily_sales_band": "日销 1–5", "margin_band_code": "15_25", "margin_band": "15%–25%"},
    ("墨西哥站", "StoreA", "A1"): {"sales_qty": 5, "daily_sales": 0, "sales_amount": 50, "order_gross_profit": -5, "order_gross_margin": -0.1, "ending_inventory_qty": 50, "sales_role_code": "eliminate", "sales_trend_code": "stopped", "sales_trend": "近期停销", "daily_sales_band_code": "zero", "daily_sales_band": "日销 0", "margin_band_code": "lt5", "margin_band": "<5%"},
}


class FakeShared:
    def __init__(self):
        builder = LabelHubDataService.__new__(LabelHubDataService)
        stats = {child: {"fact_count": 1, "latest_date": "2026-07-15", "periods": ["30d" if parent in {13, 14} else "current"]} for parent, child in [(item["label_id"], item["sub_label_id"]) for item in DETAILS]}
        self.categories = builder.build_categories(DETAILS, stats)

    def get_meta(self):
        return {"default_data_date": "2026-07-15", "data_dates": ["2026-07-15"], "excluded_categories": self.categories, "metric_periods": [{"key": "30d", "label": "30天"}], "country_categories": ["北美站", "墨西哥站"], "stores": ["StoreA"], "local_breakdowns": []}

    def _cached_details(self): return DETAILS
    def _cached_facts(self, data_date): return FACTS
    def _cached_metrics(self, data_date, metric_period): return {"status": "available", "window": {"period_code": "30d", "period_start": "2026-06-16", "period_end": "2026-07-15"}, "metrics": METRICS}
    def parse_conditions(self, value): return LabelHubDataService.__new__(LabelHubDataService).parse_conditions(value)


class CountryLabelHubDataTests(unittest.TestCase):
    def setUp(self):
        self.service = CountryLabelHubDataService(FakeShared())

    def test_country_detail_count_uses_lightweight_cached_aggregate(self):
        executed = []

        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def execute(self, sql, params): executed.append((sql, params))
            def fetchone(self): return {"country_unit_count": 41}

        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def cursor(self): return Cursor()

        self.service._shared._source_connection = lambda: Connection()

        first = self.service.get_country_detail_count(data_date="2026-07-15", country_category="北美站")
        second = self.service.get_country_detail_count(data_date="2026-07-15", country_category="北美站")

        self.assertEqual({"country_unit_count": 41}, first)
        self.assertEqual(first, second)
        self.assertEqual(1, len(executed))
        self.assertIn("group by country, country_category, store, msku", executed[0][0].lower())

    def test_price_margin_interval_uses_listing_price_against_margin_ladder(self):
        ladder = {
            "available": True,
            "margin_prices": [
                {"margin": 35, "value": 20},
                {"margin": 30, "value": 18},
                {"margin": 25, "value": 16},
                {"margin": 20, "value": 15},
                {"margin": 15, "value": 14},
                {"margin": 10, "value": 13},
                {"margin": 5, "value": 12},
                {"margin": 0, "value": 10},
            ],
        }

        cases = [
            ({"available": True, "value": 19}, ladder, "30%–35%"),
            ({"available": True, "value": 18}, ladder, "30%–35%"),
            ({"available": True, "value": 20}, ladder, "≥35%"),
            ({"available": True, "value": 9.99}, ladder, "<0%"),
            ({"available": False}, ladder, "--"),
            ({"available": True, "value": 19}, {"available": False}, "--"),
        ]

        for price, limit_prices, expected in cases:
            with self.subTest(price=price, expected=expected):
                self.assertEqual(expected, country_label_hub_data._price_margin_interval(price, limit_prices))

    def test_country_page_only_exposes_four_country_scope_parents(self):
        self.assertEqual({4, 7, 13, 14}, {item["id"] for item in self.service.get_meta()["categories"]})

    def test_country_payload_ignores_stale_url_date_and_uses_latest_date(self):
        payload = self.service.get_payload(data_date="2026-07-14", metric_period="30d", page_size=20)

        self.assertEqual("2026-07-15", payload["data_date"])

    def test_meta_reuses_preaggregated_store_mapping_without_scanning_all_facts(self):
        shared = FakeShared()
        original_get_meta = shared.get_meta
        shared.get_meta = lambda: {**original_get_meta(), "stores_by_country": {"北美站": ["StoreA"]}}
        shared._cached_facts = lambda data_date: self.fail("meta should not scan the full fact cache")

        meta = CountryLabelHubDataService(shared).get_meta()

        self.assertEqual({"北美站": ["StoreA"]}, meta["stores_by_country"])

    def test_country_payload_only_fetches_country_parent_facts(self):
        shared = FakeShared()
        with patch.object(shared, "_fetch_facts", return_value=FACTS, create=True) as fetch_facts:
            CountryLabelHubDataService(shared).get_payload(metric_period="30d", page_size=20)

        fetch_facts.assert_called_once_with("2026-07-15", parent_ids=(4, 7, 13, 14))

    def test_country_profile_reuses_country_fact_cache_instead_of_global_fact_subset(self):
        shared = FakeShared()
        shared._cached_facts = lambda data_date: []
        with patch.object(shared, "_fetch_facts", return_value=FACTS, create=True):
            service = CountryLabelHubDataService(shared)
            row = service.get_payload(metric_period="30d", page_size=20)["rows"][0]
            profile = service.get_msku_profile(
                data_date="2026-07-15",
                metric_period="30d",
                country=row["country"],
                country_category=row["country_category"],
                store=row["store"],
                msku=row["msku"],
            )

        self.assertEqual(row["msku"], profile["identity"]["msku"])
        self.assertTrue(profile["tag_profile"]["labels"])

    def test_label_hub_country_profile_reuses_warm_country_facts_without_querying_again(self):
        shared = FakeShared()
        service = CountryLabelHubDataService(shared)
        service._facts_cache["2026-07-15"] = (datetime.now(), FACTS)

        with patch.object(
            shared,
            "_fetch_facts",
            side_effect=AssertionError("warm country facts should be reused"),
            create=True,
        ):
            facts = service._cached_profile_country_facts(
                "2026-07-15", "北美站", "StoreA", "A1"
            )

        self.assertEqual(4, len(facts))

    def test_label_hub_country_profile_keeps_current_store_scope_and_splits_role_periods(self):
        self.service._cached_listing_prices = lambda *_: (
            "2026-07-16",
            {"美国": {"value": 19.99, "currency": "$", "value_cny": 144.5, "available": True}},
        )
        self.service._cached_limit_prices = lambda *_: (
            "2026-07-16",
            {"美国": {"margin_price_35": 21.5, "margin_price_10": 16.2, "margin_prices": [{"margin": 35, "value": 21.5}, {"margin": 10, "value": 16.2}], "currency": "USD", "available": True}},
        )
        self.service._cached_country_profile_metrics = lambda *_: {
            "window": {"period_code": "30d", "period_start": "2026-06-16", "period_end": "2026-07-15"},
            "sku": "SKU-01",
            "metrics": {"美国": {"sales_qty": 12, "sales_amount": 180, "order_gross_profit": 30, "small_category_ranking": 55}},
        }

        profile = self.service.get_label_hub_country_profile(
            country_category="北美站",
            store="StoreA",
            msku="A1",
        )

        self.assertEqual("2026-07-15", profile["scope"]["label_date"])
        self.assertEqual("SKU-01", profile["identity"]["sku"])
        self.assertEqual("2026-07-16", profile["scope"]["price_snapshot_date"])
        self.assertEqual("2026-07-16", profile["scope"]["limit_price_snapshot_date"])
        self.assertEqual(["美国"], [item["country"] for item in profile["countries"]])
        self.assertEqual("明星产品", profile["countries"][0]["sales_roles"]["30d"]["label"])
        self.assertIsNone(profile["countries"][0]["sales_roles"]["7d"])
        self.assertEqual(21.5, profile["countries"][0]["limit_prices"]["margin_price_35"])
        self.assertEqual("--", profile["countries"][0]["price_margin_interval"])
        self.assertEqual(
            [{"margin": 35, "value": 21.5}, {"margin": 10, "value": 16.2}],
            profile["countries"][0]["limit_prices"]["margin_prices"],
        )
        self.assertEqual(55, profile["countries"][0]["metrics"]["small_category_ranking"])
        self.assertTrue(profile["countries"][0]["price"]["available"])
        self.assertEqual(12, profile["countries"][0]["metrics"]["sales_qty"])
        self.assertEqual("30d", profile["scope"]["metric_period"])

    def test_label_hub_country_profile_loads_independent_sources_concurrently(self):
        barrier = Barrier(3)
        self.service._cached_profile_country_facts = lambda *_: FACTS[:4]

        def listing(*_):
            barrier.wait(timeout=0.2)
            return "2026-07-16", {}

        def limits(*_):
            barrier.wait(timeout=0.2)
            return "2026-07-16", {}

        def metrics(*_):
            barrier.wait(timeout=0.2)
            return {"window": {}, "metrics": {}, "sku": "SKU-01"}

        self.service._cached_listing_prices = listing
        self.service._cached_limit_prices = limits
        self.service._cached_country_profile_metrics = metrics

        profile = self.service.get_label_hub_country_profile(
            country_category="北美站", store="StoreA", msku="A1"
        )

        self.assertEqual("available", profile["scope"]["listing_price_status"])
        self.assertEqual("available", profile["scope"]["limit_price_status"])
        self.assertEqual("available", profile["scope"]["local_metrics_status"])

    def test_country_profile_daily_sales_uses_inventory_days_and_returns_sku(self):
        class FakeCursor:
            def __init__(self):
                self.query_count = 0

            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, *_): self.query_count += 1
            def fetchone(self): return {"period_end": date(2026, 7, 15)}
            def fetchall(self):
                return [{
                    "country": "美国", "sku": "SKU-01", "sales_qty": 12,
                    "inventory_days": 3, "sales_amount": 180,
                    "order_gross_profit": 30,
                }]

        class FakeConnection:
            def __init__(self): self.fake_cursor = FakeCursor()
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def cursor(self): return self.fake_cursor

        self.service._shared._dashboard = SimpleNamespace(
            schemas=None,
            connect=lambda: FakeConnection(),
        )
        with patch("app.services.country_label_hub_data.render_sql", side_effect=lambda table, _: table):
            result = self.service._cached_country_profile_metrics(
                "2026-07-15", "北美站", "StoreA", "A1", "30d"
            )

        self.assertEqual("SKU-01", result["sku"])
        self.assertEqual(3, result["metrics"]["美国"]["inventory_days"])
        self.assertEqual(4, result["metrics"]["美国"]["daily_sales"])

    def test_country_profile_daily_sales_is_zero_without_inventory_days(self):
        class FakeCursor:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, *_): return None
            def fetchone(self): return {"period_end": date(2026, 7, 15)}
            def fetchall(self):
                return [{
                    "country": "美国", "sku": "SKU-01", "sales_qty": 12,
                    "inventory_days": 0, "sales_amount": 180,
                    "order_gross_profit": 30,
                }]

        class FakeConnection:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def cursor(self): return FakeCursor()

        self.service._shared._dashboard = SimpleNamespace(
            schemas=None,
            connect=lambda: FakeConnection(),
        )
        with patch("app.services.country_label_hub_data.render_sql", side_effect=lambda table, _: table):
            result = self.service._cached_country_profile_metrics(
                "2026-07-15", "北美站", "StoreA", "A1", "30d"
            )

        self.assertEqual(0, result["metrics"]["美国"]["daily_sales"])

    def test_country_profile_deduplicates_repeated_label_facts(self):
        facts = [
            {**fact, "country": "CountryA", "country_category": "RegionA"}
            for fact in FACTS[:4]
        ]
        self.service._cached_profile_country_facts = lambda *_: facts + [dict(facts[0])]
        self.service._cached_listing_prices = lambda *_: (None, {})
        self.service._cached_limit_prices = lambda *_: (None, {})
        self.service._cached_country_profile_metrics = lambda *_: {"window": {}, "metrics": {}, "sku": None}

        profile = self.service.get_label_hub_country_profile(
            country_category="RegionA", store="StoreA", msku="A1"
        )

        raw_labels = profile["countries"][0]["raw_labels"]
        self.assertEqual(1, profile["summary"]["country_count"])
        self.assertEqual(4, len(raw_labels))
        self.assertEqual(4, len({
            (item["parent_id"], item["period"], item["id"])
            for item in raw_labels
        }))

    def test_country_profile_reconciles_partial_labels_and_missing_prices(self):
        facts = [
            {**fact, "country": "CountryA", "country_category": "RegionA"}
            for fact in FACTS[:2]
        ]
        self.service._cached_profile_country_facts = lambda *_: facts
        self.service._cached_listing_prices = lambda *_: (None, {})
        self.service._cached_limit_prices = lambda *_: (None, {})
        self.service._cached_country_profile_metrics = lambda *_: {"window": {}, "metrics": {}, "sku": None}

        profile = self.service.get_label_hub_country_profile(
            country_category="RegionA", store="StoreA", msku="A1"
        )

        self.assertEqual(1, profile["summary"]["country_count"])
        self.assertEqual(0, profile["summary"]["complete_label_country_count"])
        self.assertEqual(1, profile["summary"]["missing_price_country_count"])
        self.assertEqual("partial_labels", profile["countries"][0]["data_status"])

    def test_country_profile_invalid_metric_period_falls_back_before_loading_metrics(self):
        captured = []
        self.service._cached_profile_country_facts = lambda *_: FACTS[:4]
        self.service._cached_listing_prices = lambda *_: (None, {})
        self.service._cached_limit_prices = lambda *_: (None, {})
        self.service._cached_country_profile_metrics = lambda *args: captured.append(args) or {
            "window": {}, "metrics": {}, "sku": None
        }

        profile = self.service.get_label_hub_country_profile(
            country_category="RegionA", store="StoreA", msku="A1", metric_period="365d"
        )

        self.assertEqual("30d", profile["scope"]["metric_period"])
        self.assertEqual("30d", captured[0][-1])

    def test_country_profile_keeps_labels_when_optional_sources_fail(self):
        def fail(message):
            raise RuntimeError(message)

        self.service._cached_profile_country_facts = lambda *_: FACTS[:4]
        self.service._cached_listing_prices = lambda *_: fail("price offline")
        self.service._cached_limit_prices = lambda *_: fail("limit offline")
        self.service._cached_country_profile_metrics = lambda *_: fail("metrics offline")

        profile = self.service.get_label_hub_country_profile(
            country_category="RegionA", store="StoreA", msku="A1"
        )

        self.assertEqual("unavailable", profile["scope"]["listing_price_status"])
        self.assertEqual("unavailable", profile["scope"]["limit_price_status"])
        self.assertEqual("unavailable", profile["scope"]["local_metrics_status"])
        self.assertEqual(1, len(profile["countries"]))
        self.assertEqual(4, len(profile["countries"][0]["raw_labels"]))

    def test_country_profile_metric_windows_follow_requested_period(self):
        for period in ("7d", "14d", "90d"):
            with self.subTest(period=period):
                executed = []

                class FakeCursor:
                    def __enter__(self): return self
                    def __exit__(self, *_): return False
                    def execute(self, sql, params): executed.append((sql, dict(params)))
                    def fetchone(self): return {"period_end": date(2026, 7, 15)}
                    def fetchall(self): return []

                class FakeConnection:
                    def __enter__(self): return self
                    def __exit__(self, *_): return False
                    def cursor(self): return FakeCursor()

                service = CountryLabelHubDataService(FakeShared())
                service._shared._dashboard = SimpleNamespace(schemas=None, connect=lambda: FakeConnection())
                with patch("app.services.country_label_hub_data.render_sql", side_effect=lambda table, _: table):
                    result = service._cached_country_profile_metrics(
                        "2026-07-15", "RegionA", "StoreA", "A1", period
                    )

                expected_start = date(2026, 7, 15) - timedelta(days=int(period[:-1]) - 1)
                self.assertEqual(expected_start, executed[1][1]["period_start"])
                self.assertEqual(date(2026, 7, 15), executed[1][1]["period_end"])
                self.assertEqual(period, result["window"]["period_code"])

    def test_country_profile_metrics_return_empty_when_no_period_end_exists(self):
        test_case = self

        class FakeCursor:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, *_): return None
            def fetchone(self): return {"period_end": None}
            def fetchall(self): test_case.fail("detail query must not run without a period end")

        class FakeConnection:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def cursor(self): return FakeCursor()

        self.service._shared._dashboard = SimpleNamespace(schemas=None, connect=lambda: FakeConnection())
        with patch("app.services.country_label_hub_data.render_sql", side_effect=lambda table, _: table):
            result = self.service._cached_country_profile_metrics(
                "2026-07-15", "RegionA", "StoreA", "A1", "30d"
            )

        self.assertEqual({"window": {}, "metrics": {}, "sku": None}, result)

    def test_country_profile_metrics_reuse_cache_for_identical_scope(self):
        connections = []

        class FakeCursor:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, *_): return None
            def fetchone(self): return {"period_end": date(2026, 7, 15)}
            def fetchall(self): return []

        class FakeConnection:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def cursor(self): return FakeCursor()

        def connect():
            connections.append(1)
            return FakeConnection()

        self.service._shared._dashboard = SimpleNamespace(schemas=None, connect=connect)
        with patch("app.services.country_label_hub_data.render_sql", side_effect=lambda table, _: table):
            first = self.service._cached_country_profile_metrics(
                "2026-07-15", "RegionA", "StoreA", "A1", "30d"
            )
            second = self.service._cached_country_profile_metrics(
                "2026-07-15", "RegionA", "StoreA", "A1", "30d"
            )

        self.assertIs(first, second)
        self.assertEqual(1, len(connections))

    def test_country_profile_passes_selected_store_and_msku_to_lazy_sources(self):
        calls = []
        self.service._cached_profile_country_facts = lambda *args: calls.append(("facts", args)) or FACTS[:4]
        self.service._cached_listing_prices = lambda *args: calls.append(("price", args)) or (None, {})
        self.service._cached_limit_prices = lambda *args: calls.append(("limit", args)) or (None, {})
        self.service._cached_country_profile_metrics = lambda *args: calls.append(("metrics", args)) or {
            "window": {}, "metrics": {}, "sku": None
        }

        self.service.get_label_hub_country_profile(
            country_category="RegionA", store="Store-X", msku="MSKU-X", metric_period="14d"
        )

        self.assertEqual(("2026-07-15", "RegionA", "Store-X", "MSKU-X"), calls[0][1])
        self.assertEqual(("RegionA", "Store-X", "MSKU-X"), calls[1][1])
        self.assertEqual(("RegionA", "Store-X", "MSKU-X"), calls[2][1])
        self.assertEqual(("2026-07-15", "RegionA", "Store-X", "MSKU-X", "14d"), calls[3][1])

    def test_country_profile_sorts_by_sales_then_fixed_country_order(self):
        countries = ["荷兰", "德国", "西班牙", "法国"]
        profile_facts = [
            {**fact, "country": country}
            for country in countries
            for fact in FACTS[:4]
        ]
        self.service._cached_profile_country_facts = lambda *_: profile_facts
        self.service._cached_listing_prices = lambda *_: ("2026-07-16", {})
        self.service._cached_limit_prices = lambda *_: ("2026-07-16", {})
        self.service._cached_country_profile_metrics = lambda *_: {
            "window": {},
            "metrics": {
                "荷兰": {"sales_qty": 0},
                "德国": {"sales_qty": 0},
                "西班牙": {"sales_qty": 12},
                "法国": {"sales_qty": 12},
            },
        }

        profile = self.service.get_label_hub_country_profile(
            country_category="北美站", store="StoreA", msku="A1"
        )

        self.assertEqual(
            ["法国", "西班牙", "德国", "荷兰"],
            [item["country"] for item in profile["countries"]],
        )

    def test_country_label_units_use_the_full_four_field_key(self):
        payload = self.service.get_payload(metric_period="30d", page_size=20)

        self.assertNotIn("population_summary", payload)
        self.assertEqual(2, payload["kpis"]["business_unit_count"])
        self.assertEqual(2, payload["kpis"]["country_count"])
        self.assertEqual(2, payload["total"])
        self.assertEqual(4, len(payload["rows"][0]["labels"]))
        self.assertIn("国家销售角色", payload["rows"][0]["label_summary"])

    def test_detail_base_rows_expand_real_sku_metrics_without_copying_business_totals(self):
        self.service._country_detail_metric_provider = lambda **kwargs: {
            "status": "available",
            "window": {"period_code": "30d"},
            "rows": [
                {"country": "美国", "country_category": "北美站", "store": "StoreA", "msku": "A1", "sku": "SKU-A", "sales_amount": 100, "order_gross_profit": 20},
                {"country": "墨西哥", "country_category": "墨西哥站", "store": "StoreA", "msku": "A1", "sku": "SKU-A", "sales_amount": 50, "order_gross_profit": -5},
            ],
        }

        payload = self.service.get_country_detail_base_rows(data_date="2026-07-15", metric_period="30d")

        self.assertEqual("available", payload["metric_status"])
        self.assertEqual([50, 100], sorted(row["sales_amount"] for row in payload["rows"]))
        self.assertEqual({"SKU-A"}, {row["sku"] for row in payload["rows"]})

    def test_detail_base_rows_keep_label_rows_when_country_metrics_fail(self):
        def fail(**kwargs):
            raise RuntimeError("daily source offline")

        self.service._country_detail_metric_provider = fail

        payload = self.service.get_country_detail_base_rows(data_date="2026-07-15", metric_period="30d")

        self.assertEqual("unavailable", payload["metric_status"])
        self.assertEqual(2, len(payload["rows"]))
        self.assertTrue(all(row["data_status"] == "国家经营指标暂不可用" for row in payload["rows"]))

    def test_country_detail_metrics_fall_back_to_existing_yearly_fact(self):
        self.service._cached_country_detail_metrics = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("missing view"))
        self.service._cached_country_detail_raw_metrics = lambda **kwargs: {
            "status": "available", "window": {}, "rows": [{"country": "美国", "sku": "SKU-A"}]
        }

        payload = self.service._country_detail_metrics_with_fallback(data_date="2026-07-15", metric_period="30d")

        self.assertEqual("SKU-A", payload["rows"][0]["sku"])

    def test_country_detail_metrics_return_latest_positive_ranking(self):
        statements = []

        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql, params): statements.append(sql)
            def fetchone(self): return {"period_end": date(2026, 7, 15)}
            def fetchall(self):
                return [{
                    "country": "美国", "country_category": "北美站", "store": "StoreA",
                    "msku": "A1", "sku": "SKU-A", "ranking": 18,
                }]

        class Connection:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def cursor(self): return Cursor()

        self.service._shared._dashboard = SimpleNamespace(
            schemas=SimpleNamespace(),
            connect=lambda: Connection(),
        )
        with patch("app.services.country_label_hub_data.render_sql", return_value="product_daily"):
            payload = self.service._cached_country_detail_metrics(
                data_date="2026-07-15", metric_period="30d",
                country_category="all", store="all", keyword="", identifiers=[],
            )

        self.assertEqual(18, payload["rows"][0]["ranking"])
        metric_sql = statements[-1].lower()
        self.assertIn("ranking > 0", metric_sql)
        self.assertIn("as ranking", metric_sql)

    def test_country_is_part_of_the_unit_key_without_duplicating_local_metrics(self):
        extra = {**FACTS[0], "country": "加拿大"}
        self.service._shared._cached_facts = lambda data_date: FACTS + [extra]

        payload = self.service.get_payload(metric_period="30d", page_size=20)

        self.assertEqual(3, payload["total"])
        self.assertEqual(3, payload["kpis"]["country_count"])
        self.assertEqual(150, payload["kpis"]["sales_amount"])

    def test_inventory_uses_store_and_msku_max_instead_of_country_sum(self):
        payload = self.service.get_payload(metric_period="30d", page_size=20)

        self.assertEqual(50, payload["kpis"]["ending_inventory_qty"])
        self.assertEqual(150, payload["kpis"]["sales_amount"])

    def test_cross_country_difference_and_problem_filters(self):
        payload = self.service.get_payload(metric_period="30d", problem="cross_country_inconsistent", page_size=20)

        self.assertEqual(2, payload["total"])
        self.assertTrue(all(row["cross_country_inconsistent"] for row in payload["rows"]))
        negative = self.service.get_payload(metric_period="30d", problem="negative_profit", page_size=20)
        self.assertEqual(["墨西哥站"], [row["country_category"] for row in negative["rows"]])

    def test_same_parent_or_and_cross_parent_and(self):
        same_parent = self.service.get_payload(metric_period="30d", conditions="13:1301|1304", page_size=20)
        cross_parent = self.service.get_payload(metric_period="30d", conditions="13:1301;7:702", page_size=20)

        self.assertEqual(2, same_parent["total"])
        self.assertEqual(0, cross_parent["total"])

    def test_country_role_distribution_sums_to_business_units(self):
        payload = self.service.get_payload(metric_period="30d", page_size=20)
        role = next(item for item in payload["label_breakdowns"] if item["parent_id"] == 13)

        self.assertEqual(2, sum(item["business_unit_count"] for item in role["buckets"]))
        self.assertEqual(1, payload["issue_counts"]["problem_product"])

    def test_problem_product_is_zero_without_remote_country_role_facts(self):
        self.service._shared._cached_facts = lambda data_date: [fact for fact in FACTS if fact["label_id"] < 1300]

        payload = self.service.get_payload(metric_period="30d", page_size=20)

        self.assertEqual(0, payload["issue_counts"]["problem_product"])

    def test_linkage_filters_reuse_the_cached_country_base_rows(self):
        with patch.object(self.service, "_make_row", wraps=self.service._make_row) as make_row:
            self.service.get_payload(metric_period="30d", page_size=20)
            initial_build_count = make_row.call_count
            self.service.get_payload(metric_period="30d", conditions="7:701", page_size=20)

        self.assertGreater(initial_build_count, 0)
        self.assertEqual(initial_build_count, make_row.call_count)

    def test_all_country_label_pairs_are_available_for_matrix_switching(self):
        payload = self.service.get_payload(metric_period="30d", page_size=20)
        pairs = {
            frozenset((matrix["row_parent_id"], matrix["col_parent_id"]))
            for matrix in payload["matrices"]
        }

        self.assertEqual(6, len(payload["matrices"]))
        self.assertEqual(
            {
                frozenset((4, 7)), frozenset((4, 13)), frozenset((4, 14)),
                frozenset((7, 13)), frozenset((7, 14)), frozenset((13, 14)),
            },
            pairs,
        )


if __name__ == "__main__":
    unittest.main()
