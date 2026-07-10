# 补货链路追踪汇总 V2 实施计划
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有“补货链路追踪汇总”页上实现完整供应链节点漏斗、节点抽屉和 MSKU 链路明细，不影响每日补货看板和每日追踪页。

**Architecture:** 新增一套汇总页专用链路节点 ETL 输出，汇总页 API 读取新节点字段，前端只改 `补货链路追踪汇总` tab。每日追踪页继续使用旧 ETL、旧 API、旧页面逻辑。

**Tech Stack:** Python ETL + PyMySQL + FastAPI service + 原生 JS + AG Grid + 现有 CSS。

---

## 范围边界

只允许改：

- `etl/replenishment_tracking_summary_update.py`
- `app/services/replenishment_tracking_summary_data.py`
- `app/static/js/replenishment_tracking_summary.js`
- `app/static/css/styles.css`
- `app/templates/replenishment.html`
- `tests/test_replenishment_tracking_summary.py`
- 必要时新增汇总页专用测试文件

不要改：

- `etl/replenishment_tracking_update.py`
- `app/services/replenishment_tracking_data.py`
- `app/static/js/replenishment_tracking.js`
- 每日追踪页模板和 API
- 每日补货看板既有计算逻辑

## 目标链路节点

汇总页展示这条链路：

```text
补货需求
-> 建采购计划
-> 采购单/供应商发货
-> 到本地仓
-> 质检通过
-> 建FBA计划
-> FBA出库/在途
-> FBA接收
-> FBA完成
```

节点口径：

- `补货需求`：历史进入过紧急/建议/计划补货的 MSKU。
- `建采购计划`：补货后匹配到采购计划 `plan_sn`。
- `采购单/供应商发货`：采购计划关联采购单，且采购单有物流商或物流单号。
- `到本地仓`：采购单关联收货单，且实际收货数量大于 0。
- `质检通过`：质检单良品数大于 0，且不良数为 0。
- `建FBA计划`：质检通过后匹配到 FBA 发货计划 `R...`，能归因到本次链路。
- `FBA出库/在途`：有真实 FBA 货件号或出库/货件明细。
- `FBA接收`：FBA 收货数量大于 0，或状态为 `RECEIVING/CLOSED`。
- `FBA完成`：状态为 `CLOSED`，或 `closed_time` 不为空。

## 页面设计

### 顶部断点卡

替换或扩展当前顶部卡片：

- `追踪MSKU`
- `未建采购计划`
- `供应商未发货`
- `采购在途未到仓`
- `到仓未质检通过`
- `质检通过未建FBA`
- `已建FBA未出库`
- `FBA在途未接收`
- `FBA已完成`

点击卡片设置 `summary_stage`，联动主表。

### 履约分层漏斗

保留三层：

- 紧急补货
- 建议补货
- 计划补货

每层展示：

```text
历史 N 个 · 当日 M 个
明星 / 潜力 / 瘦狗 / 问题
```

每层右侧展示节点漏斗。每个节点用 `当前节点数量 / 上一节点数量`，例如：

```text
建FBA 13/15
质检通过 15 · 未建 2
```

颜色：

- 绿色：当前节点数量等于上一节点数量。
- 黄色：当前节点数量小于上一节点数量。
- 红色：当前节点存在超时或异常。
- 灰色：上一节点为 0，当前节点不适用。

### 节点抽屉

点击任意层级的任意节点，右侧打开抽屉。

抽屉顶部展示：

- 补货层级
- 节点名称
- MSKU 数
- 断点原因分布
- 当前节点漏斗

抽屉表格列：

- `MSKU / SKU`
- `店铺`
- `国家`
- `补货日期`
- `销售角色`
- `建议补货数`
- `采购计划单号`
- `采购计划数量`
- `采购单号`
- `供应商发货状态`
- `物流商 / 物流单号`
- `收货单号`
- `收货数量`
- `质检单号`
- `良品 / 不良`
- `FBA计划单号`
- `FBA计划数量`
- `货件号`
- `已发 / 已收`
- `预计到货`
- `断点原因`

### 主明细表

主表增加或调整列：

- `当前层级`
- `MSKU / SKU`
- `店铺`
- `国家`
- `销售角色`
- `首次进入`
- `最近补货`
- `出现天数`
- `建议数`
- `链路进度`
- `当前节点`
- `断点原因`
- `采购计划数量`
- `采购在途数量`
- `到仓数量`
- `质检通过数量`
- `FBA计划数量`
- `FBA已发数量`
- `FBA已收数量`
- `预计到货`
- `订单号摘要`
- `查看明细`

链路进度显示：

```text
采 -> 单 -> 发 -> 仓 -> 检 -> 计 -> 出 -> 收 -> 完
```

## Task 1: 扩展汇总 ETL 输出字段

**Files:**

