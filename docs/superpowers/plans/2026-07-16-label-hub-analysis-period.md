# 标签看板远端联动周期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为三个远端标签联动卡片增加互相独立的标签周期，并保证分布与点击后的联动筛选使用同一周期。

**Architecture:** `analysis_parent_ids` 与新增的 `analysis_periods` 按卡片位置一一对应。服务端将周期映射应用到远端 breakdown、标签条件和矩阵；前端负责 URL 恢复、维度切换回退和双选择器展示。

**Tech Stack:** FastAPI、Python、原生 JavaScript、CSS、pytest。

## Global Constraints

- 远端只读现有标签详情表和标签事实表，不增加数据源。
- 顶部 `label_period` 只控制当前分析父标签。
- 顶部 `metric_period` 继续控制本地经营快照。
- 未传 `analysis_periods` 时保持旧行为，全部按 `all` 处理。
- 不创建新分支，不触碰标签看板以外的业务文件。

---

### Task 1: 服务端周期映射与筛选

**Files:**
- Modify: `app/services/label_hub_data.py`
- Modify: `app/main.py`
- Test: `tests/test_label_hub_data.py`
- Test: `tests/test_label_hub_api.py`

**Interfaces:**
- Consumes: `analysis_parent_ids: str`、`analysis_periods: str`。
- Produces: 远端 breakdown 的 `label_period: str`、`periods: list[str]`。

- [ ] **Step 1: 写失败测试**

构造同一 MSKU 在销售角色 `7d` 与 `30d` 命中不同子标签的事实，调用：

```python
payload = service.build_payload(
    analysis_parent_ids=[1, 8, 9],
    analysis_periods=["7d", "all", "all"],
    conditions={1: {101}},
    parent_label_id=3,
    label_period="all",
    **base_args,
)
```

断言销售角色 breakdown 只统计 `7d` 标签、最终行也按 `7d` 条件过滤，并断言 API 将 `analysis_periods` 转发给服务。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_label_hub_data.py tests/test_label_hub_api.py -q`

Expected: 因 `analysis_periods` 尚未进入方法签名或响应而失败。

- [ ] **Step 3: 实现最小服务端逻辑**

在 `build_payload` 中加入：

```python
requested_ids = [int(item) for item in (analysis_parent_ids or []) if int(item) in category_by_id]
requested_periods = [str(item or "all") for item in (analysis_periods or [])]
analysis_period_by_parent = {
    parent_id: requested_periods[index] if index < len(requested_periods) else "all"
    for index, parent_id in enumerate(requested_ids)
}
```

`scoped_parent_children` 对非当前父标签读取 `analysis_period_by_parent`；远端 breakdown 返回规范化后的周期和可用周期。`get_payload` 将管道字符串拆成列表，`app/main.py` 增加并转发查询参数。

- [ ] **Step 4: 运行后端测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_label_hub_data.py tests/test_label_hub_api.py -q`

Expected: 全部通过。

### Task 2: 前端独立周期状态与卡片控件

**Files:**
- Modify: `app/static/js/label_hub.js`
- Modify: `app/static/css/styles.css`
- Modify: `app/templates/label_hub.html`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: breakdown 的 `parent_id`、`label_period`、`periods`。
- Produces: URL 参数 `analysis_periods=7d|all|30d`。

- [ ] **Step 1: 写失败的前端契约测试**

断言脚本包含 `analysis_periods` 状态、`analysisPeriods()`、`data-analysis-period-slot`、请求参数转发，以及远端卡片双选择器容器 `.label-hub-card-selectors`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_label_hub_frontend.py -q`

Expected: 缺少周期状态和控件而失败。

- [ ] **Step 3: 实现状态和交互**

新增：

```javascript
analysis_periods: query.get("analysis_periods") || ""
```

`analysisPeriods()` 始终返回三个周期；维度切换时对应槽位回退 `all`，周期选择时只更新对应槽位。`renderPanel` 在远端卡片头部输出“切换维度”和“标签周期”两个选择器，请求和 URL 同步携带 `analysis_periods`。

- [ ] **Step 4: 调整样式并更新资源版本**

使用两列紧凑控件布局；窄屏允许换行，不改变卡片主体高度策略。更新 `label_hub.js` 查询版本，防止浏览器沿用旧缓存。

- [ ] **Step 5: 运行前端测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_label_hub_frontend.py -q`

Expected: 全部通过。

### Task 3: 综合验证

**Files:**
- Verify only: label hub related files and test suite.

- [ ] **Step 1: 运行完整测试**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: 零失败。

- [ ] **Step 2: 后台重启 8001 并验证接口**

请求带 `analysis_parent_ids=1|8|9&analysis_periods=7d|all|all` 的 `/api/label-hub`，断言状态 200、销售角色 breakdown 的 `label_period` 为 `7d`。

- [ ] **Step 3: 检查变更范围**

Run: `git status -sb` 与 `git diff --check`

Expected: 只包含本功能相关文件，无空白错误。
