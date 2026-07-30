from datetime import date, datetime

from etl.product_performance_history_sync import (
    BATCH_TASK_NAME,
    TASK_NAME,
    changed_history_ranges,
    coalesce_dates,
    required_history_start,
    split_ranges,
    transaction_ranges,
)


def test_batch_logs_do_not_advance_the_completed_history_watermark():
    assert BATCH_TASK_NAME != TASK_NAME


def test_required_history_start_matches_return_goods_source_window():
    assert required_history_start(date(2026, 7, 28), history_days=381) == date(2025, 7, 13)


def test_coalesce_dates_combines_only_adjacent_days():
    assert coalesce_dates(
        [
            date(2026, 4, 8),
            date(2026, 4, 9),
            date(2026, 4, 17),
            date(2026, 5, 6),
            date(2026, 5, 7),
        ]
    ) == [
        (date(2026, 4, 8), date(2026, 4, 9)),
        (date(2026, 4, 17), date(2026, 4, 17)),
        (date(2026, 5, 6), date(2026, 5, 7)),
    ]


def test_first_run_refreshes_history_before_the_rolling_window():
    ranges = changed_history_ranges(
        biz_date=date(2026, 7, 28),
        history_days=381,
        rolling_days=50,
        last_success_at=None,
        changed_dates=[],
    )

    assert ranges == [(date(2025, 7, 13), date(2026, 6, 8))]


def test_incremental_run_ignores_dates_already_covered_by_rolling_refresh():
    ranges = changed_history_ranges(
        biz_date=date(2026, 7, 28),
        history_days=381,
        rolling_days=50,
        last_success_at=datetime(2026, 7, 28, 6, 0),
        changed_dates=[
            date(2025, 7, 12),
            date(2026, 4, 8),
            date(2026, 4, 9),
            date(2026, 6, 9),
            date(2026, 7, 28),
        ],
    )

    assert ranges == [(date(2026, 4, 8), date(2026, 4, 9))]


def test_split_ranges_limits_each_database_transaction():
    assert split_ranges(
        [(date(2026, 4, 8), date(2026, 4, 17))],
        max_days=4,
    ) == [
        (date(2026, 4, 8), date(2026, 4, 11)),
        (date(2026, 4, 12), date(2026, 4, 15)),
        (date(2026, 4, 16), date(2026, 4, 17)),
    ]


def test_first_backfill_uses_one_source_scan_but_incremental_runs_are_chunked():
    ranges = [(date(2025, 7, 13), date(2026, 6, 8))]

    assert transaction_ranges(ranges, first_run=True, max_days=7) == ranges
    assert len(transaction_ranges(ranges, first_run=False, max_days=7)) > 1
