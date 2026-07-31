# Country Diagnostics C2 Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用连续蓝色分组轨道和浅色父子层级优化国家站点诊断展开态，仅修改前端样式。

**Architecture:** 复用现有 `.expanded`、`.label-hub-diagnostic-role-row`、`.label-hub-diagnostic-child-row` 及 `data-diagnostic-country-detail` DOM 契约，通过 CSS 伪元素形成连续竖轨和子级连接线。国家记录占比沿用现有进度条节点，只修正国家角色表中的列选择器。

**Tech Stack:** CSS、pytest、Playwright CLI

## Global Constraints

- 仅修改 `app/static/css/styles.css` 和对应的静态契约测试。
- 不修改 Python、API、JavaScript、模板、业务文案或交互逻辑。
- 不新增四种角色专属颜色。
- 保留当前响应式列隐藏和横向滚动策略。
- 当前工作区按交接要求不提交、不推送。

---

### Task 1: 固定 C2 样式契约

**Files:**
- Modify: `tests/test_label_hub_frontend.py:768`

**Interfaces:**
- Consumes: 现有国家角色表 CSS 类和数据属性。
- Produces: 连续竖轨、连接线、分组结束边界及第 4 列占比条的静态测试契约。

- [ ] **Step 1: 写入失败测试**

在现有测试中增加以下断言：

```python
assert ".label-hub-diagnostic-role-row.expanded::before" in styles
assert ".label-hub-diagnostic-child-row::before" in styles
assert ".label-hub-diagnostic-child-row td:first-child::before" in styles
assert ".label-hub-diagnostic-child-row:has(+ .label-hub-diagnostic-role-row)" in styles
assert ".is-country-role-table td:nth-child(4) i" in styles
```

- [ ] **Step 2: 验证测试失败**

Run: `python -m pytest tests/test_label_hub_frontend.py::test_country_diagnostics_use_expandable_role_distribution_without_attention_rail -q`

Expected: FAIL，因为 C2 选择器尚不存在。

### Task 2: 实现 C2 连续分组样式

**Files:**
- Modify: `app/static/css/styles.css:8562-8604`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: `.expanded` 状态类、父行和子行现有 class。
- Produces: 纯 CSS 的展开父级、连续竖轨、子级连接线、末行边界、悬停和占比条样式。

- [ ] **Step 1: 实现最小 CSS**

使用伪元素绘制 4px 蓝色竖轨；父行使用低饱和浅蓝背景；子行使用近白浅蓝背景、名称缩进和短连接线；用 `:has(+ .label-hub-diagnostic-role-row)` 及 `:last-child` 标记分组末尾；为国家角色表第 4 列补齐进度条选择器。

- [ ] **Step 2: 验证聚焦测试通过**

Run: `python -m pytest tests/test_label_hub_frontend.py::test_country_diagnostics_use_expandable_role_distribution_without_attention_rail -q`

Expected: PASS。

### Task 3: 回归与视觉验证

**Files:**
- Verify: `app/static/css/styles.css`
- Verify: `output/playwright/`

**Interfaces:**
- Consumes: 已运行在 8001 端口的标签看板。
- Produces: 桌面及 768px 窄屏截图和无控制台错误的验证结果。

- [ ] **Step 1: 运行全量验证**

Run: `python -m pytest -q`

Expected: 全部通过。

Run: `git diff --check`

Expected: 无格式错误。

- [ ] **Step 2: 重启本地服务**

确认 8001 端口进程命令为当前项目的 `uvicorn app.main:app` 后，仅重启该进程。

- [ ] **Step 3: Playwright 视觉检查**

打开潜力产品、国家站点诊断、30d 页面；分别检查折叠态、展开“站点潜力”后的连续分组轨道，以及 768px 窄屏状态。

- [ ] **Step 4: 检查控制台**

Run: `npx --yes @playwright/cli@latest -s=labelhub console error`

Expected: 0 errors。
