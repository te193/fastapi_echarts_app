import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main


class FakeReturnGoodsService:
    def __init__(self):
        self.calls = []

    def get_payload(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "kwargs": kwargs}

    def get_detail(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "kwargs": kwargs}

    def get_stage_detail(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "kwargs": kwargs}


class ReturnGoodsApiTests(unittest.TestCase):
    def test_api_return_goods_passes_query_params_to_service(self):
        service = FakeReturnGoodsService()

        with patch("app.main.return_goods_service", service):
            payload = main.api_return_goods(
                snapshot_date="2026-06-30",
                period_days=7,
                country_category="北美站",
                seller_name_new="店铺A",
                keyword="MSKU1",
                stage="运营干预期",
                warning_type="干预期未恢复",
                quick_filter="receiving",
                inventory_status_filter="post_stockout_inbound",
                page=2,
                page_size=30,
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(
            {
                "snapshot_date": "2026-06-30",
                "period_days": 7,
                "country_category": "北美站",
                "seller_name_new": "店铺A",
                "keyword": "MSKU1",
                "stage": "运营干预期",
                "warning_type": "干预期未恢复",
                "quick_filter": "receiving",
                "inventory_status_filter": "post_stockout_inbound",
                "page": 2,
                "page_size": 30,
            },
            service.calls[0],
        )

    def test_api_return_goods_detail_passes_query_params_to_service(self):
        service = FakeReturnGoodsService()

        with patch("app.main.return_goods_service", service):
            payload = main.api_return_goods_detail(
                snapshot_date="2026-06-30",
                return_event_id="event-1",
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(
            {
                "snapshot_date": "2026-06-30",
                "return_event_id": "event-1",
            },
            service.calls[0],
        )

    def test_api_return_goods_passes_return_day_when_present(self):
        service = FakeReturnGoodsService()

        with patch("app.main.return_goods_service", service):
            main.api_return_goods(return_day=6)

        self.assertEqual(6, service.calls[0]["return_day"])

    def test_api_return_goods_stage_detail_passes_query_params_to_service(self):
        service = FakeReturnGoodsService()

        with patch("app.main.return_goods_service", service):
            payload = main.api_return_goods_stage_detail(
                snapshot_date="2026-06-30",
                period_days=7,
                country_category="欧洲站",
                seller_name_new="店铺A",
                keyword="MSKU1",
                stage_key="operating",
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(
            {
                "snapshot_date": "2026-06-30",
                "period_days": 7,
                "country_category": "欧洲站",
                "seller_name_new": "店铺A",
                "keyword": "MSKU1",
                "stage_key": "operating",
            },
            service.calls[0],
        )


if __name__ == "__main__":
    unittest.main()
