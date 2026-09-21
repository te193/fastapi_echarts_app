# Operating Stockout Rate Right Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有断货率摘要锚点从底部左侧移到右侧详细计数之前，同时保持全部视觉样式不变。

**Architecture:** 保留现有 HTML 顺序“断货率锚点 → 详细计数”，仅将 footer 布局从两端分散改为整组靠右。窄屏继续允许整组换行，不拆散断货率锚点。

**Tech Stack:** CSS、pytest、Playwright CLI。

## Global Constraints

- 不修改 JavaScript 输出、接口、计算、筛选、口径浮层和卡片交互。
- 断货率锚点的蓝色竖线、20px 百分比、颜色与间距保持不变。
- 整组靠右，断货率锚点紧挨详细计数之前。
- 窄屏允许自然换行，但组内顺序不变。
- 验证不操作用户当前页面。

---

### Task 1: Right-align the combined summary

**Files:**
- Modify: `tests/test_label_hub_frontend.py`
- Modify: `app/static/css/styles.css`

**Interfaces:**
- Consumes: `.label-hub-operating-stockout-rate` containing `.label-hub-operating-stockout-anchor` followed by `.label-hub-operating-stockout-details`.
- Produces: one right-aligned flex group with the same child order and styling.

- [x] **Step 1: Write the failing CSS contract test**

Add assertions to the operating stockout frontend test:

```python
assert "justify-content: flex-end;" in styles
assert "flex-wrap: wrap;" in styles
```

Remove the previous assertion requiring `justify-content: space-between;`.

- [x] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
pytest tests/test_label_hub_frontend.py -k "operating_stockout" -q
```

Expected: FAIL because the footer still uses `space-between`.

- [x] **Step 3: Implement the minimal CSS change**

Update `.label-hub-operating-stockout-rate`:

```css
display: flex;
flex-wrap: wrap;
justify-content: flex-end;
```

Remove the narrow-screen `flex-direction: column`; retain right alignment and allow wrapping. Do not alter anchor or detail typography.

- [x] **Step 4: Verify focused, frontend, and syntax checks**

Run:

```powershell
pytest tests/test_label_hub_frontend.py -k "operating_stockout" -q
pytest tests/test_label_hub_frontend.py -q
node --check app/static/js/label_hub.js
```

Expected: all commands exit 0.

- [x] **Step 5: Verify the real layout in an isolated browser**

On a background Uvicorn port other than 8001, verify:

- footer computed `justify-content` is `flex-end`;
- anchor left coordinate is smaller than detail left coordinate;
- the horizontal gap between anchor and details remains compact;
- 700px viewport wraps without reversing order;
- popover still opens and browser console has zero errors.

- [x] **Step 6: Run full tests and commit**

Run:

```powershell
pytest -q
git diff --check
git add app/static/css/styles.css tests/test_label_hub_frontend.py
git commit -m "调整断货率汇总区位置"
```

Expected: all tests pass and commit succeeds.
