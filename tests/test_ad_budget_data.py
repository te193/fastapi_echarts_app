from datetime import date

from app.services.ad_budget_data import (
    AdBudgetService,
    apply_anomaly_rules,
    build_overview,
    evaluate_budget_cap,
    filter_budget_countries,
)


def test_budget_cap_accepts_week_month_site_order_and_rejects_excess():
    valid = evaluate_budget_cap(
        {"weekly_ad_budget_cny": 70, "monthly_ad_budget_cny": 300, "site_total_budget_cny": 500}
    )
    invalid = evaluate_budget_cap(
        {"weekly_ad_budget_cny": 320, "monthly_ad_budget_cny": 300, "site_total_budget_cny": 250}
    )
    incomplete = evaluate_budget_cap(
        {"weekly_ad_budget_cny": None, "monthly_ad_budget_cny": 300, "site_total_budget_cny": 500}
    )

    assert valid == {"status": "valid", "label": "在总预算内", "excess_level": "", "excess_amount": 0.0}
    assert invalid == {
        "status": "invalid",
        "label": "预算配置异常",
        "excess_level": "月预算超过站点总预算；周预算超过月预算",
        "excess_amount": 70.0,
    }
    assert incomplete == {"status": "incomplete", "label": "数据不完整", "excess_level": "", "excess_amount": 0.0}


def test_anomaly_rules_prioritize_budget_configuration_and_spend_without_budget():
    rows = [
        {
            "country": "德国",
            "product_type": "老品",
            "seller_name_new": "A",
            "seller_sku_adj": "SKU1",
            "weekly_ad_budget_cny": 350,
            "monthly_ad_budget_cny": 300,
            "site_total_budget_cny": 250,
            "month_spend": 10,
            "spend_7d": 5,
            "performance_row_count": 10,
            "ad_impressions": 0,
            "ad_clicks": 0,
            "ad_orders": 0,
            "ad_sales": 0,
        },
        {
            "country": "美国",
            "product_type": "新品",
            "seller_name_new": "B",
            "seller_sku_adj": "SKU2",
            "weekly_ad_budget_cny": None,
            "monthly_ad_budget_cny": None,
            "site_total_budget_cny": None,
            "month_spend": 120,
            "spend_7d": 80,
            "performance_row_count": 7,
            "ad_impressions": 1000,
            "ad_clicks": 30,
            "ad_orders": 2,
            "ad_sales": 300,
        },
    ]

    result = apply_anomaly_rules(rows, date(2026, 8, 12))

    assert result[0]["anomalies"][0] == "预算配置异常"
    assert result[0]["anomaly_priority"] == 0
    assert "有花费但无月预算" in result[1]["anomalies"]
    assert result[1]["anomaly_priority"] == 1


def test_anomaly_rules_use_country_product_type_quartiles_only_with_enough_samples():
    rows = []
    for index in range(30):
        rows.append(
            {
                "country": "德国",
                "product_type": "老品",
                "seller_name_new": "A",
                "seller_sku_adj": f"SKU{index}",
                "weekly_ad_budget_cny": 100,
                "monthly_ad_budget_cny": 400,
                "site_total_budget_cny": 1000,
                "month_spend": 80,
                "spend_7d": 20,
                "performance_row_count": 12,
                "ad_impressions": 1000,
                "ad_clicks": 20 + index,
                "ad_orders": 1 + index,
                "ad_sales": 100 + index * 10,
            }
        )

    result = apply_anomaly_rules(rows, date(2026, 8, 12))

    assert "低点击" in result[0]["anomalies"]
    assert "低转化" in result[0]["anomalies"]
    assert "高ACOS" in result[0]["anomalies"]
    assert "低点击" not in result[-1]["anomalies"]


def test_peer_quartiles_require_thirty_valid_metric_samples():
    rows = []
    for index in range(29):
        rows.append(
            {
                "country": "德国",
                "product_type": "老品",
                "performance_row_count": 12,
                "month_spend": 80,
                "spend_7d": 20,
                "ad_impressions": 1000,
                "ad_clicks": 20 + index,
                "ad_orders": 1 + index,
                "ad_sales": 100 + index,
            }
        )
    rows.append(
        {
            "country": "德国",
            "product_type": "老品",
            "performance_row_count": None,
            "month_spend": None,
            "ad_impressions": None,
            "ad_clicks": None,
            "ad_orders": None,
            "ad_sales": None,
        }
    )

    result = apply_anomaly_rules(rows, date(2026, 8, 12))

    assert all("低点击" not in row["anomalies"] for row in result)
    assert all("低转化" not in row["anomalies"] for row in result)
    assert all("高ACOS" not in row["anomalies"] for row in result)


def test_overview_deduplicates_market_pool_budget_but_sums_site_budget():
    rows = [
        {
            "country_category": "欧洲站",
            "country": "德国",
            "seller_name_new": "A",
            "seller_sku_adj": "SKU1",
            "total_budget_pool_cny": 1000,
            "site_total_budget_cny": 600,
            "monthly_ad_budget_cny": 300,
            "weekly_ad_budget_cny": 70,
            "month_spend": 120,
            "spend_7d": 25,
        },
        {
            "country_category": "欧洲站",
            "country": "法国",
            "seller_name_new": "A",
            "seller_sku_adj": "SKU1",
            "total_budget_pool_cny": 1000,
            "site_total_budget_cny": 400,
            "monthly_ad_budget_cny": 200,
            "weekly_ad_budget_cny": 50,
            "month_spend": 80,
            "spend_7d": 20,
        },
    ]

    overview = build_overview(rows)

    assert overview["market_pool_budget"] == 1000.0
    assert overview["site_total_budget"] == 1000.0
    assert overview["monthly_budget"] == 500.0
    assert overview["month_spend"] == 200.0
    assert overview["weekly_budget"] == 120.0
    assert overview["spend_7d"] == 45.0


