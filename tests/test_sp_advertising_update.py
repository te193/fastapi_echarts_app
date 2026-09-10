from datetime import date, datetime
from decimal import Decimal
import importlib

import pytest


def api():
    try:
        return importlib.import_module('etl.sp_advertising_update')
    except ModuleNotFoundError:
        pytest.fail('SP advertising ETL has not been implemented')


def fact(**extra):
    return dict(id=100, relate_id=10, report_date='2026-09-01', profile_id=1,
                campaign_id=2, ad_group_id=3, keyword_id=4, match_type='exact',
                keyword_text='Door Hook', impressions=100, clicks=10,
                cost=Decimal('3.10'), create_time=datetime(2026, 9, 2), **extra)


def test_multi_product_association_does_not_duplicate_keyword_metrics():
    m = api()
    dims = m.Dimensions()
    dims.add('account', dict(id=1, profile_id='1', sid='11', country_code='DE', currency_code='EUR'))
    dims.add('campaign', dict(id=1, profile_id=1, campaign_id=2, targeting_type='manual'))
    dims.add('ad_group', dict(id=1, profile_id=1, campaign_id=2, ad_group_id=3))
    dims.add('product', dict(id=1, profile_id=1, campaign_id=2, ad_group_id=3, ad_id=5, sku='A'))
    dims.add('product', dict(id=2, profile_id=1, campaign_id=2, ad_group_id=3, ad_id=6, sku='B'))
    dims.finish()
    result = m.prepare_fact('keyword', fact(), dims)
    assert result['cost'] == Decimal('3.10')
    assert result['msku'] is None
    assert result['associated_msku_count'] == 2
    assert result['currency_code'] == 'EUR'


def test_missing_keys_keep_separate_source_records():
    m = api()
    dims = m.Dimensions()
    dims.finish()
    a = fact()
    a['profile_id'] = None
    b = dict(a, id=101)
    first = m.prepare_fact('keyword', a, dims)
    second = m.prepare_fact('keyword', b, dims)
    assert first['row_key'] != second['row_key']
    assert first['missing_business_key'] == 1
    assert first['cost'] == Decimal('3.10')


def test_missing_account_uses_store_suffix_for_safe_site_and_currency_fallback():
    m = api()
    dims = m.Dimensions()
    dims.finish()
    source = fact(seller_name='MyiTong-IT', sku='MT001a')
    source['profile_id'] = None

    result = m.prepare_fact('product_ad', source, dims)

    assert result['seller_name'] == 'MyiTong-IT'
    assert result['country_code'] == 'IT'
    assert result['currency_code'] == 'EUR'
    assert result['missing_account_dimension'] == 1


def test_all_fact_sources_read_ods_reports_directly_without_relate_id_join():
    m = api()

    for kind, (_, source_table, _) in m.FACTS.items():
        sql = m._source_sql(kind, source_table).lower()
        assert f"from ods_datasync.{source_table}" in sql
        assert "dwd_datasync" not in sql
        assert " join " not in sql
        assert "delete_flag" in sql
        assert "_source_ods_id" in sql


def test_direct_ods_source_keeps_source_provenance():
    m = api()
    dims = m.Dimensions()
    dims.finish()

    result = m.prepare_fact(
        'keyword',
        fact(_source_ods_id=10, _source_dwd_id=None),
        dims,
    )

    assert result['source_ods_id'] == 10
    assert result['source_dwd_id'] is None


def test_fact_schema_allows_ods_rows_without_dwd_source_id():
    ddl = api()._ddl('dashboard_sp_keyword_daily').lower()

    assert 'source_dwd_id bigint null' in ddl


def test_exact_search_term_identity_and_different_ad_groups_are_preserved():
    m = api()
    dims = m.Dimensions()
    dims.finish()
    a = fact(target_id=7, query='Hook')
    b = dict(a, query='hook')
    c = dict(a, ad_group_id=8)
    keys = [m.prepare_fact('search_term', x, dims)['row_key'] for x in (a,b,c)]
    assert len(set(keys)) == 3


def test_multiple_expressions_and_archived_objects_are_retained():
    m = api()
    dims = m.Dimensions()
    for n, value in enumerate(('price', 'category')):
        dims.add('target', dict(id=n+1, profile_id=1, campaign_id=2, ad_group_id=3,
                 target_id=9, expression_ordinal=n, expression_item_type=value,
                 expression_item_value='10', state='archived', delete_flag=1))
    dims.finish()
    r = m.prepare_fact('search_term', fact(target_id=9, query='test'), dims)
    import json
    assert len(json.loads(r['target_expressions'])) == 2
    assert r['object_state_current'] == 'archived'


def test_latest_dimension_and_all_attribution_windows():
    m = api()
    dims = m.Dimensions()
    dims.add('campaign', dict(id=2, profile_id=1, campaign_id=2, name='new', update_time=datetime(2026,9,2)))
    dims.add('campaign', dict(id=1, profile_id=1, campaign_id=2, name='old', update_time=datetime(2026,9,1)))
    dims.finish()
    r = m.prepare_fact('keyword', fact(orders_1d=1, orders_7d=2, orders_14d=3, orders_30d=4), dims)
    assert r['campaign_name_current'] == 'new'
    assert [r[f'orders_{d}d'] for d in (1,7,14,30)] == [1,2,3,4]
    assert r['sales_7d'] is None


def test_aggregated_rates_null_denominators_and_distinct_windows():
    m = api()
    r = m.calculate_rates(dict(impressions=100, clicks=10, cost=Decimal('5'),
         orders_1d=1, orders_7d=2, orders_14d=3, orders_30d=4,
         sales_1d=10, sales_7d=20, sales_14d=30, sales_30d=40))
    assert r['ctr'] == Decimal('0.1')
    assert r['cpc'] == Decimal('0.5')
    assert r['acos_7d'] == Decimal('0.25')
    assert r['roas_30d'] == Decimal('8')
    assert r['cvr_14d'] == Decimal('0.3')
    assert m.calculate_rates(dict(clicks=0, impressions=0, cost=0))['cpc'] is None


def test_invalid_range_rejected_and_default_excludes_today():
    m = api()
    assert m.date_range(None, None, date(2026,9,7)) == (date(2026,8,8), date(2026,9,6))
    with pytest.raises(ValueError):
        m.date_range('2026-09-07', '2026-09-01')
