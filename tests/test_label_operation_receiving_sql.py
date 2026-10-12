"""Execute the real SQL predicates to prevent zero-stock receiving coverage gaps."""

from pathlib import Path
import json
import re
import sqlite3

import pytest


SQL_PATH = (
    Path(__file__).resolve().parents[1]
    / "sqlcode"
    / "标签表数据插入_修改版_20261008_v47_接收中归入断货中修复版.sql"
)


def operation_predicate(alias):
    sql = SQL_PATH.read_text(encoding="utf-8-sig")
    block = sql.split("SET v_stage = 'tmp_op';", 1)[1]
    return _extract_predicate(block, alias)


def _extract_predicate(block, alias):
    end = re.search(r"\bend as " + alias + r"\b", block, re.I).start()
    start = block.lower().rfind("case", 0, end)
    expression = block[start:end] + "end"
    return expression


def evaluate(available, receiving, transit, local, purchase, box):
    with sqlite3.connect(":memory:") as conn:
        return conn.execute(
            f"select {operation_predicate('is_out_of_stock')}, {operation_predicate('is_stopped')} "
            "from (select ? as fba_available, ? as fba_in_transit) f "
            "cross join (select ? as has_receiving_shipment) rs "
            "cross join (select ? as local_warehouse_quantity, ? as purchase_plan_quantity) l "
            "cross join (select ? as source_box_quantity) b",
            (available, transit, receiving, local, purchase, box),
        ).fetchone()


@pytest.mark.parametrize(
    "available,receiving,transit,local,purchase,box,expected",
    [
        (0, 1, 0, 0, 0, 50, (1, 0)),
        (0, 1, 10, 0, 0, 50, (1, 0)),
        (0, 1, 50, 0, 0, 50, (1, 0)),
        (0, 0, 49, 0, 0, 50, (0, 1)),
        (0, 0, 50, 0, 0, 50, (1, 0)),
        (0, 0, 10, 20, 20, 50, (1, 0)),
        (0, None, 0, 0, 0, None, (0, 1)),
        (0, 1, None, None, None, None, (1, 0)),
        (1, 1, 0, 0, 0, 50, (0, 0)),
        (1, 0, 100, 0, 0, 50, (0, 0)),
        (-1, 1, 100, 0, 0, 50, (0, 0)),
    ],
)
def test_receiving_zero_stock_is_stockout_and_statuses_remain_exclusive(
    available, receiving, transit, local, purchase, box, expected
):
    assert evaluate(available, receiving, transit, local, purchase, box) == expected


@pytest.mark.parametrize(
    "status,receiving,expected_receiving,expected_supply",
    [
        ("断货中", 1, "= 1", "not_required_when_receiving"),
        ("断货中", 0, "= 0", ">= unit_box_quantity"),
        ("停售", 0, "= 0", "< unit_box_quantity"),
    ],
)
def test_evidence_describes_the_actual_receiving_or_supply_branch(
    status, receiving, expected_receiving, expected_supply
):
    sql = SQL_PATH.read_text(encoding="utf-8-sig")
    block = sql.split(
        "WHEN h.child_label_name IN ('断货中','停售') THEN JSON_OBJECT(", 1
    )[1]
    expression = block.split("'matched_rule',", 1)[1].split(
        "'missing_box_quantity_rule','use 50'", 1
    )[0]
    expression += "'missing_box_quantity_rule','use 50')"
    with sqlite3.connect(":memory:") as conn:
        raw = conn.execute(
            f"select {expression} from (select ? as child_label_name) h "
            "cross join (select ? as has_receiving_shipment) op",
            (status, receiving),
        ).fetchone()[0]
    rule = json.loads(raw)
    assert rule["has_receiving_shipment"] == expected_receiving
    assert rule["supply_quantity"] == expected_supply
