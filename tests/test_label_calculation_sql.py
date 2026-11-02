"""Calculation optimizations may change access paths, never label formulas."""
import re

import pytest

from etl.label_local_sql import compile_procedure, sql_tokens


def query(sql, name):
    return re.search(r"create temporary table " + name + r"\b.*?;", sql, re.S).group()


def test_calculation_optimization_preserves_business_sql_except_redundant_lookup():
    baseline = compile_procedure("label_test", optimize_calculation=False)
    optimized = compile_procedure("label_test", optimize_calculation=True)
    lookup = r"\s+and f\.`seller_sku_adj` = ([kx])\.msku collate utf8mb4_0900_ai_ci"
    assert len(re.findall(lookup, optimized)) == 2
    normalized = re.sub(lookup, "", optimized)
    normalize = lambda s: [(k, v) for k, v in sql_tokens(s) if k not in {"space", "comment"}]
    assert normalize(normalized) == normalize(baseline)


@pytest.mark.parametrize("name,alias", [
    ("tmp_op_fba_latest_key", "k"), ("tmp_op_fba", "x"),
])
def test_inventory_lookup_retains_original_cast_and_dimension_filters(name, alias):
    sql = query(compile_procedure("label_test", optimize_calculation=True), name)
    assert f"{alias}.msku = cast(f.`seller_sku_adj` as char)" in sql
    assert f"f.`seller_sku_adj` = {alias}.msku collate utf8mb4_0900_ai_ci" in sql
    assert "country_category = cast(f.`country_category` as char)" in sql
    assert "seller_name_new" in sql


def test_calculation_optimization_rejects_changed_inventory_query(tmp_path):
    from etl.label_local_sql import BASELINE_PATH

    path = tmp_path / "changed.sql"
    path.write_text(BASELINE_PATH.read_text(encoding="utf-8-sig").replace(
        "AND k.MSKU = CAST(f.`seller_sku_adj` AS CHAR)",
        "AND k.MSKU = CAST(f.`seller_sku_adj` AS CHAR(20))",
    ), encoding="utf-8")
    with pytest.raises(ValueError, match="FBA lookup layout changed"):
        compile_procedure("label_test", path=path, check_hash=False, optimize_calculation=True)
