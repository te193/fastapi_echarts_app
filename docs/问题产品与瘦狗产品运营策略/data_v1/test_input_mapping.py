import unittest

from extract_inputs import build_base


def tag(store="A", role=1304):
    return dict(data_date="2026-09-20", country="德国", store=store, msku="sku1", label_id=role)


def price(store="A-DE", base="A"):
    return {"国家": "德国", "店铺名": store, "新店铺": base, "msku": "sku1"}


class MappingTest(unittest.TestCase):
    def test_explicit_alias_keeps_same_sku_in_different_stores_separate(self):
        prices = [price(), price("B-DE", "B")]
        rows, _ = build_base([tag(), tag("B")], {"pricing": prices, "cost": prices})
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["cost_input"]["店铺名"] for row in rows], ["A-DE", "B-DE"])
        self.assertTrue(all(row["pricing_match_count"] == 1 for row in rows))

    def test_ambiguous_alias_does_not_choose_arbitrary_store(self):
        prices = [price(), price(base="B")]
        rows, _ = build_base([tag()], {"pricing": prices, "cost": [price()]})
        self.assertIsNone(rows[0]["cost_input"])
        self.assertIsNone(rows[0]["pricing_input"])

    def test_duplicate_prices_and_role_overlap_remain_diagnostic(self):
        rows, _ = build_base([tag(), tag(role=1303)], {"pricing": [price(), price()], "cost": []})
        self.assertEqual(len(rows), 1)
        self.assertIn("role_conflict", rows[0]["diagnostics"])
        self.assertIn("pricing_ambiguous_mapped_key", rows[0]["diagnostics"])
        self.assertIsNone(rows[0]["pricing_input"])


if __name__ == "__main__":
    unittest.main()