- Modify: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\etl\replenishment_tracking_summary_update.py`
- Test: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\tests\test_replenishment_tracking_summary.py`

- [ ] **Step 1: 给汇总表补链路节点字段**

在 `CREATE_SUMMARY_SQL` 和列补齐逻辑里增加字段：

```sql
purchase_plan_flag tinyint not null default 0 comment '是否已建采购计划',
purchase_plan_count int not null default 0 comment '采购计划单数',
purchase_plan_qty decimal(18,4) not null default 0 comment '采购计划数量',
purchase_order_flag tinyint not null default 0 comment '是否已生成采购单',
supplier_shipped_flag tinyint not null default 0 comment '供应商是否发货',
purchase_inbound_qty decimal(18,4) not null default 0 comment '采购在途数量',
local_received_flag tinyint not null default 0 comment '是否到本地仓',
local_received_qty decimal(18,4) not null default 0 comment '本地收货数量',
qc_flag tinyint not null default 0 comment '是否有质检',
qc_passed_flag tinyint not null default 0 comment '质检是否通过',
qc_good_qty decimal(18,4) not null default 0 comment '良品数量',
qc_bad_qty decimal(18,4) not null default 0 comment '不良数量',
fba_plan_flag tinyint not null default 0 comment '是否已建FBA计划',
fba_plan_count int not null default 0 comment 'FBA计划单数',
fba_plan_qty decimal(18,4) not null default 0 comment 'FBA计划数量',
fba_shipped_flag tinyint not null default 0 comment '是否FBA出库在途',
fba_shipped_qty decimal(18,4) not null default 0 comment 'FBA已发数量',
fba_receiving_flag tinyint not null default 0 comment 'FBA是否开始接收',
fba_received_qty decimal(18,4) not null default 0 comment 'FBA已收数量',
fba_closed_flag tinyint not null default 0 comment 'FBA是否完成',
current_node varchar(64) null comment '当前节点',
breakpoint_node varchar(64) null comment '断点节点',
breakpoint_reason varchar(255) null comment '断点原因',
order_sn_summary text null comment '订单号摘要'
```

- [ ] **Step 2: 先用现有追踪快照字段填充可用节点**

第一版不要强行接所有远端 DWD 表。先用当前本地可用表填：

```text
purchase_plan_flag      <- purchase_plan_count > 0
purchase_plan_count     <- purchase_plan_count
purchase_plan_qty       <- purchase_plan_total_qty 或 purchase_plan_qty
fba_plan_flag           <- fba_shipment_plan_msku_flag 或 fba_shipment_plan_qty > 0
fba_plan_qty            <- fba_shipment_plan_qty
fba_shipped_qty         <- current_fba_shipment_plan_qty + historical_fba_shipment_plan_qty
fba_received_qty        <- received_qty
```

缺采购单、收货单、质检链路的字段先填 0，并把断点原因写清楚：

```text
当前本地未同步采购单/收货/质检链路
```

- [ ] **Step 3: 写断点原因 CASE**

按顺序判断：

```sql
case
  when purchase_plan_flag = 0 then '未匹配到补货后的采购计划'
  when supplier_shipped_flag = 0 then '已建采购计划，但未确认供应商发货'
  when local_received_flag = 0 then '采购在途，但未确认到本地仓'
  when qc_passed_flag = 0 then '到仓后未确认质检通过'
  when fba_plan_flag = 0 then '质检通过后未创建FBA计划'
  when fba_shipped_flag = 0 then '已建FBA计划，但未确认出库在途'
  when fba_receiving_flag = 0 then 'FBA在途，未开始接收'
  when fba_closed_flag = 0 then 'FBA已接收，未确认完成'
  else '链路完成'
end
```

- [ ] **Step 4: 运行单日 ETL**

Run:

```powershell
python -m etl.replenishment_tracking_summary_update --cutoff-date 2026-06-29
```

Expected:

```text
[success] cutoff_date=2026-06-29 summary_rows=... level_history_rows=...
```

## Task 2: 扩展汇总 API 返回节点聚合

**Files:**

- Modify: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\app\services\replenishment_tracking_summary_data.py`
- Test: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\tests\test_replenishment_tracking_summary.py`

- [ ] **Step 1: `map_summary_row` 返回新字段**

返回字段包括：

```python
"purchase_plan_flag"
"purchase_plan_count"
"purchase_plan_qty"
"supplier_shipped_flag"
"purchase_inbound_qty"
"local_received_qty"
"qc_passed_flag"
"qc_good_qty"
"qc_bad_qty"
"fba_plan_flag"
"fba_plan_count"
"fba_plan_qty"
"fba_shipped_qty"
"fba_received_qty"
"current_node"
"breakpoint_node"
"breakpoint_reason"
"order_sn_summary"
```

- [ ] **Step 2: `_summary` 增加顶部断点卡指标**

