from datetime import date
import pytest

from etl.label_local_contracts import dictionary_contract, validate_dictionary, validate_history_coverage
from etl.label_local_sources import validate_source_count


def test_partial_input_history_cannot_restart_continuous_counts_and_publish():
    with pytest.raises(RuntimeError, match="2026-01-01"):
        validate_history_coverage(date(2026, 10, 6), {date(2026, 10, 6), date(2026, 10, 7)}, date(2026, 10, 7))


def test_input_context_can_precede_label_replay_start():
    from datetime import timedelta
    dates = {date(2026, 1, 1) + timedelta(days=n) for n in range(280)}
    dates.add(date(2025, 12, 11))
    validate_history_coverage(date(2026, 1, 1), dates, date(2026, 10, 7))


def test_recent_period_publication_still_rejects_missing_days():
    start, end = date(2026, 10, 6), date(2026, 10, 7)
    validate_history_coverage(start, {start, end}, end, require_baseline=False)
    with pytest.raises(RuntimeError, match='lacks business dates'):
        validate_history_coverage(start, {end}, end, require_baseline=False)
    with pytest.raises(RuntimeError, match='starts after'):
        validate_history_coverage(end, {end}, start, require_baseline=False)


@pytest.mark.parametrize("parent", [13, 20, 21, 23])
def test_missing_or_disabled_whole_dictionary_family_is_blocked(parent):
    rows = dictionary_contract()
    validate_dictionary(rows)
    with pytest.raises(RuntimeError, match="dictionary contract"):
        validate_dictionary([r for r in rows if r["label_id"] != parent])
    with pytest.raises(RuntimeError, match="dictionary contract"):
        validate_dictionary([{**r, "status": "未启用"} if r["label_id"] == parent else r for r in rows])


def test_fba_missing_is_not_treated_as_zero_stock():
    with pytest.raises(RuntimeError, match="empty"):
        validate_source_count("dashboard_label_source_fba", 0)
    validate_source_count("dashboard_label_source_listing_tag", 0)
