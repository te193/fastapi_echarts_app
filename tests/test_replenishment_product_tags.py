from datetime import date
from unittest.mock import MagicMock

from app.services.replenishment_data import ReplenishmentDataService


def test_product_tags_preserve_rows_case_and_merge_duplicates():
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    service.connect_source = MagicMock()
    cursor = service.connect_source.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        {"sku": "SKU-A", "tag_name": "退税产品"},
        {"sku": "SKU-A", "tag_name": "退税产品"},
        {"sku": "SKU-A", "tag_name": " 重点产品 "},
        {"sku": "sku-a", "tag_name": "另一产品"},
        {"sku": "SKU-A", "tag_name": None},
    ]
    rows = [{"sku": "SKU-A"}, {"sku": "SKU-A"}, {"sku": "sku-a"}, {"sku": "missing"}, {"sku": None}]
    service._attach_product_tags(rows, "sku")
    assert len(rows) == 5
    assert rows[0]["product_tags"] == rows[1]["product_tags"] == "退税产品 | 重点产品"
    assert rows[2]["product_tags"] == "另一产品"
    assert rows[3]["product_tags"] == rows[4]["product_tags"] == ""
    sql, params = cursor.execute.call_args.args
    assert "dwd_datasync.lx_product_local_product_info" in sql
    assert set(params) == {"SKU-A", "sku-a", "missing"}


def test_empty_product_skus_do_not_query_source():
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    service.connect_source = MagicMock()
    rows = [{"max_sku": None}]
    service._attach_product_tags(rows, "max_sku")
    assert rows == [{"max_sku": None, "product_tags": ""}]
    service.connect_source.assert_not_called()


def test_export_adds_product_tags_after_fetching_physical_columns():
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    service.connect = MagicMock()
    service._latest_date = MagicMock(return_value=date(2026, 9, 9))
    service._build_where = MagicMock(return_value=("1=1", {}))
    service._export_columns = MagicMock(return_value=[{"name": "max_sku", "label": "SKU"}])
    service._export_items = MagicMock(return_value=[{"max_sku": "SKU-A"}])
    service._attach_product_tags = MagicMock(side_effect=lambda rows, key: rows[0].update(product_tags="退税产品"))
    payload = service.get_export_payload()
    assert {"name": "product_tags", "label": "产品标签"} in payload["columns"]
    assert payload["rows"][0]["product_tags"] == "退税产品"
    assert "product_tags" not in service._export_items.call_args.args[5]

    from io import BytesIO
    from openpyxl import load_workbook
    from app.main import build_replenishment_xlsx

    workbook = load_workbook(BytesIO(build_replenishment_xlsx(payload)))
    values = list(workbook.active.values)
    assert "产品标签" in values[0]
    assert values[1][values[0].index("产品标签")] == "退税产品"
