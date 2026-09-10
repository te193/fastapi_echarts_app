import importlib
from decimal import Decimal

import pytest


def api():
    try:
        return importlib.import_module('app.services.ad_performance_data')
    except ModuleNotFoundError:
        pytest.fail('Advertising performance service is missing')


def test_filter_validation_rejects_injected_identifiers():
    m = api()
    for params in ({'view': 'campaign;drop'}, {'window': '8'}, {'sort': 'cost desc;'},
                   {'start': '2026-09-07', 'end': '2026-09-01'}):
        with pytest.raises(ValueError):
            m.Filters(params)


def test_large_ids_nulls_and_decimal_values_are_serialized():
    m = api()
    row = m.serialize({'profile_id': 9007199254740999, 'cost': Decimal('1.20'), 'sales': None})
    assert row == {'profile_id': '9007199254740999', 'cost': 1.2, 'sales': None}


def test_csv_cells_prevent_formulas_and_preserve_identifiers():
    m = api()
    assert m.csv_cell('msku', '=CMD()') == "'=CMD()"
    assert m.csv_cell('profile_id', 9007199254740999) == "'9007199254740999"
    assert m.csv_cell('cost', Decimal('2.50')) == Decimal('2.50')


def test_aggregate_rates_preserve_zero_denominators():
    m = api()
    row = m.with_rates({'impressions': 100, 'clicks': 10, 'cost': Decimal('5'), 'sales': 20, 'orders': 2})
    assert row['ctr'] == Decimal('0.1')
    assert row['acos'] == Decimal('0.25')
    assert row['cvr'] == Decimal('0.2')
    assert m.with_rates({'clicks': 0, 'cost': 10, 'sales': 0})['acos'] is None


def test_filter_changes_do_not_drop_literal_percent_from_search():
    m = api()
    f = m.Filters({'view': 'keyword', 'start': '2026-08-08', 'end': '2026-09-06', 'currency': 'EUR', 'msku': '100%_x'})
    sql, params = m.where(f)
    assert 'exists' in sql.lower()
    assert '100%_x' not in sql
    assert '%100!%!_x%' in params


def test_exact_identity_is_validated():
    m = api()
    with pytest.raises(ValueError):
        m.Filters({'key': 'oops'})
    with pytest.raises(ValueError):
        m.Filters({'profile_id': '1 or 1=1'})


def test_long_trend_range_avoids_the_date_order_index():
    m = api()
    long_range = m.Filters({'start': '2026-08-08', 'end': '2026-09-06'})
    one_day = m.Filters({'start': '2026-09-06', 'end': '2026-09-06'})
    assert 'ignore index' in m.trend_index_hint(long_range).lower()
    assert m.trend_index_hint(one_day) == ''


def test_object_filters_are_independent_and_combined_with_and():
    m = api()
    filters = m.Filters({
        'view': 'search_term',
        'start': '2026-08-08',
        'end': '2026-09-06',
        'store': 'jingjie',
        'country': 'US',
        'campaign': 'JJ068a',
        'ad_group': 'KW',
        'keyword_text': 'float switch',
        'search_term': '12volt',
    })

    sql, params = m.where(filters)

    assert "coalesce(seller_name, '') like %s escape '!'" in sql
    assert "coalesce(country_code, '') like %s escape '!'" in sql
    assert "coalesce(campaign_name_current, '') like %s escape '!'" in sql
    assert "coalesce(ad_group_name_current, '') like %s escape '!'" in sql
    assert "coalesce(keyword_text, target_text, '') like %s escape '!'" in sql
    assert "coalesce(search_term, '') like %s escape '!'" in sql
    assert params[-6:] == [
        '%jingjie%', '%US%', '%JJ068a%', '%KW%', '%float switch%', '%12volt%'
    ]
