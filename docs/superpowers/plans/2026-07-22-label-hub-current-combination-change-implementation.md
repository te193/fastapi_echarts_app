# 标签看板当前组合变化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用现有两日组合流转能力替换“今日重点变化”，直接说明当前筛选组合昨天到今天的数量、进出和简略原因。

**Architecture:** 删除前端对 `/api/label-hub/highlights` 的依赖，重点区域改为异步请求已有 `/api/label-hub/changes`。服务端补充面向组合的原因摘要，前端渲染组合条件、两日对账、进入/离开来源和原因，并继续复用现有变化明细抽屉。

**Tech Stack:** FastAPI、Python、原生 JavaScript、HTML/CSS、pytest。

## Global Constraints

- 当前看板首屏主数据不得被变化请求阻塞。
- 昨日与今日分别应用相同公共筛选和完整组合条件。
- 不再展示“恶化 / 改善 / 突增”或自动拼接未选择的标签条件。
- 原因只做可验证的简略归类；证据不足时显示“标签事实变化”，不输出确定性业务归因。
- 不修改现有标签卡片、联动面板和变化明细抽屉的筛选行为。

---

### Task 1: 固化组合变化响应口径

**Files:**
- Modify: `app/services/label_hub_change_data.py`
- Test: `tests/test_label_hub_changes.py`

**Interfaces:**
- Consumes: `LabelHubChangeDataService.get_changes(**filters)`。
- Produces: 响应新增 `combination_summary`，包含 `condition_labels`、`previous`、`current`、`added`、`removed`、`net`、`entry_summary`、`exit_summary`、`reason_summary`。

- [ ] **Step 1: Write the failing test**

```python
def test_changes_return_current_combination_summary():
    result = service.get_changes(conditions="1:104;3:301", metric_period="30d")
    summary = result["combination_summary"]
    assert summary["previous"] + summary["added"] - summary["removed"] == summary["current"]
    assert summary["condition_labels"] == ["问题产品", "正常在售"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_label_hub_changes.py -q`
Expected: FAIL because `combination_summary` is absent.

- [ ] **Step 3: Implement the response summary**

在已经计算完成的 `current_set`、`previous_set`、`added`、`removed`、`layer_transitions` 和 `reason_distribution` 上组装摘要，不重复拉取远端数据。进入和离开来源取同一父标签流转；没有当前层时退化为标签事实新增、消失或其他条件变化。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_label_hub_changes.py -q`
Expected: PASS.

### Task 2: 用组合变化替换重点变化区域

**Files:**
- Modify: `app/templates/label_hub.html`
- Modify: `app/static/js/label_hub.js`
- Modify: `app/static/css/styles.css`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: `/api/label-hub/changes` 的 `combination_summary` 和现有 `scope`、`summary`、`layer_transitions`。
- Produces: 页面“当前组合变化”区和“查看变化明细”入口。

- [ ] **Step 1: Write the failing frontend contract test**

```python
def test_current_combination_change_replaces_daily_highlights():
    js = Path("app/static/js/label_hub.js").read_text(encoding="utf-8")
    html = Path("app/templates/label_hub.html").read_text(encoding="utf-8")
    assert "/api/label-hub/highlights" not in js
    assert "当前组合变化" in html
    assert "今日重点变化" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_label_hub_frontend.py -q`
Expected: FAIL because the page still requests the highlights endpoint.

- [ ] **Step 3: Implement the compact combination view**

渲染内容固定为：当前组合条件；`上次 + 进入 - 离开 = 今日`；净变化；进入来源；离开去向；简略原因；“查看变化明细”。没有已选标签时显示“请先选择一个或多个标签条件”，不自动推荐其他组合。

- [ ] **Step 4: Preserve asynchronous loading and drawer reuse**

页面主接口完成后独立请求 `/api/label-hub/changes`。按钮继续调用已有变化明细抽屉；失败只显示变化区域错误态，不影响主看板。

- [ ] **Step 5: Run frontend tests**

Run: `pytest tests/test_label_hub_frontend.py tests/test_label_hub_api.py -q`
Expected: PASS.

### Task 3: 清理旧重点变化服务并验证

**Files:**
- Modify: `app/main.py`
- Delete: `app/services/label_hub_highlight_data.py`
- Delete: `tests/test_label_hub_highlights.py`

**Interfaces:**
- Removes: `GET /api/label-hub/highlights`。
- Retains: `GET /api/label-hub/changes` 和所有既有标签看板接口。

- [ ] **Step 1: Remove the unused route and service imports**

删除 highlights 路由、服务实例和专用测试，确保页面与测试代码无残余调用。

- [ ] **Step 2: Run focused tests**

Run: `pytest tests/test_label_hub_changes.py tests/test_label_hub_frontend.py tests/test_label_hub_api.py -q`
Expected: PASS.

- [ ] **Step 3: Run the complete suite**

Run: `pytest -q`
Expected: all tests pass.
