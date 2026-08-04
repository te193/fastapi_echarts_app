# 补货列表交期信息紧凑展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在补货 SKU 列表中用一个“库存 / 交期”复合列展示当前支撑、采购交期、到货支撑和断货风险，并通过弹层展示完整交期指标。

**Architecture:** 后端列表查询直接读取 ETL 已落库的交期指标并通过现有 `/api/replenishment` 接口返回；前端使用一个自定义 AG Grid 单元格替换原“支撑天数”数字列。完整指标沿用页面已有的 document-level popover 模式展示，排序仍映射到 `inventory_support_days`，导出不创建新的组合列。

**Tech Stack:** Python 3、FastAPI、PyMySQL、原生 JavaScript、AG Grid、CSS、pytest、Playwright 页面验收。

## Global Constraints

- 不修改 ETL 计算公式、补货分层和补货数量。
- 表格只保留一个“库存 / 交期”列，不增加五个独立交期列。
- 到货支撑天数、到货预计库存等负值必须原样展示，不截断为 0。
- 日销小于或等于 0 时显示“无法计算”，不标记为安全或断货。
- 未配置交期时展示 ETL 已生效的默认 10 天，并保留 `purchase_lead_status`。
- 导出不增加“库存 / 交期”组合列；现有原始交期字段继续使用当前导出机制。
- 只修改补货页面，不调整补货追踪等其他页面。

---

## File Structure

- Modify: `app/services/replenishment_data.py` — 查询并序列化列表需要的交期指标。
- Modify: `app/static/js/replenishment.js` — 渲染复合单元格、风险文案和交期详情弹层。
- Modify: `app/static/css/styles.css` — 复合单元格、风险标签和弹层样式。
- Modify: `app/templates/base.html` — 更新 CSS 静态资源版本号。
- Modify: `app/templates/replenishment.html` — 更新补货页 JavaScript 静态资源版本号。
- Modify: `tests/test_replenishment_data.py` — 后端查询与序列化契约测试。
- Modify: `tests/test_replenishment_frontend.py` — 单列布局、交互、样式和资源版本契约测试。

### Task 1: 补货列表接口返回交期明细

**Files:**
- Modify: `app/services/replenishment_data.py:1544-1650,1942-1975`
- Test: `tests/test_replenishment_data.py`

**Interfaces:**
- Consumes: `dashboard_pur_plan_replenish_data` 已有字段 `effective_purchase_lead_days`、`purchase_lead_status`、`arrival_inventory_support_days`、`arrival_inventory_qty`、`lead_time_demand_qty`、`lead_time_stockout_flag`、`lead_time_stockout_days`。
- Produces: `_serialize_item(row) -> dict` 新增同名 API 键；数值键返回两位小数或 `None`，状态键保留字符串/整数语义。

- [ ] **Step 1: 写查询和序列化失败测试**

在 `tests/test_replenishment_data.py` 增加：

```python
def test_items_query_selects_purchase_lead_time_detail_fields(self):
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)
    conn = RecordingConnection([])

    service._items(
        conn,
        filters="cur_date = %(snapshot_date)s",
        params={"snapshot_date": "2026-08-03"},
        sort_field="support_days",
        sort_dir="asc",
        page=1,
        page_size=20,
    )

    sql = conn.queries[1]
    for field in (
        "effective_purchase_lead_days",
        "purchase_lead_status",
        "arrival_inventory_support_days",
        "arrival_inventory_qty",
        "lead_time_demand_qty",
        "lead_time_stockout_flag",
        "lead_time_stockout_days",
    ):
        self.assertIn(field, sql)


def test_serialize_item_exposes_purchase_lead_time_details_and_keeps_negative_values(self):
    service = ReplenishmentDataService.__new__(ReplenishmentDataService)

    item = service._serialize_item({
        "cur_date": None,
        "daily_avg_sales": 6.6,
        "inventory_support_days": 7.4,
        "effective_purchase_lead_days": 10,
        "purchase_lead_status": "defaulted",
        "arrival_inventory_support_days": -2.6,
        "arrival_inventory_qty": -17.16,
        "lead_time_demand_qty": 66,
        "lead_time_stockout_flag": 1,
        "lead_time_stockout_days": 2.6,
    })

    self.assertEqual(10, item["effective_purchase_lead_days"])
    self.assertEqual(-2.6, item["arrival_inventory_support_days"])
    self.assertEqual(-17.16, item["arrival_inventory_qty"])
    self.assertEqual(66, item["lead_time_demand_qty"])
    self.assertEqual(1, item["lead_time_stockout_flag"])
    self.assertEqual(2.6, item["lead_time_stockout_days"])
    self.assertEqual("defaulted", item["purchase_lead_status"])
```

