import csv
import io
import unittest

from app.services.label_hub_export import LabelHubExportService


class FakeDetailService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_export_rows(self, **filters):
        self.calls.append(filters)
        return self.payload


class LabelHubExportTests(unittest.TestCase):
    def test_business_export_has_chinese_columns_bom_and_only_available_inventory(self):
        detail_service = FakeDetailService({
            "rows": [{
                "country_category": "欧洲站",
                "store": "店铺,A",
                "msku": 'M"1',
                "country_count": 3,
                "countries": "德国,法国,意大利",
                "current_label": "明星产品",
                "sales_role": "明星产品",
                "role_diagnostic_summary": "高毛利",
                "label_summary": "销售角色：明星产品",
                "labels": [{"label": "明星产品"}],
                "issue_codes": ["conflict"],
                "issue_labels": ["标签冲突"],
                "sales_trend": "明显增长",
                "sales_trend_ratio": 0.25,
                "daily_sales": 2,
                "sales_qty": 60,
                "sales_amount": 100,
                "order_gross_profit": 20,
                "order_gross_margin": 0.2,
                "ending_inventory_qty": 18,
                "avg_inventory_qty": 12,
                "conflict": True,
                "metric_present": True,
                "data_status": "本地指标可用",
            }],
            "total": 1,
        })
        service = LabelHubExportService(detail_service)

        filename, chunks = service.build_export(
            detail_view="business_unit",
            data_date="2026-08-13",
            metric_period="30d",
            page=2,
            page_size=20,
        )
        text = "".join(chunks)
        parsed = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))

        self.assertEqual("标签看板-MSKU维度-2026-08-13.csv", filename)
        self.assertTrue(text.startswith("\ufeff"))
        self.assertEqual("18", parsed[0]["可售库存"])
        self.assertNotIn("平均可售库存", parsed[0])
        self.assertNotIn("最高可售库存", parsed[0])
        self.assertNotIn("库存覆盖天数", parsed[0])
        self.assertEqual("店铺,A", parsed[0]["店铺"])
        self.assertEqual('M"1', parsed[0]["MSKU"])
        self.assertEqual("是", parsed[0]["是否标签冲突"])
        self.assertEqual("25.00%", parsed[0]["动销趋势变化率"])
        self.assertEqual(2, detail_service.calls[0]["page"])

    def test_country_export_adds_country_sku_ranking_and_keeps_header_when_empty(self):
        service = LabelHubExportService(FakeDetailService({"rows": [], "total": 0}))

        _, chunks = service.build_export(
            detail_view="country",
            data_date="2026-08-13",
            metric_period="7d",
        )
        header = next(csv.reader(io.StringIO("".join(chunks).lstrip("\ufeff"))))

        self.assertEqual(
            ["数据日期", "经营周期", "明细维度", "国家", "国家类别", "店铺", "MSKU", "SKU"],
            header[:8],
        )
        self.assertIn("排名", header)
        self.assertIn("可售库存", header)
        self.assertEqual(1, header.count("可售库存"))
        self.assertIn("7天销量", header)
        self.assertIn("7天销售额", header)


if __name__ == "__main__":
    unittest.main()
