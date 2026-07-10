# 补货履约汇总页实施计划

> **执行说明：** 本文是给后续开发使用的实施计划。实现时按任务逐步执行，每个任务完成后做验证。本文先用于业务口径审核，未审核通过前不改功能代码。

**目标：** 新增一个按“截止日期”汇总的补货履约页面，用来查看截至某天，哪些 MSKU 需要补货、当前分层是什么、有没有采购、采购是否在途或到本地仓、是否创建 FBA 货件、FBA 是否在途、预计还有几天到货。

**总体方案：** 保留现有“按补货日期 + 追踪窗口 7/14/30 天”的追踪页面不动。新增一套旁路汇总表、接口和页面视图，专门回答“截至某天，这个 MSKU 的补货链路整体走到哪一步了”。汇总 ETL 只读现有补货结果表和现有追踪快照，不重新从采购/FBA 原始单据归因。

**技术范围：** FastAPI、MySQL、本地 ETL、现有服务层模式、原生 JavaScript、AG Grid、pytest。

---

## 一、先审核的业务口径

### 1. 汇总粒度

汇总页一行代表一个产品链路：

```text
国家类别 + 店铺 + MSKU
```

同一个 MSKU 如果在多天补货结果里反复出现，汇总页不重复展示多行，而是合并成一行。

### 2. 日期口径

每一行保留这些日期字段：

- `首次进入补货日期`：这个 MSKU 在截止日期之前，第一次进入紧急补货、建议补货、计划补货的日期。
- `最近补货日期`：这个 MSKU 在截止日期之前，最近一次还出现在补货结果里的日期。
- `当前补货分层`：取最近补货日期那天的分层。
- `最近补货建议数`：取最近补货日期那天的建议补货数量，不做多天累计。
- `出现天数`：这个 MSKU 在补货结果里出现过多少天，用来识别反复缺货。
- `历史出现分层`：这个 MSKU 在截止日期之前曾经进入过哪些补货层级。比如同一个 MSKU 可能先进入建议补货，后面升级为紧急补货，历史出现分层需要同时保留这两个层级。

这样处理后，不需要强行判断“25 号采购到底是对应 22 号补货，还是 23 号补货”。系统只表达：这个 MSKU 从首次进入补货后，截止当前是否已经发生采购或发货动作。

### 3. 采购归因口径

用 `首次进入补货日期` 作为本次和历史的分界线。

采购状态分为：

- `本次补货后采购`：采购计划创建时间 >= 首次进入补货日期，且 <= 截止日期。
- `历史采购在途`：采购动作早于首次进入补货日期，但截止日期仍有采购在途信号。
- `本次+历史采购`：既有本次补货后的采购，也有历史采购在途。
- `未采购`：没有本次采购计划，也没有历史采购在途。

注意：这里不把采购强行归到某一天补货建议，只归到“首次进入补货后的这条补货链路”。

### 4. FBA 归因口径

FBA 也用 `首次进入补货日期` 作为分界线。

FBA 状态分为：

- `本次FBA在途`：FBA 计划或发货单发生在首次进入补货日期之后，且截止日期仍属于在途或未完全收货。
- `历史FBA在途`：FBA 计划或发货单发生在首次进入补货日期之前，但截止日期仍在途。
- `本次+历史FBA在途`：两种都有。
- `未建FBA`：没有 FBA 计划或发货单信号。

### 5. 预计到货口径

- 只看 FBA 在途，不看采购在途。
- 如果同一个 MSKU 同时有本次 FBA 在途和历史 FBA 在途，取最近的预计到货日期。
- 如果预计到货日期还没到，展示 `X 天后到货`。
- 如果预计到货日期已经过了但仍未收货，展示 `已过预计到货 X 天`。
- 如果没有预计到货日期，展示 `-`。

### 6. 销售角色分类口径

销售角色分类用于查看这些补货 MSKU 里，明星产品、潜力产品、瘦狗产品、问题产品分别有多少。

- 分类周期支持动态选择：7 天、14 天、30 天、90 天。
- 分类字段跟随选择周期变化，不固定使用 30 天。
- 分类统计既要支持全局汇总，也要支持按历史出现分层拆分。
- 如果某个 MSKU 在选择周期下没有分类，归到 `未分类`。

### 7. 历史分层流转口径

新增一块“历史分层流转概览”，用于回答：

```text
历史上进入过紧急/建议/计划补货的 MSKU，各自后续走到了什么状态？
```

注意：这里按“曾经进入过某个分层”统计，不按“当前分层”统计。

