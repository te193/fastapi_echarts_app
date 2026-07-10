from app import main
from etl import price_review_update


def test_price_review_adjustment_ratio_uses_after_minus_before_in_tracking_sql():
    sql = " ".join(price_review_update._tracking_insert_sql("etl_datasync_test").split())

    assert "(b.price_after - b.price_before) / nullif(b.price_before, 0)" in sql
    assert "(b.price_before - b.price_after) / nullif(b.price_before, 0)" not in sql


def test_price_review_adjustment_ratio_uses_after_minus_before_in_source_sql():
    sql = " ".join(
        price_review_update._select_price_review_adjustment_source_sql("remote_queue").split()
    )

    after_pos = sql.index("adjust_after_obj_standard_price")
    before_pos = sql.index("adjust_before_obj_standard_price", after_pos)

    assert after_pos < before_pos


def test_price_review_export_headers_use_adjustment_ratio_labels():
    labels = {field: label for label, field in main._SKU_EXPORT_COLUMNS}

    assert labels["drop_ratio"] == "调价幅度"
    assert labels["drop_range"] == "调价幅度区间"


def test_price_review_drop_ranges_match_adjustment_ratio_sign():
    sql = " ".join(price_review_update._tracking_insert_sql("etl_datasync_test").split())

    assert "when drop_ratio < -0.30 then '降价>30%%'" in sql
    assert "when drop_ratio < 0 then '降价0-5%%'" in sql
    assert "when drop_ratio <= 0.05 then '涨价0-5%%'" in sql
    assert "else '涨价>30%%'" in sql
