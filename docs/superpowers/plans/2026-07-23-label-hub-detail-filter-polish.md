# 标签看板明细筛选区视觉优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将标签看板明细筛选区改造成效果图中的横向紧凑筛选工具栏，隐藏常驻多选列表并保留全部筛选能力。

**Architecture:** 保持现有 `detailState` 和 `/api/label-hub/details` 请求契约不变，只重构模板结构、SlimSelect 初始化、已选条件摘要和响应式样式。核心筛选常驻，高级筛选通过折叠容器显示。

**Tech Stack:** Jinja2、原生 JavaScript、SlimSelect、现有 CSS、pytest 静态前端契约测试。

## Global Constraints

- 不修改后端筛选字段、数据口径或表格下钻。
- 默认不展示原生 `select[multiple]` 长列表。
- 核心工具栏在桌面端保持一至两行，小屏自然换行。
- 测试与浏览器验证均后台静默运行。
- 保留当前工作区已有未提交修改。

---

### Task 1: 紧凑筛选结构与交互

**Files:**
- Modify: `app/templates/label_hub.html`
- Modify: `app/static/js/label_hub.js`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: 现有 `detailState`、`collectDetailFilters()`、`clearDetailFilters()`、`renderDetails()`。
- Produces: `toggleDetailAdvancedFilters()`、`renderDetailActiveFilters()`、`initDetailFilterSelects()`。

- [ ] **Step 1: 写失败的前端契约测试**

```python
def test_detail_filters_use_compact_toolbar_and_collapsed_advanced_panel():
    assert 'id="labelHubDetailAdvanced" hidden' in template
    assert 'id="labelHubDetailMore"' in template
    assert "function renderDetailActiveFilters()" in script
    assert "function initDetailFilterSelects()" in script
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_label_hub_frontend.py::test_detail_filters_use_compact_toolbar_and_collapsed_advanced_panel -q`

Expected: FAIL，模板尚无折叠高级筛选结构。

- [ ] **Step 3: 重构模板和 JavaScript**

将批量编码改为紧凑输入，将问题、国家类别、店铺、国家放在核心工具栏；把标签、销售角色、趋势、日销段、毛利段移动到 `labelHubDetailAdvanced`。使用现有 SlimSelect 初始化多选控件，并在应用、清空、视图切换后调用 `renderDetailActiveFilters()`。

- [ ] **Step 4: 运行目标测试与 JS 语法检查**

Run: `node --check app/static/js/label_hub.js`

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_label_hub_frontend.py -q`

Expected: PASS。

### Task 2: 视觉样式与响应式验收

**Files:**
- Modify: `app/static/css/styles.css`
- Modify: `app/templates/label_hub.html`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: Task 1 的核心工具栏、高级筛选区、条件标签区。
- Produces: `.label-hub-detail-toolbar`、`.label-hub-detail-advanced`、`.label-hub-detail-active-filters` 响应式样式。

- [ ] **Step 1: 写失败的样式契约测试**

```python
assert ".label-hub-detail-toolbar" in styles
assert ".label-hub-detail-active-filters" in styles
assert "select[multiple] { min-height: 64px" not in detail_styles
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_label_hub_frontend.py::test_detail_filters_match_compact_reference_visual_language -q`

Expected: FAIL，紧凑样式尚未实现。

- [ ] **Step 3: 实现效果图样式**

统一控件高度为 36px，使用白底、细边框、8px 圆角和蓝色激活态；工具栏使用自适应网格，高级区使用浅灰蓝背景；已选条件使用可扫描标签；移除原生长列表高度和滚动条呈现。

- [ ] **Step 4: 静默验证**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_label_hub_frontend.py -q`

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Run: `git diff --check`

Expected: 全部通过且无新增空白错误。
