from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeAdBudgetService:
    def __init__(self):
        self.calls = []

    def get_meta(self):
        self.calls.append(("meta", {}))
        return {"budget_date": "2026-08-11", "performance_date": "2026-08-12"}

    def get_payload(self, **kwargs):
        self.calls.append(("payload", kwargs))
        return {"rows": [], "total": 0}

    def get_detail(self, **kwargs):
        self.calls.append(("detail", kwargs))
        return {"identity": kwargs, "trend": []}


def test_ad_budget_page_renders_operating_workbench():
    response = TestClient(main.app).get("/ad-budget")

    assert response.status_code == 200
    assert "广告预算执行工作台" in response.text
    assert "ad-budget.js" in response.text


def test_ad_budget_page_renders_loading_placeholders_before_javascript_finishes():
    response = TestClient(main.app).get("/ad-budget")

    assert response.status_code == 200
    assert response.text.count('class="ab-skeleton ab-skeleton-kpi"') == 4
    assert response.text.count('class="ab-skeleton ab-skeleton-chart') == 2
    assert 'class="ab-grid-loading"' in response.text


def test_ad_budget_initializes_meta_and_main_data_requests_in_parallel():
    script = (PROJECT_ROOT / "app/static/js/ad-budget.js").read_text(encoding="utf-8")

    assert 'var metaRequest=api("/api/ad-budget/meta")' in script
    assert "var dataRequest=load();" in script
    assert "Promise.allSettled([metaRequest,dataRequest])" in script


def test_ad_budget_removes_grid_skeleton_before_ag_grid_mounts():
    script = (PROJECT_ROOT / "app/static/js/ad-budget.js").read_text(encoding="utf-8")
    render_table = script[script.index("function renderTable"):script.index("function load")]

    destroy_at = render_table.index('window.kanbanGrid.destroy("ab-grid")')
    clear_at = render_table.index('el("ab-grid").replaceChildren()')
    mount_at = render_table.index('window.kanbanGrid.makeGrid("ab-grid"')
    assert destroy_at < clear_at < mount_at


def test_ad_budget_product_cell_labels_identifiers_and_supports_copying():
    script = (PROJECT_ROOT / "app/static/js/ad-budget.js").read_text(encoding="utf-8")
    stylesheet = (PROJECT_ROOT / "app/static/css/ad_budget.css").read_text(encoding="utf-8")
    service = (PROJECT_ROOT / "app/services/ad_budget_data.py").read_text(encoding="utf-8")
    template = (PROJECT_ROOT / "app/templates/ad_budget.html").read_text(encoding="utf-8")

    assert "站点：" in script
    assert "店铺：" in script
    assert 'headerName:"MSKU / ASIN"' in script
    assert 'headerName:"站点总预算"' not in script
    assert 'headerName:"市场池总预算"' not in script
    assert 'headerName:"广告总预算"' in script
    assert "budgetMetric(r.monthly_ad_budget_cny,r.month_spend" in script
    assert "budgetMetric(r.weekly_ad_budget_cny,r.spend_7d" in script
    assert "identifierCell(row)" in script
    assert 'identifierLine("MSKU", row.seller_sku_adj, true)' in script
    assert 'identifierLine("ASIN", row.asin, false)' in script
    assert "data-copy-value" in script
    assert "navigator.clipboard.writeText" in script
    assert '{headerName:"广告转化",field:"ad_orders",width:205' in script
    assert 'headerName:"TACOS / ACOS"' in script
    assert 'headerName:"ACOS / TACOS"' not in script
    assert 'metricCell(pct(r.tacos),"ACOS "+pct(r.acos))' in script
    assert "then sales_amount else 0 end) as sales_amount" in service
    assert "then sales_amount else 0 end) as sales_amount_7d" in service
    assert "then sales_qty else 0 end) as sales_qty_7d" in service
    assert "then sessions_total else 0 end) as sessions_total_7d" in service
    assert "TACOS '+pct(r.tacos)+' · ACOS '+pct(r.acos)" in script
    assert "ROAS '+num(r.roas_7d,2)" not in script
    assert 'class="ab-business-summary"' in script
    assert '本月至今经营数据' in script
    assert '本月至今广告漏斗' in script
    assert '近 7 天经营数据' not in script
    assert '近 7 天广告漏斗' not in script
    assert '经营销售额' in script
    assert '广告销售占比' in script
    assert 'money(r.sales_amount)' in script
    assert 'num(r.sales_qty,0)' in script
    assert 'num(r.sessions_total,0)' in script
    assert 'pct(r.ad_sales_share)' in script
    assert 'money(r.month_spend)' in script
    assert '月剩余额度' in script
    drawer_source = script[script.index("function renderDetail"):script.index("function bind")]
    assert 'weekly_ad_budget_cny' not in drawer_source
    assert ".ab-metric-emphasis" not in stylesheet
    assert ".ad-budget-grid .ab-metric{width:100%;min-width:0;overflow:hidden}" in stylesheet
    assert "text-overflow:ellipsis" in stylesheet
    assert "event.stopPropagation()" in script
    assert 'button.disabled = !value' in script


