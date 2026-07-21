from pathlib import Path


JS = Path("app/static/js/replenishment.js").read_text(encoding="utf-8")


def test_moq_warning_card_is_clickable_and_filters_detail_rows():
    assert "data-moq-status=\"below_minimum\"" in JS
    assert "state.moq_status = \"below_minimum\"" in JS
    assert "state.level = \"all\"" in JS
    assert "moq_warning_count" in JS
    assert "moq_warning_calculated_qty" in JS


def test_replenishment_table_exposes_moq_comparison_columns():
    assert 'numberColumn(text.calculatedReplenishQty, "calculated_replenish_qty"' in JS
    assert 'numberColumn(text.supplierMoq, "supplier_moq"' in JS
    assert 'numberColumn(text.moqShortfall, "moq_shortfall_qty"' in JS
    assert 'field: "moq_status"' in JS


def test_export_includes_moq_status_filter():
    assert '"moq_status"' in JS[JS.index("function exportReplenishment"):]
