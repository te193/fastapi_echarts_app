import unittest

from app.services.label_hub_diagnostics import build_diagnostic_payload


class LabelHubDiagnosticsTests(unittest.TestCase):
    def test_country_diagnostics_deduplicate_business_metrics_but_keep_country_records(self):
        rows = [
            {
                "country_category": "欧洲站",
                "store": "StoreA",
                "msku": "A1",
                "sales_amount": 100,
                "order_gross_profit": 20,
            }
        ]
        facts = [
            {
                "country_category": "欧洲站",
                "country": "德国",
                "store": "StoreA",
                "msku": "A1",
                "label_id": 1604,
                "label_period": "30d",
                "sub_label_name": "潜力产品(站点)-排名不足",
                "evidence": {"metrics": {"small_rank": 88}, "matched_rule": {"small_rank": "> 50"}},
            },
            {
                "country_category": "欧洲站",
                "country": "法国",
                "store": "StoreA",
                "msku": "A1",
                "label_id": 1604,
                "label_period": "30d",
                "sub_label_name": "潜力产品(站点)-排名不足",
                "evidence": {"metrics": {"small_rank": 92}, "matched_rule": {"small_rank": "> 50"}},
            },
            {
                "country_category": "欧洲站",
                "country": "意大利",
                "store": "StoreA",
                "msku": "A1",
                "label_id": 1601,
                "label_period": "30d",
                "sub_label_name": "已达到站点明星产品标准",
                "evidence": {"matched_rule": {"role": "star"}},
            },
        ]

        payload = build_diagnostic_payload(
            rows=rows,
            facts=facts,
            previous_facts=[],
            scope="country",
            period="30d",
        )

        bucket = next(item for item in payload["buckets"] if item["child_id"] == 1604)
        self.assertEqual(2, bucket["country_record_count"])
        self.assertEqual(1, bucket["business_unit_count"])
        self.assertEqual(2, bucket["country_count"])
        self.assertEqual(100, bucket["sales_amount"])
        self.assertEqual(20, bucket["order_gross_profit"])
        self.assertEqual(2, bucket["delta"])

        distribution = {item["role_id"]: item for item in payload["country_role_distribution"]}
        self.assertEqual(1, payload["business_unit_count"])
        self.assertEqual(3, payload["country_record_count"])
        self.assertEqual(2, distribution["potential"]["country_record_count"])
        self.assertEqual(1, distribution["potential"]["business_unit_count"])
        self.assertEqual(2 / 3, distribution["potential"]["ratio"])
        self.assertEqual(2, distribution["potential"]["delta"])
        self.assertEqual([1604], [item["child_id"] for item in distribution["potential"]["children"]])
        self.assertEqual(1, distribution["star"]["country_record_count"])
        self.assertEqual(0, distribution["dog"]["country_record_count"])
