# 国家排名筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在标签看板国家明细中增加基于 `ranking` 的固定档位多选筛选和排名展示列。

**Architecture:** 国家指标查询在统计窗口结束日返回国家级 `ranking`；统一明细服务负责档位校验、国家视图过滤和不可用状态处理；前端沿用现有多选控件、激活条件标签与服务端分页流程。经营单元视图只保留筛选状态，不应用排名条件。

**Tech Stack:** FastAPI、Pydantic、Python 服务层、原生 JavaScript、SlimSelect、pytest/unittest。

## Global Constraints

- 筛选名称固定为“排名”，底层字段固定为 `ranking`。
- 档位固定为 `top10`、`11_20`、`21_50`、`51_100`、`gt100`、`missing`。
- 仅国家明细视图应用排名筛选；经营单元视图保留但不生效。
- 不新增数据库表或 ETL。
- 所有测试使用后台隐藏进程运行。

---

### Task 1: 国家指标返回 ranking

**Files:**
- Modify: `app/services/country_label_hub_data.py`
- Test: `tests/test_country_label_hub_data.py`

**Interfaces:**
- Consumes: `dashboard_product_performance_daily.ranking`
- Produces: `get_country_detail_base_rows(...).rows[*].ranking: int | None`

- [ ] **Step 1: 写失败测试**

在国家明细指标测试数据中加入 `ranking: 18`，断言输出国家行保留该字段；同时断言指标 SQL 包含统计窗口结束日排名表达式。

- [ ] **Step 2: 后台运行目标测试并确认失败**

Run: `python -m pytest tests/test_country_label_hub_data.py -q`
Expected: FAIL，国家行缺少 `ranking` 或 SQL 未选择排名。

- [ ] **Step 3: 最小实现**

在日表和年度回退表聚合 SQL 中增加：

```sql
max(case when dt_date = %(period_end)s and ranking > 0 then ranking end) as ranking
```

年度表对应使用 `start_date` 与原始 `rank` 字段。保持 `None` 表示暂无排名。

- [ ] **Step 4: 运行目标测试**

Run: `python -m pytest tests/test_country_label_hub_data.py -q`
Expected: PASS。

### Task 2: 明细接口校验并筛选排名档位

**Files:**
- Modify: `app/main.py`
- Modify: `app/services/label_hub_detail_data.py`
- Test: `tests/test_label_hub_detail_data.py`
- Test: `tests/test_label_hub_api.py`

**Interfaces:**
- Consumes: `ranking_bands: list[str]`
- Produces: `applied_filters.ranking_bands` 与按国家排名过滤后的分页结果

- [ ] **Step 1: 写失败测试**

覆盖边界：

```python
rows = [
    {"country": "A", "ranking": 10},
    {"country": "B", "ranking": 11},
    {"country": "C", "ranking": 20},
    {"country": "D", "ranking": 21},
    {"country": "E", "ranking": 50},
    {"country": "F", "ranking": 51},
    {"country": "G", "ranking": 100},
    {"country": "H", "ranking": 101},
    {"country": "I", "ranking": None},
]
```

断言多选 `["11_20", "51_100"]` 返回 B、C、F、G；经营单元视图忽略但回显；无效代码返回 400；指标不可用时选择排名返回明确错误。

- [ ] **Step 2: 后台运行目标测试并确认失败**

Run: `python -m pytest tests/test_label_hub_detail_data.py tests/test_label_hub_api.py -q`
Expected: FAIL，接口模型或筛选规则尚不存在。

- [ ] **Step 3: 最小实现**

在 `LabelHubDetailRequest` 增加：

```python
ranking_bands: list[str] = Field(default_factory=list)
```

服务层增加合法集合及匹配函数：

```python
RANKING_BANDS = {"top10", "11_20", "21_50", "51_100", "gt100", "missing"}
```

仅 `detail_view == "country"` 时匹配档位；空值、0、负数命中 `missing`。将 `ranking` 加入国家排序白名单，将 `ranking_bands` 加入指标型筛选、明细过滤激活判断与 `applied_filters`。

- [ ] **Step 4: 运行目标测试**

Run: `python -m pytest tests/test_label_hub_detail_data.py tests/test_label_hub_api.py -q`
Expected: PASS。

### Task 3: 前端排名多选和国家排名列

**Files:**
- Modify: `app/templates/label_hub.html`
- Modify: `app/static/js/label_hub.js`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: `ranking_bands` 与响应行 `ranking`
- Produces: “排名”多选、激活条件标签、国家表格“排名”列

- [ ] **Step 1: 写失败契约测试**

断言模板包含 `labelHubDetailRankingBands` 和六个选项；JS 状态、请求、清空、回填、激活标签、更多筛选计数均包含 `ranking_bands`；国家列包含 `ranking`，经营单元列不包含。

- [ ] **Step 2: 后台运行目标测试并确认失败**

Run: `python -m pytest tests/test_label_hub_frontend.py -q`
Expected: FAIL，排名控件和字段契约不存在。

- [ ] **Step 3: 最小实现**

在更多筛选区增加“排名”多选，选项文案为“前10、11–20、21–50、51–100、100名后、暂无排名”。将其接入 SlimSelect 生命周期和明细请求；经营单元视图显示已保留状态。国家综合/经营字段预设增加 `ranking` 数值列，无值显示“暂无”。

- [ ] **Step 4: 运行前端契约测试**

Run: `python -m pytest tests/test_label_hub_frontend.py -q`
Expected: PASS。

- [ ] **Step 5: 全量验证**

Run: `python -m pytest -q`
Expected: 所有测试通过。

Run: `git diff --check`
Expected: 无空白错误。

- [ ] **Step 6: 重启 8001 并验证真实接口**

在国家视图选择 `11–20`，确认响应仅包含 `ranking` 11 至 20 的国家行；切回经营单元视图确认条件保留但结果不受影响。
