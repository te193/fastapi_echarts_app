import sqlite3

import pytest

from etl.label_fba_source import fba_select_sql


@pytest.mark.parametrize("earlier,latest", [(5, 0), (0, 7), (6, 2)])
def test_projection_preserves_latest_intraday_inventory(earlier, latest):
    with sqlite3.connect(":memory:") as conn:
        conn.execute("attach database ':memory:' as dwd_datasync")
        conn.execute(
            "create table dwd_datasync.lx_storage_fba_warehouse_detail "
            "(create_time text, afn_fulfillable_quantity integer)"
        )
        conn.executemany(
            "insert into dwd_datasync.lx_storage_fba_warehouse_detail values (?, ?)",
            [("2026-10-11 09:00:00", earlier), ("2026-10-11 18:00:00", latest)],
        )
        projection = fba_select_sql(["create_time", "afn_fulfillable_quantity"])
        quantity = conn.execute(
            f"with projected as ({projection}) "
            "select sum(afn_fulfillable_quantity) from projected "
            "where create_time = (select max(create_time) from projected)"
        ).fetchone()[0]
    assert quantity == latest
