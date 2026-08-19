import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GRID_SCRIPT = ROOT / "app" / "static" / "js" / "price_review_role_grid.js"


def run_grid_contract(expression: str, payload: dict) -> dict:
    node = shutil.which("node")
    assert node, "Node.js is required for the role-grid frontend contract test"
    script = f"""
const fs = require('fs');
const grid = require(process.argv[1]);
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = {expression};
process.stdout.write(JSON.stringify(result));
"""
    result = subprocess.run(
        [node, "-e", script, str(GRID_SCRIPT)],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_role_grid_uses_ag_grid_columns_without_the_redundant_window_column():
    result = run_grid_contract(
        "grid.buildColumnDefs({}).map(column => ({ headerName: column.headerName, field: column.field || null, pinned: column.pinned || null }))",
        {},
    )

    assert [column["headerName"] for column in result] == [
        "国家",
        "店铺",
        "MSKU",
        "调前角色",
        "调后角色",
        "变化",
        "调前日销",
        "调后日销",
        "调前毛利率",
        "调后毛利率",
        "调前财务区间",
        "调后财务区间",
        "财务变化",
        "数据状态",
    ]
    assert "实际窗口" not in [column["headerName"] for column in result]
    assert [column["pinned"] for column in result[:3]] == ["left", "left", "left"]


def test_role_grid_pagination_model_reports_total_pages_and_supported_page_sizes():
    result = run_grid_contract(
        "grid.buildPaginationModel(payload)",
        {"page": 2, "total_pages": 18, "total": 359, "page_size": 20},
    )

    assert result == {
        "page": 2,
        "totalPages": 18,
        "total": 359,
        "pageSize": 20,
        "pageSizes": [20, 50, 100],
        "pages": [1, 2, 3, 4],
        "info": "共 359 条，第 2 / 18 页",
    }


def test_role_grid_copy_action_does_not_open_the_diagnostic_drawer():
    result = run_grid_contract(
        "(() => { const calls = []; const handlers = { handleCopy: event => event.copy, openDetail: key => calls.push(key), activeKey: () => '' }; const options = grid.buildGridOptions([{ msku: 'MSKU-1' }], {}, handlers); options.onRowClicked({ event: { copy: true }, data: options.rowData[0] }); options.onRowClicked({ event: { copy: false }, data: options.rowData[0] }); return { calls, key: options.rowData[0]._roleDetailKey, domLayout: options.domLayout }; })()",
        {},
    )

    assert result == {"calls": ["0"], "key": "0", "domLayout": "normal"}


def test_role_grid_exposes_server_backed_sort_and_column_filter_events():
    result = run_grid_contract(
        "(() => { const handlers = { gridState: { sortField: 'pre_daily_sales', sortDir: 'desc', filterModel: { country: { filterType: 'text', type: 'contains', filter: 'DE' } } } }; const options = grid.buildGridOptions([], {}, handlers); return { sortable: options.defaultColDef.sortable, filterable: options.defaultColDef.filter, initialFilter: options.initialState.filter.filterModel, activeSort: options.columnDefs.find(function (column) { return column.field === 'pre_daily_sales'; }).sort, countryFilter: options.columnDefs.find(function (column) { return column.field === 'country'; }).filter, dailySalesFilter: options.columnDefs.find(function (column) { return column.field === 'pre_daily_sales'; }).filter, hasSortEvent: typeof options.onSortChanged === 'function', hasFilterEvent: typeof options.onFilterChanged === 'function' }; })()",
        {},
    )

    assert result == {
        "sortable": True,
        "filterable": True,
        "initialFilter": {"country": {"filterType": "text", "type": "contains", "filter": "DE"}},
        "activeSort": "desc",
        "countryFilter": "agTextColumnFilter",
        "dailySalesFilter": "agNumberColumnFilter",
        "hasSortEvent": True,
        "hasFilterEvent": True,
    }