SQL 聚合：

```sql
sum(case when purchase_plan_flag = 0 then 1 else 0 end) as no_purchase_plan_count,
sum(case when purchase_plan_flag = 1 and supplier_shipped_flag = 0 then 1 else 0 end) as supplier_not_shipped_count,
sum(case when supplier_shipped_flag = 1 and local_received_flag = 0 then 1 else 0 end) as inbound_not_received_count,
sum(case when local_received_flag = 1 and qc_passed_flag = 0 then 1 else 0 end) as qc_pending_count,
sum(case when qc_passed_flag = 1 and fba_plan_flag = 0 then 1 else 0 end) as no_fba_plan_count,
sum(case when fba_plan_flag = 1 and fba_shipped_flag = 0 then 1 else 0 end) as fba_not_shipped_count,
sum(case when fba_shipped_flag = 1 and fba_receiving_flag = 0 then 1 else 0 end) as fba_not_receiving_count,
sum(case when fba_closed_flag = 1 then 1 else 0 end) as fba_closed_count
```

- [ ] **Step 3: `_level_flow` 返回每层节点漏斗**

每层返回：

```python
"demand_count"
"purchase_plan_count"
"supplier_shipped_count"
"local_received_count"
"qc_passed_count"
"fba_plan_count"
"fba_shipped_count"
"fba_receiving_count"
"fba_closed_count"
```

- [ ] **Step 4: `_where` 支持节点筛选**

新增 `summary_stage` 值：

```text
no_purchase_plan
supplier_not_shipped
inbound_not_received
qc_pending
no_fba_plan
fba_not_shipped
fba_not_receiving
fba_closed
```

每个值对应 Task 2 Step 2 的同口径条件。

- [ ] **Step 5: 测试 API payload**

Run:

```powershell
python -m pytest tests\test_replenishment_tracking_summary.py -q
```

Expected:

```text
passed
```

## Task 3: 改汇总页分层漏斗

**Files:**

- Modify: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\app\static\js\replenishment_tracking_summary.js`
- Modify: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\app\static\css\styles.css`
- Modify: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\app\templates\replenishment.html`

- [ ] **Step 1: 顶部卡改为断点卡**

`renderCards` 改用：

```javascript
[
  ["追踪MSKU", summary.msku_count, "tone-0", "历史进入过补货范围", "all"],
  ["未建采购计划", summary.no_purchase_plan_count, "tone-2", "未匹配到补货后的采购计划", "no_purchase_plan"],
  ["供应商未发货", summary.supplier_not_shipped_count, "tone-2", "采购计划已建但未确认发货", "supplier_not_shipped"],
  ["采购在途未到仓", summary.inbound_not_received_count, "tone-2", "已发货但未确认本地收货", "inbound_not_received"],
  ["到仓未质检", summary.qc_pending_count, "tone-3", "到仓后未确认质检通过", "qc_pending"],
  ["质检通过未建FBA", summary.no_fba_plan_count, "tone-2", "可推进FBA计划", "no_fba_plan"],
  ["FBA未出库", summary.fba_not_shipped_count, "tone-2", "已建FBA计划但未出库", "fba_not_shipped"],
  ["FBA未接收", summary.fba_not_receiving_count, "tone-2", "FBA在途未接收", "fba_not_receiving"],
  ["FBA已完成", summary.fba_closed_count, "tone-1", "链路完成", "fba_closed"]
]
```

- [ ] **Step 2: 分层右侧改成完整节点漏斗**

节点顺序：

```javascript
[
  ["建采购", "purchase_plan_count", "demand_count", "no_purchase_plan"],
  ["供应商发货", "supplier_shipped_count", "purchase_plan_count", "supplier_not_shipped"],
  ["到本地仓", "local_received_count", "supplier_shipped_count", "inbound_not_received"],
  ["质检通过", "qc_passed_count", "local_received_count", "qc_pending"],
  ["建FBA", "fba_plan_count", "qc_passed_count", "no_fba_plan"],
  ["FBA出库", "fba_shipped_count", "fba_plan_count", "fba_not_shipped"],
  ["FBA接收", "fba_receiving_count", "fba_shipped_count", "fba_not_receiving"],
  ["完成", "fba_closed_count", "fba_receiving_count", "fba_closed"]
]
```

每个节点显示：

```text
当前数 / 上一节点数
上一节点 N · 未完成 M
```

- [ ] **Step 3: 节点点击联动主表**

点击节点设置：

```javascript
state.history_level = level;
state.summary_stage = node.stage;
state.product_category = "all";
state.page = 1;
render();
```

- [ ] **Step 4: 样式控制**

新增 CSS：

```css
.chain-node-flow {}
.chain-node-card.ok {}
.chain-node-card.warn {}
.chain-node-card.danger {}
.chain-node-card.muted {}
```

保持当前页面卡片风格，不引入新组件库。

- [ ] **Step 5: bump 静态版本**

修改 `app/templates/replenishment.html`：

```html
replenishment_tracking_summary.js?v=20260630chainv2
styles.css?v=20260630chainv2
```

- [ ] **Step 6: JS 检查**

Run:

```powershell
node --check app\static\js\replenishment_tracking_summary.js
```

Expected: no output.

## Task 4: 改主明细表

**Files:**

- Modify: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\app\static\js\replenishment_tracking_summary.js`