- [ ] **Step 2: 运行测试并确认因字段缺失而失败**

Run:

```powershell
pytest tests/test_replenishment_data.py -k "purchase_lead_time_detail" -v
```

Expected: FAIL；SQL 不包含交期字段，或序列化结果缺少对应键。

- [ ] **Step 3: 在列表查询中读取现有字段**

在 `_items()` 的 SELECT 中紧跟 `inventory_support_days` 增加：

```sql
effective_purchase_lead_days,
purchase_lead_status,
arrival_inventory_support_days,
arrival_inventory_qty,
lead_time_demand_qty,
lead_time_stockout_flag,
lead_time_stockout_days,
```

- [ ] **Step 4: 最小化扩展序列化结果**

在 `_serialize_item()` 中增加：

```python
"effective_purchase_lead_days": (
    round(to_float(row.get("effective_purchase_lead_days")), 2)
    if row.get("effective_purchase_lead_days") is not None else None
),
"purchase_lead_status": row.get("purchase_lead_status") or "",
"arrival_inventory_support_days": (
    round(to_float(row.get("arrival_inventory_support_days")), 2)
    if row.get("arrival_inventory_support_days") is not None else None
),
"arrival_inventory_qty": (
    round(to_float(row.get("arrival_inventory_qty")), 2)
    if row.get("arrival_inventory_qty") is not None else None
),
"lead_time_demand_qty": (
    round(to_float(row.get("lead_time_demand_qty")), 2)
    if row.get("lead_time_demand_qty") is not None else None
),
"lead_time_stockout_flag": to_int(row.get("lead_time_stockout_flag")),
"lead_time_stockout_days": (
    round(to_float(row.get("lead_time_stockout_days")), 2)
    if row.get("lead_time_stockout_days") is not None else None
),
```

不要改变现有 `support_days` 键和 `support_days -> inventory_support_days` 排序映射。

- [ ] **Step 5: 运行后端测试并确认通过**

Run:

```powershell
pytest tests/test_replenishment_data.py -k "purchase_lead_time_detail or serialize_item_exposes_follow_status or items_query_selects_and_sorts_listing_tags" -v
```

Expected: PASS。

- [ ] **Step 6: 提交后端契约改动**

```powershell
git add app/services/replenishment_data.py tests/test_replenishment_data.py
git commit -m "补充补货列表交期明细字段"
```

### Task 2: 实现“库存 / 交期”复合单元格和详情弹层

**Files:**
- Modify: `app/static/js/replenishment.js:187-343,850-920,1116-1158`
- Modify: `app/static/css/styles.css`（在现有 `#replenishmentAgGrid` 专属样式旁新增）
- Modify: `app/templates/base.html`
- Modify: `app/templates/replenishment.html`
- Test: `tests/test_replenishment_frontend.py`

**Interfaces:**
- Consumes: Task 1 产生的 API 字段。
- Produces: `renderLeadTimeCell(params) -> string`、`toggleLeadTimePopover(button, key)`、`closeLeadTimePopover()`；`window.replenishmentLeadTimeRowMap` 保存当前表格行映射。

- [ ] **Step 1: 写前端结构失败测试**

在 `tests/test_replenishment_frontend.py` 增加：

```python
def test_replenishment_grid_compacts_lead_time_metrics_into_one_column():
    script = (ROOT / "app/static/js/replenishment.js").read_text(encoding="utf-8")
    styles = (ROOT / "app/static/css/styles.css").read_text(encoding="utf-8")

    assert "function renderLeadTimeCell(params)" in script
    assert 'headerName: "库存 / 交期"' in script
    assert 'field: "support_days"' in script
    assert "cellRenderer: renderLeadTimeCell" in script
    assert 'field: "effective_purchase_lead_days"' not in script[script.index("columnDefs:", script.index("function renderTable")):script.index("]", script.index("columnDefs:", script.index("function renderTable")))]
    assert "lead_time_demand_qty" in script
    assert "arrival_inventory_qty" in script
    assert "lead_time_stockout_days" in script
    assert "purchase_lead_status" in script
    assert ".replenishment-lead-time-cell" in styles
    assert ".lead-time-risk.safe" in styles
    assert ".lead-time-risk.danger" in styles


def test_replenishment_lead_time_cell_opens_document_level_detail_popover():
    script = (ROOT / "app/static/js/replenishment.js").read_text(encoding="utf-8")

    assert 'event.target.closest("[data-lead-time-key]")' in script
    assert "toggleLeadTimePopover" in script
    assert "replenishmentLeadTimeRowMap" in script
    assert "lead-time-popover" in script
    assert "closeLeadTimePopover" in script
```

同时将已有静态资源版本断言更新为新的版本标识，例如 `20260804leadtime1`。

