from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_margin_price_popover_uses_document_capture_click_delegate():
    script = (ROOT / "app" / "static" / "js" / "replenishment.js").read_text(encoding="utf-8")

    assert 'var button = event.target.closest("[data-margin-price-key]");' in script
    assert 'toggleMarginPricePopover(button, button.dataset.marginPriceKey || "");' in script
    assert 'elements.countryMetricsWrap.addEventListener("click", function (event) {\n      var button = event.target.closest("[data-margin-price-key]");' not in script
    assert 'document.addEventListener("click", function (event) {\n      var button = event.target.closest("[data-margin-price-key]");' in script
    assert "event.stopImmediatePropagation();" in script
    assert "}, true);" in script


def test_margin_price_assets_use_cache_busting_versions():
    base_template = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    replenishment_template = (ROOT / "app" / "templates" / "replenishment.html").read_text(encoding="utf-8")

    assert "styles.css') }}?v=20260706returnclick1" in base_template
    assert "replenishment.js') }}?v=20260630dailycategory2" in replenishment_template
    assert "replenishment_tracking_summary.js') }}?v=20260630chainv8" in replenishment_template