def test_missing_performance_is_not_rendered_as_a_real_zero_rate():
    [row] = apply_anomaly_rules(
        [
            {
                "country": "德国",
                "product_type": "老品",
                "weekly_ad_budget_cny": 70,
                "monthly_ad_budget_cny": 300,
                "site_total_budget_cny": 500,
                "performance_row_count": None,
                "ad_impressions": None,
                "ad_clicks": None,
                "ad_orders": None,
                "ad_sales": None,
                "month_spend": None,
                "spend_7d": None,
            }
        ],
        date(2026, 8, 12),
    )

    assert row["ctr"] is None
    assert row["ad_cvr"] is None


def test_detail_metrics_include_the_seven_day_ad_funnel():
    [row] = apply_anomaly_rules(
        [
            {
                "country": "德国",
                "product_type": "老品",
                "performance_row_count": 12,
                "performance_7d_row_count": 7,
                "ad_impressions": 1000,
                "ad_clicks": 40,
                "ad_orders": 4,
                "ad_sales": 200,
                "month_spend": 80,
                "ad_impressions_7d": 500,
                "ad_clicks_7d": 25,
                "ad_orders_7d": 3,
                "ad_sales_7d": 120,
                "sales_amount_7d": 300,
                "sales_qty_7d": 6,
                "sessions_total_7d": 180,
                "spend_7d": 60,
            }
        ],
        date(2026, 8, 12),
    )

    assert row["ctr_7d"] == 0.05
    assert row["ad_cvr_7d"] == 0.12
    assert row["acos_7d"] == 0.5
    assert row["tacos_7d"] == 0.2
    assert row["ad_sales_share_7d"] == 0.4
    assert row["sales_qty_7d"] == 6
    assert row["sessions_total_7d"] == 180
    assert row["roas_7d"] == 2.0


def test_month_metrics_include_ad_sales_share():
    [row] = apply_anomaly_rules(
        [
            {
                "country": "德国",
                "product_type": "老品",
                "performance_row_count": 3,
                "ad_sales": 120,
                "sales_amount": 300,
            }
        ],
        date(2026, 8, 12),
    )

    assert row["ad_sales_share"] == 0.4


def test_detail_trend_starts_on_first_day_of_performance_month():
    service = AdBudgetService()

    assert service._detail_trend_start(date(2026, 8, 12)) == date(2026, 8, 1)


def test_descending_sort_keeps_missing_values_last(monkeypatch):
    service = AdBudgetService()
    rows = [
        {"seller_sku_adj": "missing", "month_spend": None, "anomalies": []},
        {"seller_sku_adj": "high", "month_spend": 20, "anomalies": []},
        {"seller_sku_adj": "low", "month_spend": 10, "anomalies": []},
    ]
    monkeypatch.setattr(service, "_load_rows", lambda: (rows, date(2026, 8, 11), date(2026, 8, 12)))

    payload = service.get_payload(sort_field="month_spend", sort_dir="desc")

    assert [row["seller_sku_adj"] for row in payload["rows"]] == ["high", "low", "missing"]


def test_default_sort_puts_highest_priority_anomaly_first(monkeypatch):
    service = AdBudgetService()
    rows = [
        {"seller_sku_adj": "normal", "anomaly_priority": 99, "budget_gap_amount": 0, "anomalies": []},
        {"seller_sku_adj": "config", "anomaly_priority": 0, "budget_gap_amount": 5, "anomalies": ["预算配置异常"]},
        {"seller_sku_adj": "overspend", "anomaly_priority": 2, "budget_gap_amount": 100, "anomalies": ["月预算超支"]},
    ]
    monkeypatch.setattr(service, "_load_rows", lambda: (rows, date(2026, 8, 11), date(2026, 8, 12)))

    payload = service.get_payload()

    assert [row["seller_sku_adj"] for row in payload["rows"]] == ["config", "overspend", "normal"]


def test_month_start_scan_includes_the_full_seven_day_window():
    service = AdBudgetService()

    assert service._performance_start(date(2026, 8, 3)) == date(2026, 7, 28)
    assert service._performance_start(date(2026, 8, 12)) == date(2026, 8, 1)


def test_budget_country_scope_keeps_only_configured_seven_countries():
    rows = [
        {"country": country, "seller_sku_adj": country}
        for country in ("德国", "法国", "意大利", "西班牙", "荷兰", "美国", "英国", "比利时", "瑞典", "加拿大")
    ]

    scoped = filter_budget_countries(rows)

    assert [row["country"] for row in scoped] == ["德国", "法国", "意大利", "西班牙", "荷兰", "美国", "英国"]


def test_tacos_uses_month_ad_spend_over_product_sales_amount():
    rows = apply_anomaly_rules(
        [
            {
                "country": "德国",
                "product_type": "老品",
                "performance_row_count": 12,
                "month_spend": 80,
                "ad_sales": 200,
                "sales_amount": 400,
            },
            {
                "country": "法国",
                "product_type": "老品",
                "performance_row_count": 12,
                "month_spend": 20,
                "ad_sales": 50,
                "sales_amount": 0,
            },
        ],
        date(2026, 8, 12),
    )

    assert rows[0]["acos"] == 0.4
    assert rows[0]["tacos"] == 0.2
    assert rows[1]["tacos"] is None