一个 MSKU 如果历史上同时进入过多个分层，会分别计入对应分层的历史统计。例如：

- 6 月 20 日进入建议补货
- 6 月 23 日进入紧急补货

那么它在“建议补货历史出现 MSKU”和“紧急补货历史出现 MSKU”里都会被计入。

每个历史分层建议展示：

- 历史出现 MSKU 数
- 当前仍在该分层 MSKU 数
- 后续已采购 MSKU 数
- 后续未采购 MSKU 数
- 后续本次FBA在途 MSKU 数
- 后续历史FBA在途 MSKU 数
- 后续已收货 MSKU 数
- 销售角色分布：明星、潜力、瘦狗、问题、未分类

这块用来发现问题，例如：

- 历史出现过紧急补货的 MSKU 里，还有多少一直未采购。
- 建议补货里哪些已经进入采购但还没建 FBA。
- 计划补货里哪些大多只是历史 FBA 在途，并不是本次补货推动。

---

## 二、页面建议

### 1. 页面名称

建议叫：

```text
补货履约汇总
```

和现有页面区分：

- 现有页面：补货分层采购追踪，偏“某天补货之后的 7/14/30 天追踪”。
- 新页面：补货履约汇总，偏“截至某天整体链路状态”。

### 2. 页面固定口径说明

页面顶部需要固定展示本次和历史的口径说明，不只放在问号提示里。

建议文案：

```text
本次：首次进入补货后产生的采购/FBA动作；历史：首次进入补货前已有，但截止日仍在途或仍影响库存的动作。
```

这段说明用于减少误解，例如“未采购为什么还有历史在途”“历史 FBA 是否代表本次补货已经推进”等。

### 3. 筛选区

建议包含：

- 截止日期
- 补货需求批次：最近 7 天新增补货、最近 14 天新增补货、最近 30 天新增补货、最近 90 天新增补货、全部历史补货
- 销售角色分类周期：7 天、14 天、30 天、90 天
- 当前补货分层：全部、紧急补货、建议补货、计划补货
- 采购状态：全部、本次补货后采购、历史采购在途、本次+历史采购、未采购
- FBA 状态：全部、本次FBA在途、历史FBA在途、本次+历史FBA在途、未建FBA
- 异常类型：全部、紧急补货未采购、多次出现未采购、已采购未建FBA、已建FBA未在途、FBA预计到货已过期、无预计到货时间、只有历史链路无本次推进
- 国家类别
- 店铺
- 关键词：MSKU / SKU / 店铺

异常类型只做事实筛选，不做“下一步动作”建议。

### 4. 顶部指标卡

顶部卡片建议分两层展示，避免所有指标堆在一起。

第一层：总体状态卡。

- 需要补货 MSKU
- 未采购 MSKU
- 已采购未建FBA MSKU
- FBA在途 MSKU
- 预计 7 天内到货 MSKU
- 预计到货异常 MSKU

第二层：历史分层流转卡。

- 历史出现过紧急补货
- 历史出现过建议补货
- 历史出现过计划补货

如果页面空间不够，第一版可以优先做总体状态卡和历史分层三张卡，其他指标放入筛选或表格。

### 5. 历史分层流转概览

建议在顶部指标卡下面增加一组按历史分层展示的卡片，三块分别是：

- 历史出现过紧急补货
- 历史出现过建议补货
- 历史出现过计划补货

每块卡片展示：

- 历史出现 MSKU
- 当前仍在本层
- 后续已采购 / 未采购
- 本次FBA在途 / 历史FBA在途 / 已收货
- 销售角色分布

展示方式建议：

```text
历史出现 82
当前仍在本层 58
已采购 36 / 未采购 46
本次FBA 13 / 历史FBA 7 / 已收货 2
明星 3 / 潜力 8 / 瘦狗 54 / 问题 17 / 未分类 0
```

销售角色分布跟随筛选区的“销售角色分类周期”变化。

点击卡片里的状态或销售角色标签时，可以联动明细表筛选。例如点击“未采购 46”，明细表只看历史进入过该层且未采购的 MSKU。

### 6. 反复补货标签

明细表和历史分层卡片里建议增加事实标签，帮助识别长期未解决的产品。

建议标签：

- `反复出现 X 天`：出现天数达到阈值，例如大于等于 3 天。
- `连续出现 X 天`：最近连续多天都在补货池。
- `曾升级为紧急`：历史出现分层包含紧急补货，但首次进入不是紧急补货。
- `当前仍紧急`：当前补货分层是紧急补货。