def test_ad_budget_table_uses_ag_grid_with_server_page_size_selector():
    script = (PROJECT_ROOT / "app/static/js/ad-budget.js").read_text(encoding="utf-8")
    template = (PROJECT_ROOT / "app/templates/ad_budget.html").read_text(encoding="utf-8")
    styles = (PROJECT_ROOT / "app/static/css/ad_budget.css").read_text(encoding="utf-8")

    assert 'id="ab-page-size"' in template
    assert all(f'<option value="{size}"' in template for size in (20, 50, 100, 200))
    assert 'localStorage.getItem("adBudgetPageSize")' in script
    assert 'localStorage.setItem("adBudgetPageSize"' in script
    assert 'id="ab-grid"' in template
    assert 'kanbanGrid.makeGrid("ab-grid"' in script
    assert 'domLayout: "normal"' in script
    assert ".ad-budget-grid{height:min(620px,calc(100vh - 190px))" in styles


def test_ad_budget_api_forwards_filters_sort_and_pagination():
    service = FakeAdBudgetService()
    with patch("app.main.ad_budget_service", service):
        payload = main.api_ad_budget(
            country_category="欧洲站",
            country="德国",
            seller_name_new="A",
            product_type="老品",
            inventory_status="monthly_sufficient",
            anomaly="消耗过快",
            keyword="SKU1",
            page=2,
            page_size=50,
            sort_field="month_spend",
            sort_dir="asc",
            column_filters='{"monthly_ad_budget_cny":{"filterType":"number","type":"greaterThan","filter":100}}',
        )

    assert payload == {"rows": [], "total": 0}
    assert service.calls == [
        (
            "payload",
            {
                "country_category": "欧洲站",
                "country": "德国",
                "seller_name_new": "A",
                "product_type": "老品",
                "inventory_status": "monthly_sufficient",
                "anomaly": "消耗过快",
                "keyword": "SKU1",
                "page": 2,
                "page_size": 50,
                "sort_field": "month_spend",
                "sort_dir": "asc",
                "column_filters": '{"monthly_ad_budget_cny":{"filterType":"number","type":"greaterThan","filter":100}}',
            },
        )
    ]


def test_ad_budget_grid_uses_server_side_header_sorting_and_filtering():
    script = (PROJECT_ROOT / "app/static/js/ad-budget.js").read_text(encoding="utf-8")

    assert "sortable:false" not in script
    assert "filter:false" not in script
    assert "onSortChanged:handleGridSortChanged" in script
    assert "onFilterChanged:handleGridFilterChanged" in script
    assert "getFilterModel" in script
    assert 'params.set("column_filters",JSON.stringify(state.columnFilters))' in script
    assert 'state.page=1;load();' in script
    assert 'sort:colSort("monthly_ad_budget_cny")' in script
    assert 'state.columnFilters={};state.sortField="anomaly_priority";state.sortDir="asc"' in script
    assert 'if(!state.gridReady)return;' in script
    assert 'onFirstDataRendered:function(){state.gridReady=true;}' in script
    assert 'valueGetter:numericValue("monthly_ad_budget_cny")' in script


def test_anomaly_panel_explains_rules_in_a_hover_and_focus_tooltip():
    template = (PROJECT_ROOT / "app/templates/ad_budget.html").read_text(encoding="utf-8")
    stylesheet = (PROJECT_ROOT / "app/static/css/ad_budget.css").read_text(encoding="utf-8")

    assert 'id="ab-anomaly-help"' in template
    assert 'role="tooltip"' in template
    assert 'aria-describedby="ab-anomaly-help"' in template
    assert "未启动" in template
    assert "预算偏慢" in template
    assert "有花费但无月预算" in template
    assert "同国家、新老品分组" in template
    assert ".ab-help-wrap:hover .ab-anomaly-help" in stylesheet
    assert ".ab-help-wrap:focus-within .ab-anomaly-help" in stylesheet


def test_budget_rate_copy_uses_budget_consumption_rate_wording():
    template = (PROJECT_ROOT / "app/templates/ad_budget.html").read_text(encoding="utf-8")
    script = (PROJECT_ROOT / "app/static/js/ad-budget.js").read_text(encoding="utf-8")

    assert 'kpi("月预算消耗"' in script
    assert 'kpi("近 7 天预算消耗"' in script
    assert '"预算消耗率 " + pct' in script
    assert "月预算消耗率比当月时间进度" in template
    assert "月预算消耗率比时间进度落后" in template
    assert "执行率" not in script


def test_ad_budget_detail_requires_exact_site_product_identity():
    service = FakeAdBudgetService()
    with patch("app.main.ad_budget_service", service):
        payload = main.api_ad_budget_detail(
            country_category="欧洲站",
            country="法国",
            seller_name_new="A",
            seller_sku_adj="SKU1",
        )

    assert payload["identity"]["country"] == "法国"
    assert service.calls == [
        (
            "detail",
            {
                "country_category": "欧洲站",
                "country": "法国",
                "seller_name_new": "A",
                "seller_sku_adj": "SKU1",
            },
        )
    ]
