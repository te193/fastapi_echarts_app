"""The fast path must decide before running the product aggregate SQL."""
from datetime import date

import pytest

from etl.dashboard_daily_update import STEPS
from etl import product_consumer_contract as contract


DAY = date(2026, 1, 2)
SQL = STEPS['product_performance_daily'].source_select_statement


def applied(**changes):
    state = dict(rule_sha=contract.rule_sha(SQL), raw_stamp='old',
                 dependency_fp=(2, 10, 20), output_rows=1)
    return {**state, **changes}


def test_unchanged_input_requires_no_projection_hash_or_aggregation():
    assert contract.requires_projection(applied(), 'old', contract.rule_sha(SQL), 1) is False


@pytest.mark.parametrize('change', ['raw', 'rule', 'missing', 'new'])
def test_changes_cannot_use_the_fast_path(change):
    state = None if change == 'new' else applied()
    assert contract.requires_projection(state, 'new' if change == 'raw' else 'old',
                                        'new' if change == 'rule' else contract.rule_sha(SQL),
                                        0 if change == 'missing' else 1)


def test_irrelevant_raw_or_schema_change_does_not_require_aggregation():
    assert not contract.requires_aggregate(applied(), (2, 10, 20), contract.rule_sha(SQL), 1)


@pytest.mark.parametrize('fp,rule,count', [
    ((2, 11, 20), None, 1), ((3, 10, 20), None, 1),
    (None, None, 1), ((2, 10, 20), 'new', 1), ((2, 10, 20), None, 0),
])
def test_business_changes_duplicates_deletions_rules_and_missing_rows_are_candidates(fp, rule, count):
    assert contract.requires_aggregate(applied(), fp, rule or contract.rule_sha(SQL), count)


def test_rule_contract_detects_sql_changes_and_version_changes():
    assert contract.rule_sha(SQL) != contract.rule_sha(SQL.replace('/ 1.19', '/ 1.20'))
    assert contract.rule_sha(SQL) != contract.rule_sha(SQL, rule_version='v2')


def test_contract_has_all_twenty_actual_raw_dependencies():
    contract.validate_sql(SQL)
    assert len(contract.RAW_COLUMNS) == 20
    for column in ('seller_sku', 'country', 'start_date', 'sessions_total', 'rank'):
        assert column in contract.RAW_COLUMNS
    assert not set(contract.RAW_COLUMNS) & {'status', 'page_views_mobile', 'tag_name', 'create_time'}


@pytest.mark.parametrize('changed', [
    SQL.replace('coalesce(volume, 0)', 'coalesce(page_views_mobile, 0)'),
    SQL.replace('from src', 'from src join other_table on 1=1'),
    SQL.replace('dwd_datasync.lx_statistics_product_performance', 'other_schema.other_table'),
    SQL.replace('coalesce(volume, 0)', 'coalesce(volume + new_business_metric, 0)'),
    SQL.replace('and seller_sku not like', 'and unreviewed_flag=1 and seller_sku not like'),
    SQL.replace('coalesce(volume, 0)', 'coalesce(volume + dt_year, 0)'),
    SQL.replace('from dwd_datasync.lx_statistics_product_performance',
                'from dwd_datasync.lx_statistics_product_performance, hidden_lookup'),
    SQL.replace('from dwd_datasync.lx_statistics_product_performance',
                'from dwd_datasync.lx_statistics_product_performance, country'),
])
def test_unreviewed_dependency_changes_fail_closed(changed):
    with pytest.raises(ValueError, match='dependency'):
        contract.validate_sql(changed)


def test_stamp_tracks_schema_epoch_and_partition_but_not_run_id():
    item = dict(columns=['a'], fingerprint_version='v1', partitions={str(DAY): {'rows': 2}},
                shared_acquisition={'run_id': 'first'})
    stamp = contract.raw_stamp(item, DAY)
    assert stamp == contract.raw_stamp({**item, 'shared_acquisition': {'run_id': 'next'}}, DAY)
    assert stamp != contract.raw_stamp({**item, 'columns': ['a', 'irrelevant']}, DAY)
    assert stamp != contract.raw_stamp({**item, 'partitions': {}}, DAY)


def test_coverage_includes_deleted_applied_dates_but_not_unknown_older_target_days():
    item = {'partitions': {'2026-01-02': {}, '2026-01-03': {}}}
    assert contract.covered_dates(item, {date(2026, 1, 1): {}}, date(2025, 1, 1), DAY) == (
        date(2026, 1, 1), DAY)


def test_null_or_invalid_raw_date_partitions_are_retained_but_not_date_candidates():
    item = {'partitions': {'__NULL__': {}, 'invalid': {}, '2026-01-02': {}}}
    assert contract.covered_dates(item, {}, DAY, DAY) == (DAY,)


def test_first_cache_adopts_explicit_deleted_partition_tombstones():
    item = {'partitions': {'2026-01-01': {}, '2026-01-03': {}},
            'shared_acquisition': {'changed_partitions': ['2026-01-02', '__NULL__']}}
    assert contract.covered_dates(item, {}, DAY, DAY) == (DAY,)


def test_deleted_dates_survive_a_failed_consumer_and_an_unchanged_next_input():
    from etl.shared_product_inputs import retain_known_partitions
    before = {'partitions': {'2026-01-01': {}, '2026-01-02': {}, '2026-01-03': {}}}
    deleted = retain_known_partitions({'partitions': {'2026-01-01': {}, '2026-01-03': {}}}, before)
    unchanged_next = retain_known_partitions({'partitions': dict(deleted['partitions'])}, deleted)
    assert contract.covered_dates(unchanged_next, {}, DAY, DAY) == (DAY,)


def test_bootstrap_interior_missing_source_day_is_authoritative_but_outside_days_are_unknown():
    item = {'partitions': {'2026-01-01': {}, '2026-01-03': {}}}
    assert contract.covered_dates(item, {}, date(2025, 1, 1), date(2026, 2, 1),
        target_days=[date(2025, 12, 31), DAY, date(2026, 1, 4)]) == (date(2026, 1, 1), DAY, date(2026, 1, 3))