这些标签只描述事实，不提供处理建议。

### 7. 最新状态展示口径

最新状态建议更业务化，但不写“下一步动作”。

状态建议：

- `未采购`
- `本次已采购`
- `历史采购在途`
- `本次+历史采购`
- `已采购未建FBA`
- `本次FBA在途`
- `历史FBA在途`
- `本次+历史FBA在途`
- `已收货`
- `预计到货异常`

### 8. ETA 风险展示

最近预计到货需要突出风险。

展示建议：

- `3天后到货`
- `今天预计到货`
- `已过预计到货2天`
- `无预计到货`

其中 `已过预计到货` 和 `无预计到货` 建议使用风险色。

### 9. 默认排序

明细表默认不筛掉数据，但按风险优先排序。

建议排序优先级：

1. 紧急补货未采购
2. 多次出现未采购
3. 已采购未建FBA
4. FBA预计到货已过期
5. 无预计到货时间但有FBA在途
6. 本次FBA在途
7. 历史FBA在途
8. 已收货

### 10. 明细表字段

建议字段：

- MSKU / SKU
- 店铺
- 国家
- 当前补货分层
- 首次进入补货日期
- 最近补货日期
- 出现天数
- 反复补货标签
- 最近补货建议数
- 采购状态
- 采购计划单数
- 采购计划数量
- 本次采购在途数
- 历史采购在途数
- 本地仓数量
- FBA 状态
- 本次FBA在途数
- 历史FBA在途数
- 已收货数
- 最近预计到货
- 最新状态
- 操作：查看链路明细

### 11. 来源明细

主表只展示汇总字段，采购计划单、FBA 计划单、发货单、创建时间、发货时间、预计到货、数量、本次/历史归因等信息放到“查看链路明细”里。

来源明细默认折叠，避免主表字段过多。

### 12. 本期暂不做

本期不做“下一步动作”列，不展示类似“联系采购”“催建 FBA”“查物流”这种建议动作。

原因：

- 这类字段带有主观业务决策。
- 当前阶段先把事实状态、本次/历史归因、异常筛选展示清楚。
- 后续如果运营确认规则，再单独增加建议动作。

---

## 三、汇总 ETL 数据来源

第一版只复用现有表。

主数据来源：

```text
dashboard_pur_plan_replenish_data
```

用途：

- 哪些 MSKU 进入过补货池。
- 首次进入补货日期。
- 最近补货日期。
- 当前补货分层。
- 历史出现分层。
- 最近补货建议数。
- 销售角色分类。

状态数据来源：

```text
dashboard_replenishment_tracking_snapshot
```

用途：

- 采购状态。
- 采购计划数量。
- 本次/历史采购在途。
- FBA 状态。
- 本次/历史 FBA 在途。
- 已收货。
- 最近预计到货。
- 最新状态。

明细数据来源：

```text
dashboard_replenishment_tracking_detail
```

用途：

- 查看链路明细时复用现有采购计划、FBA 计划、发货单明细。

第一版不重新读取这些远端原始表：

```text
dwd_datasync.lx_purchase_purchase_plan
dwd_datasync.lx_fba_shipment_plan
dwd_datasync.lx_inbound_shipment_detail
dwd_datasync.lx_inbound_shipment_detail_ShangPinLieBiao
```

原因：现有追踪 ETL 已经处理过本次/历史、FBA、ETA 等归因，汇总 ETL 重复做一遍成本高且容易口径分叉。

---

## 四、建议新增的数据表

新增汇总表：

```text
dashboard_replenishment_tracking_summary
```

建议字段：

