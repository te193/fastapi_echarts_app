from datetime import date

from etl.station_sales_role_drift_check import compare_role_rows, remote_role_rows_sql


def test_drift_comparison_reports_matches_missing_and_samples():
    remote = [
        {"data_date": date(2026, 8, 16), "country": "德国", "store": "A", "msku": "M1", "label_period": "7d", "role_code": "star"},
        {"data_date": date(2026, 8, 16), "country": "德国", "store": "A", "msku": "M2", "label_period": "7d", "role_code": "dog"},
        {"data_date": date(2026, 8, 16), "country": "法国", "store": "B", "msku": "M3", "label_period": "7d", "role_code": "problem"},
    ]
    local = [
        {**remote[0], "role_code": "star"},
        {**remote[1], "role_code": "potential"},
    ]

    result = compare_role_rows(local, remote, sample_limit=10)

    assert result["sample_count"] == 3
    assert result["matched_count"] == 1
    assert result["mismatch_count"] == 1
    assert result["local_missing_count"] == 1
    assert result["match_rate"] == 1 / 3
    assert result["missing_rate"] == 1 / 3
    assert len(result["mismatch_samples"]) == 2


def test_remote_drift_query_is_read_only_and_uses_station_role_labels():
    sql = " ".join(remote_role_rows_sql(500).split()).lower()

    assert "dws_datasync`.`dws_标签表" in sql
    assert "label_id in (1301, 1302, 1303, 1304)" in sql
    assert "label_period in ('7d', '14d', '30d', '90d')" in sql
    assert "limit 500" in sql
    assert all(token not in sql for token in (" insert ", " update ", " delete ", " drop ", " truncate "))
