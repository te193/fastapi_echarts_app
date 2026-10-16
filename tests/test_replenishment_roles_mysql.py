"""Role joins against mixed collations in disposable MySQL schemas only."""
from datetime import date
from decimal import Decimal
import re

import pytest

from test_label_local_store_mysql import local_store
from app.services.replenishment_tracking_summary_data import ReplenishmentTrackingSummaryService
from etl import replenishment_roles as roles
from etl import replenishment_tracking_summary_update as summary_update


DAY = date(2026, 10, 13)
CASES = [
    (7, 42, 20, "明星产品"),
    (14, 28, 12, "潜力产品"),
    (30, 60, 4, "瘦狗产品"),
    (90, 0, None, "问题产品"),
]


@pytest.fixture
def mixed_role_store(local_store):
    conn, schema = local_store
    assert re.fullmatch(r"label_validation_[0-9a-f]{12}", schema)
    conn.select_db(schema)
    with conn.cursor() as cursor:
        cursor.execute("select database() as active_schema")
        assert cursor.fetchone()["active_schema"] == schema
        cursor.execute("""
            create table dashboard_pur_plan_replenish_data (
                cur_date date, country_category varchar(64), seller_name_new varchar(128),
                seller_sku_adj varchar(128), max_sku varchar(128),
                support_replenish_level varchar(32), support_replenish_level_sort int,
                daily_avg_sales decimal(18,4)
            ) default charset=utf8mb4 collate=utf8mb4_unicode_ci
        """)
        cursor.execute(summary_update.CREATE_SUMMARY_SQL)
        cursor.execute("""
            create table dashboard_replenishment_country_metrics (
                snapshot_date date, period_days int, country_category varchar(64),
                country varchar(64), seller_name_new varchar(128), seller_sku_adj varchar(128),
                sales_qty decimal(18,4), sales_amount decimal(18,4),
                order_gross_profit decimal(18,4)
            ) default charset=utf8mb4 collate=utf8mb4_0900_ai_ci
        """)
        for sku in ("sku", "no-evidence"):
            cursor.execute("""
                insert into dashboard_pur_plan_replenish_data
                values (%s,'欧洲站','shop',%s,%s,'level1',1,99)
            """, (DAY, sku, sku))
            cursor.execute("""
                insert into dashboard_replenishment_tracking_summary
                    (cutoff_date,country_category,seller_name_new,seller_sku_adj,
                     first_replenishment_date,latest_replenishment_date)
                values (%s,'欧洲站','shop',%s,%s,%s)
            """, (DAY, sku, DAY, DAY))
        for period, qty, profit, _ in CASES:
            for country in ("德国", "法国"):
                cursor.execute("""
                    insert into dashboard_replenishment_country_metrics
                    values (%s,%s,'欧洲站',%s,'SHOP','SKU',%s,50,%s)
                """, (DAY, period, country, Decimal(qty) / 2,
                      None if profit is None else Decimal(profit) / 2))
            for category, store, sku, snapshot in [
                ("北美站", "shop", "sku", DAY),
                ("欧洲站", "other", "sku", DAY),
                ("欧洲站", "shop", "other-sku", DAY),
                ("欧洲站", "shop", "sku", date(2026, 10, 12)),
            ]:
                cursor.execute("""
                    insert into dashboard_replenishment_country_metrics
                    values (%s,%s,%s,'德国',%s,%s,9000,100,90)
                """, (snapshot, period, category, store, sku))
    conn.commit()
    return conn


@pytest.mark.parametrize("period,qty,profit,want", CASES)
def test_tracking_summary_role_filter_accepts_mixed_collations(
    mixed_role_store, period, qty, profit, want
):
    service = ReplenishmentTrackingSummaryService.__new__(ReplenishmentTrackingSummaryService)
    result = service._summary(
        mixed_role_store, "current_role_category = %(expected_role)s",
        {"cutoff_date": DAY, "role_period_days": period, "expected_role": want},
    )
    assert result["msku_count"] == 1
    with mixed_role_store.cursor() as cursor:
        cursor.execute(
            f"select seller_sku_adj,current_role_category "
            f"from {roles.tracking_summary_source_sql(period)} s",
            {"cutoff_date": DAY},
        )
        rows = {row["seller_sku_adj"]: row["current_role_category"] for row in cursor.fetchall()}
    assert rows == {"sku": want, "no-evidence": None}


@pytest.mark.parametrize("period,qty,profit,want", CASES)
def test_replenishment_role_join_preserves_own_metrics_with_mixed_collations(
    mixed_role_store, period, qty, profit, want
):
    with mixed_role_store.cursor() as cursor:
        cursor.execute(
            f"select seller_sku_adj,role_daily_sales_{period}d as daily,"
            f"role_margin_rate_{period}d as margin,daily_avg_sales "
            f"from {roles.replenishment_source_sql(period, ('snapshot_date',))} r",
            {"snapshot_date": DAY},
        )
        rows = {row["seller_sku_adj"]: row for row in cursor.fetchall()}
    assert rows["sku"]["daily"] == Decimal(qty) / period
    assert rows["sku"]["margin"] == (None if profit is None else Decimal(profit) / 100)
    assert rows["sku"]["daily_avg_sales"] == 99
    assert rows["no-evidence"]["daily"] is None
    assert rows["no-evidence"]["margin"] is None


def test_summary_etl_role_ctes_accept_mixed_collations_without_running_etl(mixed_role_store):
    sql = summary_update.INSERT_SUMMARY_SQL
    # Execute the production role CTEs as a SELECT, without its INSERT or later ETL.
    start = sql.index("with base as (")
    end = sql.index(",\npurchase_plan_doc as (", start)
    expressions = [
        f"{getattr(summary_update, f'PRODUCT_CATEGORY_{period}D_SQL')} as role_{period}d"
        for period in (7, 14, 30, 90)
    ]
    query = sql[start:end] + "\nselect l.seller_sku_adj," + ",".join(expressions) + " from latest_row l"
    with mixed_role_store.cursor() as cursor:
        cursor.execute(query, {"cutoff_date": DAY})
        rows = {row["seller_sku_adj"]: row for row in cursor.fetchall()}
    assert rows["sku"] == {
        "seller_sku_adj": "sku", "role_7d": "明星产品", "role_14d": "潜力产品",
        "role_30d": "瘦狗产品", "role_90d": "问题产品",
    }
    assert all(rows["no-evidence"][f"role_{period}d"] is None for period in (7, 14, 30, 90))