```sql
cutoff_date date not null comment '截止日期',
country_category varchar(64) not null comment '国家类别',
seller_name_new varchar(255) not null comment '店铺',
seller_sku_adj varchar(255) not null comment 'MSKU',
sku varchar(255) null comment 'SKU',
first_replenishment_date date not null comment '首次进入补货日期',
latest_replenishment_date date not null comment '最近补货日期',
appearance_days int not null default 0 comment '补货结果中出现天数',
current_replenishment_level varchar(32) null comment '当前补货分层',
current_replenishment_level_sort int null comment '分层排序',
historical_replenishment_levels varchar(255) null comment '历史出现过的补货分层，逗号分隔',
latest_replenishment_qty decimal(18,4) not null default 0 comment '最近补货建议数',
latest_replenishment_value decimal(18,4) not null default 0 comment '最近补货货值',
product_category varchar(32) null comment '按选择周期计算的销售角色分类',
purchase_status varchar(32) not null default 'none' comment '采购状态：current/historical/mixed/none',
current_purchase_plan_count int not null default 0 comment '本次补货后采购计划单数',
current_purchase_plan_qty decimal(18,4) not null default 0 comment '本次补货后采购计划数量',
current_purchase_shipping_qty decimal(18,4) not null default 0 comment '本次采购在途数量',
historical_purchase_shipping_qty decimal(18,4) not null default 0 comment '历史采购在途数量',
local_stock_qty decimal(18,4) not null default 0 comment '本地仓数量',
fba_status varchar(32) not null default 'none' comment 'FBA状态：current/historical/mixed/none',
current_fba_inbound_qty decimal(18,4) not null default 0 comment '本次FBA在途数量',
historical_fba_inbound_qty decimal(18,4) not null default 0 comment '历史FBA在途数量',
received_qty decimal(18,4) not null default 0 comment '已收货数量',
nearest_fba_eta_date date null comment '最近预计到货日期',
nearest_fba_eta_days int null comment '距离截止日期预计到货天数',
latest_status varchar(255) null comment '最新状态',
created_at timestamp not null default current_timestamp,
updated_at timestamp not null default current_timestamp on update current_timestamp,
primary key (cutoff_date, country_category, seller_name_new, seller_sku_adj)
```

为支持“历史分层流转概览”，建议再新增一张轻量明细表：

```text
dashboard_replenishment_tracking_summary_level_history
```

一行代表一个 MSKU 曾经进入过的一个补货分层：

```sql
cutoff_date date not null comment '截止日期',
country_category varchar(64) not null comment '国家类别',
seller_name_new varchar(255) not null comment '店铺',
seller_sku_adj varchar(255) not null comment 'MSKU',
historical_replenishment_level varchar(32) not null comment '历史出现分层',
first_level_date date not null comment '首次进入该分层日期',
latest_level_date date not null comment '最近进入该分层日期',
level_appearance_days int not null default 0 comment '该分层出现天数',
is_current_level tinyint not null default 0 comment '截止日期最近分层是否仍为该层',
primary key (cutoff_date, country_category, seller_name_new, seller_sku_adj, historical_replenishment_level)
```

这张表只解决“曾经进入过哪个分层”的问题，采购/FBA/销售角色状态仍从汇总主表关联，避免重复存太多状态字段。

---

## 五、实施任务

### 任务 1：建立汇总 ETL 和表结构

**涉及文件：**

- 新增：`etl/replenishment_tracking_summary_update.py`
- 新增：`tests/test_replenishment_tracking_summary.py`

**要做的事：**

- 创建 `dashboard_replenishment_tracking_summary` 表。
- 创建 `dashboard_replenishment_tracking_summary_level_history` 表。
- 支持按单个截止日期刷新。
- 支持后续扩展成滚动刷新最近 N 天。

**验证方式：**

```bash
python -m py_compile etl/replenishment_tracking_summary_update.py
```

预期：无报错。

---

### 任务 2：实现汇总计算逻辑

**涉及文件：**

- 修改：`etl/replenishment_tracking_summary_update.py`

**核心计算步骤：**

1. 从补货结果表取截止日期之前的紧急、建议、计划三层 MSKU。
2. 按 `国家 + 店铺 + MSKU` 聚合出首次进入补货日期、最近补货日期、出现天数。
3. 回连最近补货日期当天的数据，取当前分层、最近补货建议数、最近补货货值。
4. 计算历史出现分层，写入 `dashboard_replenishment_tracking_summary_level_history`。
5. 按选择的销售角色分类周期，计算明星、潜力、瘦狗、问题、未分类。
6. 左连接最近补货日期对应的 `dashboard_replenishment_tracking_snapshot`。
7. 从现有追踪快照读取采购/FBA/ETA/最新状态。
8. 生成汇总状态和顶部指标。

**状态判断优先级建议：**

```text
本次+历史FBA在途
本次FBA在途
历史FBA在途
本次+历史采购
本次补货后采购
历史采购在途
未采购
```

**验证方式：**

```bash
python -m etl.replenishment_tracking_summary_update --cutoff-date 2026-06-26
```

命令输出建议包含：

```text
cutoff_date=2026-06-26
summary_rows=...
level_history_rows=...
purchase_status={...}
fba_status={...}
product_category={...}
```

---

### 任务 3：新增后端查询服务和接口

**涉及文件：**

- 新增：`app/services/replenishment_tracking_summary_data.py`
- 修改：`app/main.py`
- 新增：`tests/test_replenishment_tracking_summary.py`

