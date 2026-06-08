import unittest

from etl.dashboard_daily_update import (
    INSERT_ALERT_COMPARISON_SNAPSHOT_SQL,
    INSERT_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL,
    INSERT_LIMIT_PRICE_SQL,
    INSERT_LISTING_PRICE_SQL,
    INSERT_PERIOD_SNAPSHOT_SQL,
    INSERT_PRODUCT_DAILY_SQL,
)


class DashboardDailyUpdateSqlTests(unittest.TestCase):
    def test_product_daily_sql_contains_complete_country_rules(self):
        self.assertIn("when country in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'", INSERT_PRODUCT_DAILY_SQL)
        self.assertIn("when country = '英国' then '英国站'", INSERT_PRODUCT_DAILY_SQL)
        self.assertIn("when country = '德国' then coalesce(amount, 0) / 1.19", INSERT_PRODUCT_DAILY_SQL)
        self.assertIn("when country = '土耳其' then coalesce(amount, 0) / 1.20", INSERT_PRODUCT_DAILY_SQL)

    def test_listing_price_sql_contains_complete_marketplace_rules(self):
        self.assertIn("when marketplace in ('美国', '加拿大', '巴西', '墨西哥') then '北美站'", INSERT_LISTING_PRICE_SQL)
        self.assertIn("when marketplace = '英国' then '英国站'", INSERT_LISTING_PRICE_SQL)
        self.assertIn("when marketplace in ('德国', '法国', '荷兰', '比利时', '西班牙', '意大利', '爱尔兰') then '欧元'", INSERT_LISTING_PRICE_SQL)
        self.assertIn("when marketplace = '墨西哥' then '墨西哥比索'", INSERT_LISTING_PRICE_SQL)

    def test_limit_price_sql_uses_pricing_schedule_rows(self):
        self.assertIn("from temporary_dwd.`在库节点_输出定价表`", INSERT_LIMIT_PRICE_SQL)
        self.assertIn("`35毛利润价格` as margin_price_35", INSERT_LIMIT_PRICE_SQL)
        self.assertIn("`35毛利润含广告定价` as margin_price_35_adj", INSERT_LIMIT_PRICE_SQL)
        self.assertIn(
            "round(max(margin_price_35), 2) as tax_inclusive_price,\n"
            "    round(max(margin_price_35), 2) as tax_inclusive_price_noad,\n"
            "    round(max(margin_price_35_adj), 2) as tax_inclusive_price_adj,\n"
            "    round(max(margin_price_35), 2) as margin_price_35,\n"
            "    round(max(margin_price_10), 2) as margin_price_10,",
            INSERT_LIMIT_PRICE_SQL,
        )

    def test_snapshot_label_sql_uses_readable_chinese_labels(self):
        combined_sql = "\n".join(
            [INSERT_ALERT_COMPARISON_SNAPSHOT_SQL, INSERT_ALERT_MONTHLY_METRIC_SNAPSHOT_SQL, INSERT_PERIOD_SNAPSHOT_SQL]
        )
        self.assertIn("'日销 <1'", combined_sql)
        self.assertIn("'毛利率 >35%%'", combined_sql)
        self.assertIn("'销量下滑'", combined_sql)
        for mojibake in ["鏃ラ攢", "姣涘埄", "浣庢瘺", "鎺掑悕", "搴撳瓨"]:
            self.assertNotIn(mojibake, combined_sql)


if __name__ == "__main__":
    unittest.main()
