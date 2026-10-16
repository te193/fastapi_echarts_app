from datetime import date, datetime
from decimal import Decimal

import pytest

from return_goods_data.remote_sources import (
    as_date, calculate, evaluation_days, inventory_days, performance_days, read_ads,
)
from return_goods_data.rules import build_events


def test_missing_inventory_is_not_zero_and_multiple_captures_are_not_added():
    warnings = []
    raw = [dict(country_category='欧洲站', create_time=datetime(2026, 10, 1, hour),
                afn_fulfillable_quantity=stock) for hour, stock in [(1, 0), (2, 8)]]
    assert inventory_days(raw, warnings)['欧洲站'][0]['stock'] is None
    assert warnings
    assert build_events([dict(day=date(2026, 10, d), stock=s)
                         for d, s in [(1, 0), (2, 0), (4, 5)]]) == []


def test_single_capture_adds_warehouses_and_threshold_is_five():
    raw = [dict(country_category='欧洲站', create_time=datetime(2026, 10, 4),
                afn_fulfillable_quantity=s) for s in (2, 3)]
    restored = inventory_days(raw, [])['欧洲站'][0]
    days = [dict(day=date(2026, 10, d), stock=0) for d in (1, 2, 3)] + [restored]
    assert build_events(days)[0]['return_date'] == date(2026, 10, 4)


def performance_row(**changes):
    row = dict(id=1, create_time='2026-10-05 01:00:00', start_date='2026-10-04',
               end_date='2026-10-04', seller_name='Store-DE', seller_sku='sku',
               country='德国', asin='asin', local_sku='local', currency_icon='EUR',
               volume=1, amount=10, predict_gross_profit=2, sessions_total=20, spend=1)
    row.update(changes)
    return row


def test_performance_uses_latest_revision_and_order_profit_not_settlement():
    raw = [performance_row(), performance_row(id=2, volume=2, predict_gross_profit=3),
           performance_row(id=3, end_date='2026-10-05', volume=100)]
    item = performance_days(raw, [])['欧洲站'][0]
    assert item['qty'] == 2
    assert item['profit'] == 3
    assert item['day'] == date(2026, 10, 4)


def test_null_sales_remains_missing_and_mixed_currencies_do_not_form_margin():
    rows = performance_days([performance_row(volume=None),
        performance_row(id=2, country='法国', seller_name='Store-FR', currency_icon='USD')], [])['欧洲站']
    for row in rows:
        row['stock'] = Decimal(5)
    combined = evaluation_days(rows)[0]
    assert combined['qty'] is None
    assert combined['profit'] is None
    assert combined['revenue'] is None
    assert combined['stock'] == 5


def test_future_settings_rejected_before_database_connection():
    with pytest.raises(ValueError, match='未来'):
        calculate('store', 'sku', date(2026, 10, 8), date(2026, 10, 9))
    assert as_date(datetime(2026, 10, 8, 23)) == date(2026, 10, 8)


def test_missing_ad_snapshot_is_not_claimed_as_no_ads(monkeypatch):
    monkeypatch.setattr('return_goods_data.remote_sources.read_rows', lambda *args: [{'day': None}])
    with pytest.raises(RuntimeError, match='没有广告对象快照'):
        read_ads(None, 'store', 'sku', date(2026, 10, 8), date(2026, 10, 8), [])


def test_empty_product_ads_only_after_successful_scoped_read(monkeypatch):
    calls = []
    def read(conn, sql, params):
        calls.append((sql, params))
        return [{'day': date(2026, 10, 8)}] if len(calls) == 1 else []
    monkeypatch.setattr('return_goods_data.remote_sources.read_rows', read)
    result = read_ads(None, 'store', 'sku', date(2026, 10, 8), date(2026, 10, 8), [])
    assert result['objects'] == []
    assert calls[1][1] == (date(2026, 10, 8), 'store', 'sku')
    assert 'base_store_name=%s and msku=%s' in calls[1][0]