- [ ] **Step 2: 运行测试并确认因复合单元格尚未实现而失败**

Run:

```powershell
pytest tests/test_replenishment_frontend.py -k "lead_time or cache_busting" -v
```

Expected: FAIL；缺少 `renderLeadTimeCell`、弹层和样式。

- [ ] **Step 3: 为表格行建立交期明细映射**

在 `renderTable(payload)` 创建 AG Grid 前：

```javascript
closeLeadTimePopover();
window.replenishmentLeadTimeRowMap = {};
rows.forEach(function (row, index) {
  row._lead_time_key = "lead-time-" + index;
  window.replenishmentLeadTimeRowMap[row._lead_time_key] = row;
});
```

- [ ] **Step 4: 用一个复合列替换数字列**

把原来的：

```javascript
numberColumn(text.supportDays, "support_days", 118, 2)
```

替换为：

```javascript
{
  headerName: "库存 / 交期",
  field: "support_days",
  width: 176,
  minWidth: 166,
  maxWidth: 196,
  type: "numericColumn",
  sort: colSort("support_days"),
  cellRenderer: renderLeadTimeCell
}
```

将表格 `rowHeight` 从 58 调整到 62，保证两行信息不拥挤。

- [ ] **Step 5: 实现正常、断货和无法计算三种文案**

新增 `renderLeadTimeCell(params)`：

```javascript
function renderLeadTimeCell(params) {
  var row = params.data || {};
  var supportDays = row.support_days;
  var leadDays = row.effective_purchase_lead_days;
  var arrivalDays = row.arrival_inventory_support_days;
  var calculable = Number(row.daily_sales || 0) > 0 && supportDays !== null && supportDays !== undefined;
  var riskClass = !calculable ? "neutral" : Number(row.lead_time_stockout_flag || 0) === 1 ? "danger" : "safe";
  var riskText = !calculable
    ? "无法计算"
    : riskClass === "danger"
      ? "预计断货" + formatNumber(row.lead_time_stockout_days, 2) + "天"
      : "安全";
  var arrivalText = arrivalDays === null || arrivalDays === undefined ? "-" : formatNumber(arrivalDays, 2) + "天";
  return [
    '<button type="button" class="replenishment-lead-time-cell" data-lead-time-key="' + app.escapeHtml(row._lead_time_key || "") + '">',
    '<span class="lead-time-primary"><strong>' + (calculable ? formatNumber(supportDays, 2) + "天" : "-") + '</strong><i class="lead-time-risk ' + riskClass + '">' + app.escapeHtml(riskText) + '</i></span>',
    '<small>交期' + (leadDays === null || leadDays === undefined ? "-" : formatNumber(leadDays, 0) + "天") + ' → 到货<span class="' + (Number(arrivalDays) < 0 ? "is-negative" : "") + '">' + arrivalText + '</span></small>',
    '</button>'
  ].join("");
}
```

- [ ] **Step 6: 沿用现有弹层模式显示完整交期指标**

参照 `marginPricePopover` 的事件委托、定位和关闭逻辑，实现：

```javascript
var leadTimePopover = null;

function toggleLeadTimePopover(button, key) {
  var row = window.replenishmentLeadTimeRowMap ? window.replenishmentLeadTimeRowMap[key] : null;
  closeLeadTimePopover();
  if (!row) return;
  leadTimePopover = document.createElement("div");
  leadTimePopover.className = "lead-time-popover";
  leadTimePopover.innerHTML = [
    '<b>交期影响明细</b>',
    '<dl>',
    '<div><dt>采购交期</dt><dd>' + formatNumber(row.effective_purchase_lead_days, 0) + '天</dd></div>',
    '<div><dt>到货时支撑</dt><dd>' + formatNumber(row.arrival_inventory_support_days, 2) + '天</dd></div>',
    '<div><dt>交期预计消耗</dt><dd>' + formatNumber(row.lead_time_demand_qty, 2) + '件</dd></div>',
    '<div><dt>到货预计库存</dt><dd>' + formatNumber(row.arrival_inventory_qty, 2) + '件</dd></div>',
    '<div><dt>预计断货天数</dt><dd>' + formatNumber(row.lead_time_stockout_days, 2) + '天</dd></div>',
    '<div><dt>交期状态</dt><dd>' + app.escapeHtml(row.purchase_lead_status || "-") + '</dd></div>',
    '</dl>'
  ].join("");
  document.body.appendChild(leadTimePopover);
  positionLeadTimePopover(button);
}
```

document 捕获阶段点击 `[data-lead-time-key]` 时调用弹层；点击弹层外部、重新渲染表格时关闭。定位逻辑复用现有“贴近按钮并避免超出视口”的算法，但不要重构无关的毛利价弹层。