**接口建议：**

页面路由：

```text
GET /replenishment-tracking-summary
```

数据接口：

```text
GET /api/replenishment-tracking-summary
```

接口参数：

- `cutoff_date`
- `entry_batch_days`
- `level`
- `purchase_status`
- `fba_status`
- `category_period_days`
- `history_level`
- `history_flow_status`
- `product_category`
- `exception_type`
- `site`
- `store`
- `keyword`
- `page`
- `page_size`
- `sort_field`
- `sort_dir`

接口返回：

- 顶部指标卡
- 分层汇总
- 历史分层流转概览
- 销售角色分类分布
- 异常类型统计
- 明细列表
- 分页信息
- 可选筛选项

**验证方式：**

```bash
python -m pytest tests/test_replenishment_tracking_summary.py -q
python -m py_compile app/main.py app/services/replenishment_tracking_summary_data.py
```

预期：测试通过，编译无报错。

---

### 任务 4：新增前端汇总页面

**涉及文件：**

- 新增：`app/templates/replenishment_tracking_summary.html`
- 新增：`app/static/js/replenishment_tracking_summary.js`
- 修改：`app/static/css/styles.css`

**页面内容：**

- 筛选区
- 顶部指标卡
- 历史分层流转概览
- 分层汇总区
- 明细表
- 状态说明问号提示

**表格关键列：**

```javascript
[
  { headerName: 'MSKU / SKU', field: 'msku' },
  { headerName: '店铺', field: 'store' },
  { headerName: '国家', field: 'country' },
  { headerName: '当前分层', field: 'level' },
  { headerName: '历史出现分层', field: 'historical_replenishment_levels' },
  { headerName: '销售角色', field: 'product_category' },
  { headerName: '反复补货标签', field: 'replenishment_tags' },
  { headerName: '首次进入补货', field: 'first_replenishment_date' },
  { headerName: '最近补货日期', field: 'latest_replenishment_date' },
  { headerName: '出现天数', field: 'appearance_days' },
  { headerName: '最近补货建议数', field: 'latest_replenishment_qty' },
  { headerName: '采购状态', field: 'purchase_status_label' },
  { headerName: '采购计划单数', field: 'current_purchase_plan_count' },
  { headerName: '采购计划数量', field: 'current_purchase_plan_qty' },
  { headerName: '本次采购在途', field: 'current_purchase_shipping_qty' },
  { headerName: '历史采购在途', field: 'historical_purchase_shipping_qty' },
  { headerName: 'FBA状态', field: 'fba_status_label' },
  { headerName: '本次FBA在途', field: 'current_fba_inbound_qty' },
  { headerName: '历史FBA在途', field: 'historical_fba_inbound_qty' },
  { headerName: '最近预计到货', field: 'nearest_fba_eta_text' },
  { headerName: '最新状态', field: 'latest_status' }
]
```

**说明提示文案：**

- 采购状态：`本次=首次进入补货后创建采购；历史=首次进入补货前已有采购在途；本次+历史=两类都存在。`
- FBA状态：`本次=首次进入补货后创建或发出的 FBA 在途；历史=首次进入补货前创建或发出但截止日仍在途。`
- 最近预计到货：`只看 FBA 在途，多个货件取最近一个预计到货日期。`
- 历史出现分层：`统计截止日期前曾经进入过的补货分层，一个 MSKU 可能同时出现在多个历史分层统计里。`
- 销售角色：`根据筛选区选择的分类周期动态计算，支持 7 / 14 / 30 / 90 天。`
- 异常类型：`只用于事实筛选，不代表系统给出的处理建议。`

---

### 任务 5：增加明细下钻

**涉及文件：**

- 修改：`app/static/js/replenishment_tracking_summary.js`
- 修改：`app/services/replenishment_tracking_summary_data.py`

**建议行为：**

明细表增加 `查看链路明细`。

点击后可以复用现有追踪明细，默认传：

```text
snapshot_date = 最近补货日期
tracking_window_days = 30
msku = 当前 MSKU
store = 当前店铺
site = 当前国家类别
```

明细顶部增加说明：

```text
该明细展示最近补货日期对应的采购、FBA 和货件记录。汇总页的本次/历史判断以首次进入补货日期为分界。
```

---

### 任务 6：刷新数据并做业务校验

**涉及文件：**

- 修改：`docs/补货分层采购发货追踪规划.md`

**刷新命令：**

