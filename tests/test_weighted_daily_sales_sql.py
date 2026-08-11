import re
from pathlib import Path


SQL_PATH = Path(__file__).resolve().parents[1] / "data" / "补货页面加权日销计算.sql"


def _sql_text() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


def _final_select(sql: str) -> str:
    match = re.search(
        r"\nselect\s+cast\(@biz_date\s+as\s+date\).*?\nfrom\s+weighted_metrics\s+as\s+w",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert match is not None, "未找到最终加权日销 select"
    return match.group(0).lower()


def test_final_select_keeps_period_inputs_but_only_exposes_weighted_daily_sales():
    final_select = _final_select(_sql_text())

    for alias in (
        "daily_sales_3d",
        "daily_sales_7d",
        "daily_sales_14d",
        "daily_sales_30d",
    ):
        assert f" as {alias}" not in final_select

    for column in (
        "sales_3",
        "r_3d_salable_days",
        "sales_7",
        "r_7d_salable_days",
        "sales_14",
        "r_14d_salable_days",
        "sales_30",
        "r_30d_salable_days",
        "daily_avg_sales",
    ):
        assert column in final_select


def test_sql_keywords_and_functions_are_lowercase():
    sql = re.sub(
        r"--.*?$|/\*.*?\*/|'(?:''|[^'])*'",
        " ",
        _sql_text(),
        flags=re.MULTILINE | re.DOTALL,
    )
    sql_words = {
        "add", "alter", "and", "as", "binary", "by", "case", "cast",
        "char", "charset", "coalesce", "count", "create", "date", "date_add",
        "date_format", "date_sub", "day", "decimal", "default", "desc",
        "drop", "else", "end", "engine", "exists", "force", "from",
        "greatest", "group", "if", "in", "index", "interval", "is",
        "join", "key", "leading", "least", "left", "length", "like",
        "locate", "max", "min", "not",
        "null", "nullif", "on", "or", "order", "over", "partition",
        "primary", "round", "row_number", "select", "set", "sum", "table",
        "substring_index", "temporary", "then", "trim", "upper", "when",
        "where", "with",
    }
    uppercase_tokens = [
        token
        for token in re.findall(r"\b[A-Za-z_]+\b", sql)
        if token.lower() in sql_words and token != token.lower()
    ]

    assert uppercase_tokens == []