- [ ] **Step 7: 添加局部样式并更新缓存版本**

样式限定在 `#replenishmentAgGrid` 和 `.lead-time-popover`：

```css
#replenishmentAgGrid .replenishment-lead-time-cell { display:grid; width:100%; gap:3px; padding:0; border:0; background:transparent; color:inherit; text-align:left; cursor:pointer; }
#replenishmentAgGrid .lead-time-primary { display:flex; align-items:center; justify-content:space-between; gap:6px; }
#replenishmentAgGrid .replenishment-lead-time-cell small { color:#6b7f95; font-size:10px; white-space:nowrap; }
#replenishmentAgGrid .lead-time-risk { padding:2px 6px; border-radius:999px; font-size:10px; font-style:normal; font-weight:800; }
#replenishmentAgGrid .lead-time-risk.safe { color:#087557; background:#e9f8f1; }
#replenishmentAgGrid .lead-time-risk.danger,
#replenishmentAgGrid .is-negative { color:#b42318; }
#replenishmentAgGrid .lead-time-risk.danger { background:#feeceb; }
#replenishmentAgGrid .lead-time-risk.neutral { color:#607086; background:#eef2f7; }
.lead-time-popover { position:fixed; z-index:1200; width:270px; padding:14px; border:1px solid #d7e3ef; border-radius:12px; background:#fff; box-shadow:0 14px 38px rgba(20,45,75,.18); }
.lead-time-popover dl { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:10px 0 0; }
```

将 `base.html` 的 `styles.css` 和 `replenishment.html` 的 `replenishment.js` 版本标识更新为 `20260804leadtime1`。

- [ ] **Step 8: 运行前端契约测试并确认通过**

Run:

```powershell
pytest tests/test_replenishment_frontend.py -v
```

Expected: PASS。

- [ ] **Step 9: 提交前端展示改动**

```powershell
git add app/static/js/replenishment.js app/static/css/styles.css app/templates/base.html app/templates/replenishment.html tests/test_replenishment_frontend.py
git commit -m "紧凑展示补货交期和库存风险"
```

### Task 3: 回归测试和 8002 页面验收

**Files:**
- Verify only: `app/services/replenishment_data.py`
- Verify only: `app/static/js/replenishment.js`
- Verify only: `app/static/css/styles.css`

**Interfaces:**
- Consumes: Task 1 的列表 API 字段和 Task 2 的复合单元格。
- Produces: 通过自动化测试、API 实际数据和浏览器截图验证的可交付页面。

- [ ] **Step 1: 运行补货相关测试**

```powershell
pytest tests/test_replenishment_data.py tests/test_replenishment_frontend.py tests/test_replenishment_moq_frontend.py tests/test_replenishment_update.py -q
```

Expected: 全部 PASS，且无 warning/error。

- [ ] **Step 2: 运行完整测试集**

```powershell
pytest -q
```

Expected: 全部 PASS；基线为 601 个测试，新增测试后总数应高于 601。

- [ ] **Step 3: 检查测试服务和 API 实际字段**

确认 `http://127.0.0.1:8002/replenishment` 可访问；调用补货 API，并从正常 SKU 与交期内断货 SKU 中各抽一条，核对：

```text
support_days
effective_purchase_lead_days
arrival_inventory_support_days
lead_time_demand_qty
arrival_inventory_qty
lead_time_stockout_flag
lead_time_stockout_days
purchase_lead_status
```

Expected: API 数值与 `etl_datasync_replenishment_test.dashboard_pur_plan_replenish_data` 对应行一致，负值未被改为 0。

- [ ] **Step 4: 使用 Playwright 进行页面验收**

打开 `http://127.0.0.1:8002/replenishment`，检查：

1. 表头显示“库存 / 交期”，不存在五个新增独立交期列。
2. 单元格两行内容清晰，无裁切或与相邻列重叠。
3. 安全 SKU 显示绿色“安全”。
4. 风险 SKU 显示红色“预计断货 N 天”和负数到货支撑。
5. 点击单元格弹出六项交期明细，点击外部关闭。
6. 点击该列表头后，请求仍发送 `sort_field=support_days`。
7. 在常见桌面宽度下检查横向滚动，没有因本次改动增加多列。

保存验收截图到测试工作区临时目录，不提交截图。

- [ ] **Step 5: 检查导出结构未新增组合列**

调用现有补货导出接口，确认不存在名为“库存 / 交期”的导出列；原始交期字段仍按 `REPLENISHMENT_COLUMN_LABELS` 导出。

- [ ] **Step 6: 最终检查工作区和提交历史**

```powershell
git diff --check
git status --short
git log -5 --oneline
```

Expected: `git diff --check` 无输出；没有未提交的实现文件；最近提交分别包含后端字段和前端展示改动。