```bash
python -m etl.replenishment_tracking_update --rolling-days 30
python -m etl.replenishment_tracking_summary_update --cutoff-date 2026-06-26
```

**校验 SQL：**

按分层看数量：

```sql
select current_replenishment_level, count(*) as msku_count
from dashboard_replenishment_tracking_summary
where cutoff_date = '2026-06-26'
group by current_replenishment_level
order by msku_count desc;
```

按历史出现分层看后续状态：

```sql
select h.historical_replenishment_level,
       count(*) as msku_count,
       sum(case when s.purchase_status <> 'none' then 1 else 0 end) as purchased_count,
       sum(case when s.purchase_status = 'none' then 1 else 0 end) as not_purchased_count,
       sum(case when s.fba_status in ('current', 'mixed') then 1 else 0 end) as current_fba_count,
       sum(case when s.fba_status in ('historical', 'mixed') then 1 else 0 end) as historical_fba_count
from dashboard_replenishment_tracking_summary_level_history h
join dashboard_replenishment_tracking_summary s
  on s.cutoff_date = h.cutoff_date
 and s.country_category = h.country_category
 and s.seller_name_new = h.seller_name_new
 and s.seller_sku_adj = h.seller_sku_adj
where h.cutoff_date = '2026-06-26'
group by h.historical_replenishment_level
order by msku_count desc;
```

看采购和 FBA 状态分布：

```sql
select purchase_status, fba_status, count(*) as msku_count
from dashboard_replenishment_tracking_summary
where cutoff_date = '2026-06-26'
group by purchase_status, fba_status
order by msku_count desc;
```

抽查历史链路：

```sql
select seller_sku_adj,
       seller_name_new,
       country_category,
       first_replenishment_date,
       latest_replenishment_date,
       purchase_status,
       fba_status,
       historical_purchase_shipping_qty,
       historical_fba_inbound_qty
from dashboard_replenishment_tracking_summary
where cutoff_date = '2026-06-26'
  and (purchase_status = 'historical' or fba_status = 'historical')
limit 50;
```

---

### 任务 7：最终回归

**自动检查：**

```bash
python -m pytest tests/test_replenishment_tracking.py tests/test_replenishment_tracking_summary.py -q
python -m py_compile app/main.py app/services/replenishment_tracking_data.py app/services/replenishment_tracking_summary_data.py etl/replenishment_tracking_update.py etl/replenishment_tracking_summary_update.py
node --check app/static/js/replenishment_tracking.js
node --check app/static/js/replenishment_tracking_summary.js
node --check app/static/js/replenishment.js
```

**人工检查：**

- 原补货看板正常。
- 原 `/replenishment-tracking` 页面正常。
- 新 `/replenishment-tracking-summary` 页面正常。
- 筛选、清空、排序、分页正常。
- 本次和历史不会混淆。
- 最近预计到货只来自 FBA 在途。
- 现有日追踪结果不因为新汇总页被改动。

---

## 六、审核清单

请重点确认这些口径：

- [ ] 汇总粒度是一行一个 `国家 + 店铺 + MSKU`。
- [ ] 本次和历史的分界线用 `首次进入补货日期`。
- [ ] 汇总 ETL 只读现有补货结果表和追踪快照，不改现有补货看板结果。
- [ ] 第一版不重新从采购/FBA 原始表归因。
- [ ] 当前分层取截止日期前最近一次补货记录。
- [ ] 补货建议数取最近一次，不做多天累计。
- [ ] 多天重复出现用 `出现天数` 表示，不重复展示多行。
- [ ] 采购不强行归属到某一天补货建议，只判断是否发生在首次进入补货之后。
- [ ] FBA 也按首次进入补货日期拆成本次和历史。
- [ ] 最近预计到货只看 FBA 在途。
- [ ] 新增“历史分层流转概览”，按曾经进入过的分层统计，不只看当前分层。
- [ ] 一个 MSKU 历史进入过多个分层时，可以同时计入多个历史分层统计。
- [ ] 销售角色分类周期支持 7 / 14 / 30 / 90 天动态切换。
- [ ] 页面顶部固定展示“本次/历史”口径说明。
- [ ] 保留异常类型筛选，但不做“下一步动作”建议。
- [ ] 明细表默认按风险优先排序，不默认隐藏全部数据。
- [ ] 增加反复补货标签，例如反复出现、连续出现、曾升级为紧急、当前仍紧急。
- [ ] ETA 风险需要突出展示，包含已过预计到货和无预计到货。
- [ ] 原有一天一天追踪页面不改，只新增汇总页。
