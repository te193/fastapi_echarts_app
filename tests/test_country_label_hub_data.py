import unittest
from unittest.mock import patch

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

    def test_country_label_units_use_the_full_four_field_key(self):
        payload = self.service.get_payload(metric_period="30d", page_size=20)

        self.assertNotIn("population_summary", payload)
        self.assertEqual(2, payload["kpis"]["business_unit_count"])
        self.assertEqual(2, payload["kpis"]["country_count"])
        self.assertEqual(2, payload["total"])
        self.assertEqual(4, len(payload["rows"][0]["labels"]))
        self.assertIn("国家销售角色", payload["rows"][0]["label_summary"])

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