- [ ] **Step 1: 增加链路进度列**

新增列：

```javascript
{ headerName: "链路进度", field: "chain_progress", width: 180, cellRenderer: renderChainProgress }
```

`renderChainProgress(row)` 用小点展示：

```text
采 单 发 仓 检 计 出 收 完
```

- [ ] **Step 2: 增加当前节点和断点原因**

新增列：

```javascript
{ headerName: "当前节点", field: "current_node", width: 130 }
{ headerName: "断点原因", field: "breakpoint_reason", minWidth: 220 }
```

- [ ] **Step 3: 增加关键数量列**

新增列：

```javascript
numberColumn("采购计划数", "purchase_plan_qty", 112)
numberColumn("采购在途", "purchase_inbound_qty", 104)
numberColumn("到仓数", "local_received_qty", 104)
numberColumn("质检良品", "qc_good_qty", 104)
numberColumn("FBA计划数", "fba_plan_qty", 112)
numberColumn("FBA已发", "fba_shipped_qty", 104)
numberColumn("FBA已收", "fba_received_qty", 104)
```

- [ ] **Step 4: 增加订单号摘要**

新增列：

```javascript
{ headerName: "订单号摘要", field: "order_sn_summary", minWidth: 220 }
```

长文本用 tooltip，不展开撑乱表格。

## Task 5: 节点抽屉

**Files:**

- Modify: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\app\templates\replenishment.html`
- Modify: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\app\static\js\replenishment_tracking_summary.js`
- Modify: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\app\services\replenishment_tracking_summary_data.py`

- [ ] **Step 1: 复用现有明细抽屉结构**

不要新增第二套抽屉。复用 `summaryTrackingDetailDrawer`。

- [ ] **Step 2: 点击节点打开抽屉**

节点点击先筛主表；如果用户点击节点卡里的“查看明细”区域，再打开抽屉。

第一版可以直接点击节点打开抽屉，同时主表也筛选。

- [ ] **Step 3: 抽屉 API 参数**

复用汇总 API 参数：

```text
cutoff_date
entry_batch_days
history_level
summary_stage
category_period_days
site
store
keyword
```

返回当前筛选下最多 100 条节点明细。

- [ ] **Step 4: 抽屉表格列**

使用 AG Grid，列见“页面设计 / 节点抽屉”。

第一版如果明细表字段不全，缺字段显示 `-`，不要用错误字段替代。

## Task 6: 回归验证

**Files:**

- Test: `E:\Code\Python_code\日常测试使用\fastapi_echarts_app\tests\test_replenishment_tracking_summary.py`

- [ ] **Step 1: 后端测试**

Run:

```powershell
python -m pytest tests\test_replenishment_tracking_summary.py -q
```

Expected:

```text
passed
```

- [ ] **Step 2: 前端语法检查**

Run:

```powershell
node --check app\static\js\replenishment_tracking_summary.js
```

Expected: no output.

- [ ] **Step 3: 单日 ETL 刷新**

Run:

```powershell
python -m etl.replenishment_tracking_summary_update --cutoff-date 2026-06-29
```

Expected:

```text
[success]
```

- [ ] **Step 4: 启动或重启 8001**

Run:

```powershell
$conn = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force }
Start-Process -WindowStyle Hidden -FilePath "D:\Users\13957\anaconda3\python.exe" -ArgumentList @('-m','uvicorn','app.main:app','--host','0.0.0.0','--port','8001') -WorkingDirectory "E:\Code\Python_code\日常测试使用\fastapi_echarts_app"
```

- [ ] **Step 5: 页面人工验证**

打开：

```text
http://127.0.0.1:8001/replenishment
```

验证：

- 每日补货看板能正常打开。
- 补货链路追踪汇总能正常打开。
- 日期筛选联动汇总页。
- 层级标签联动表格。
- 销售角色标签顺序为明星、潜力、瘦狗、问题。
- 分层漏斗每个节点显示 `当前 / 上一层`。
- 点击节点能筛选主表。
- 抽屉能打开并展示节点明细。
- 每日追踪页未被影响。

## 后续暂不做

- 不做供应商维度分析。
- 不做物流时效评分。
- 不改每日追踪页面。
- 不做复杂图表，只做节点漏斗、抽屉和表格。
