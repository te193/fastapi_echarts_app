from datetime import date
from unittest.mock import patch

from app import main
from app.services.price_review_data import PriceReviewService, _build_station_role_evidence


def test_price_review_service_exposes_station_role_detail_drilldown():
    assert hasattr(PriceReviewService, "get_role_migration_detail")


def test_dog_role_evidence_uses_business_copy_instead_of_internal_code():
    evidence = _build_station_role_evidence("dog", "瘦狗产品", 0.13, 0.149, 458)

    assert evidence["items"][1]["actual"] == "未命中明星/潜力组合"


class FixtureDetailService(PriceReviewService):
    def _load_role_migration_rows(self, adjust_date, pre_days, post_days):
        return [{
            "adjust_date": adjust_date,
            "pre_period_days": pre_days,
            "post_period_days": post_days,
            "pre_period_start": date(2026, 8, 5),
            "pre_period_end": date(2026, 8, 7),
            "post_period_start": date(2026, 8, 8),
            "post_period_end": date(2026, 8, 10),
            "country": "西班牙",
            "station_store": "JkangMei",
            "store": "JkangMei-ES",
            "msku": "JKM-001a",
            "local_sku": "HE0190a",
            "product_name": "便携折叠收纳箱 30L",
            "currency": "EUR",
            "price_before": 11.99,
            "price_after": 8.99,
            "drop_ratio": -0.2502,
            "pre_daily_sales": 2.0,
            "post_daily_sales": 0.0,
            "pre_margin_rate": 0.30,
            "post_margin_rate": None,
            "pre_small_rank": 45,
            "post_small_rank": 1892,
            "pre_small_rank_date": date(2026, 8, 6),
            "post_small_rank_date": date(2026, 8, 10),
            "role_before_code": "star",
            "role_before_label": "明星产品",
            "role_after_code": "problem",
            "role_after_label": "问题产品",
            "role_change": "down",
            "data_status": "complete",
            "finance_snapshot_date": date(2026, 8, 7),
            "finance_band_before_code": "20_25",
            "finance_band_before_label": "20–25%",
            "finance_band_after_code": "20_25",
            "finance_band_after_label": "20–25%",
            "finance_change": "stable",
            "station_sales_role_rule_version": "station_sales_role_v47_local",
        }]

    def _load_role_detail_daily_rows(self, **_kwargs):
        return [
            {"dt_date": date(2026, 8, 4), "sales_qty": 2, "revenue": 20, "order_profit": 6, "small_rank": 50},
            {"dt_date": date(2026, 8, 5), "sales_qty": 3, "revenue": 30, "order_profit": 9, "small_rank": 47},
            {"dt_date": date(2026, 8, 6), "sales_qty": 1, "revenue": 10, "order_profit": 3, "small_rank": 45},
            {"dt_date": date(2026, 8, 7), "sales_qty": 1, "revenue": 9, "order_profit": 2, "small_rank": 88},
            {"dt_date": date(2026, 8, 8), "sales_qty": 0, "revenue": 0, "order_profit": 0, "small_rank": 900},
            {"dt_date": date(2026, 8, 9), "sales_qty": 0, "revenue": 0, "order_profit": 0, "small_rank": 1200},
            {"dt_date": date(2026, 8, 10), "sales_qty": 0, "revenue": 0, "order_profit": 0, "small_rank": 1892},
        ]

    def _load_role_detail_finance_ladder(self, _row):
        return {0: 7.0, 5: 7.5, 10: 8.0, 15: 8.5, 20: 9.0, 25: 10.0, 30: 11.0, 35: 12.0}


def test_role_migration_detail_returns_checkpoints_evidence_finance_and_daily_trend():
    payload = FixtureDetailService().get_role_migration_detail(
        adjust_date=date(2026, 8, 7),
        pre_days=3,
        post_days=3,
        country="西班牙",
        store="JkangMei",
        msku="JKM-001a",
    )

    assert payload["identity"]["msku"] == "JKM-001a"
    assert payload["checkpoints"]["before"]["daily_sales"] == 2.0
    assert payload["checkpoints"]["before"]["small_rank"] == 45
    assert payload["checkpoints"]["adjustment"]["small_rank"] == 88
    assert payload["checkpoints"]["after"]["daily_sales"] == 0.0
    assert payload["checkpoints"]["after"]["small_rank"] == 1892
    assert payload["role_evidence"]["before"]["role_code"] == "star"
    assert payload["role_evidence"]["before"]["qualified"] is True
    assert payload["role_evidence"]["after"]["role_code"] == "problem"
    assert payload["role_evidence"]["after"]["qualified"] is True
    assert payload["finance"]["price_before"] == 11.99
    assert payload["finance"]["price_after"] == 8.99
    assert payload["finance"]["ladder"][4] == {"margin": 20, "price": 9.0}
    assert [point["relative_day"] for point in payload["trend"]] == ["D-2", "D-1", "D", "D+1", "D+2", "D+3"]
    assert payload["trend"][2]["period"] == "before"
    assert payload["trend"][2]["small_rank"] == 88


class FakeDetailApiService:
    def __init__(self):
        self.calls = []

    def get_role_migration_detail(self, **kwargs):
        self.calls.append(kwargs)
        return {"identity": {"msku": kwargs["msku"]}}


def test_role_migration_detail_api_passes_exact_station_identity():
    service = FakeDetailApiService()
    with patch("app.main.price_review_service", service):
        payload = main.api_price_review_role_migration_detail(
            adjust_date="2026-08-07",
            pre_days=30,
            post_days=3,
            country="西班牙",
            store="JkangMei",
            msku="JKM-001a",
        )

    assert payload["identity"]["msku"] == "JKM-001a"
    assert service.calls == [{
        "adjust_date": date(2026, 8, 7),
        "pre_days": 30,
        "post_days": 3,
        "country": "西班牙",
        "store": "JkangMei",
        "msku": "JKM-001a",
    }]
