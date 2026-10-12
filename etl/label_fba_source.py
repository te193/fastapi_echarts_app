"""Label-only projection of remote DWD FBA; shared inventory ETL is untouched."""

RAW_REFERENCE = ("dwd_datasync", "lx_storage_fba_warehouse_detail")
RAW_COLUMNS = (
    "create_time",
    "name",
    "seller_sku",
    "total",
    "afn_fulfillable_quantity",
    "stock_up_num",
    "inv_age_271_to_330_days",
    "inv_age_331_to_365_days",
    "inv_age_365_plus_days",
)
DERIVED_COLUMNS = (
    "seller_sku_adj",
    "seller_name",
    "seller_name_new",
    "country_category",
)
NORMALIZATION_VERSION = "dwd_fba_label_projection_20261009"


def fba_columns(metadata: list[dict]) -> list[dict]:
    by_name = {c["column_name"]: c for c in metadata}
    missing = set(RAW_COLUMNS) - by_name.keys()
    if missing:
        raise RuntimeError(f"DWD FBA required columns missing: {sorted(missing)}")
    derived = [
        {
            "column_name": name,
            "column_type": "varchar(255)",
            "is_nullable": "YES",
            "character_set_name": "utf8mb4",
            "collation_name": "utf8mb4_0900_ai_ci",
        }
        for name in DERIVED_COLUMNS
    ]
    return [by_name[name] for name in RAW_COLUMNS] + derived


def fba_indexes() -> list[dict]:
    # V47 explicitly uses FORCE INDEX(id1). Keep that lookup contract locally.
    return [
        {
            "index_name": "id1",
            "non_unique": 1,
            "seq_in_index": i,
            "column_name": name,
            "sub_part": None,
        }
        for i, name in enumerate(
            ("seller_sku_adj", "create_time", "country_category", "seller_name_new"), 1
        )
    ] + [
        {
            "index_name": "idx_label_fba_date",
            "non_unique": 1,
            "seq_in_index": 1,
            "column_name": "create_time",
            "sub_part": None,
        }
    ]


def fba_select_sql(columns: list[str]) -> str:
    allowed = set(RAW_COLUMNS + DERIVED_COLUMNS)
    if not columns or len(set(columns)) != len(columns) or set(columns) - allowed:
        raise ValueError("invalid label DWD FBA projection columns")
    expressions = {name: f"`{name}`" for name in RAW_COLUMNS}
    store = "regexp_replace(`name`, '[一-龥]', '')"
    expressions.update(
        {
            "create_time": "cast(date(`create_time`) as datetime)",
            "seller_name": store,
            "seller_name_new": f"substring_index({store}, '-', 1)",
            "seller_sku_adj": "if(length(`seller_sku`)>16, replace(substring_index(`seller_sku`, '-', 1), 'amzn.gr.', ''), `seller_sku`)",
            "country_category": "case when `name` like '%英国%' then '英国站' when `name` regexp '北美|美国|加拿大|巴西|墨西哥' then '北美站' else '欧洲站' end",
        }
    )
    return (
        "select "
        + ", ".join(f"{expressions[c]} as `{c}`" for c in columns)
        + " from `dwd_datasync`.`lx_storage_fba_warehouse_detail`"
    )
