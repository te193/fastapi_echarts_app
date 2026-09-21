# Operating Stockout Rate Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将运营状态底部的“在营断货率”从右侧脚注改为方案 C 的左侧摘要锚点，提高断货率的可发现性。

**Architecture:** 保留现有 `operating_stockout_rate` payload、口径浮层和事件处理，仅调整 `renderOperatingStockoutRate()` 输出的内部结构与对应 CSS。左侧锚点负责突出断货率，右侧继续承载可核对的分子、分母、返场再断货和口径入口。

**Tech Stack:** 原生 JavaScript、CSS、pytest、Playwright CLI。

## Global Constraints

- 不修改断货率计算、接口字段、筛选联动和状态卡片交互。
- 左侧使用短蓝色竖线、“在营断货率”小号文字及较大深蓝百分比。
- 右侧详细计数保持次级灰蓝文字。
- 不使用胶囊、整行底色或独立指标卡。
- 窄屏下允许右侧说明换行，左侧断货率保持完整视觉单元。
- 验证使用独立无头浏览器，不操作用户当前页面。

---

### Task 1: Convert the footer to a left summary anchor

**Files:**
- Modify: `tests/test_label_hub_frontend.py`
- Modify: `app/static/js/label_hub.js`
- Modify: `app/static/css/styles.css`

**Interfaces:**
- Consumes: `payload.operating_stockout_rate` with `rate`, `effective_stockout_count`, `operating_count`, and `return_restockout_count`.
- Produces: `.label-hub-operating-stockout-anchor` on the left and `.label-hub-operating-stockout-details` on the right; existing `[data-operating-stockout-formula]` behavior remains unchanged.

- [x] **Step 1: Write the failing frontend contract test**

Extend `test_operating_stockout_rate_renders_quiet_footer_and_formula_popover` with:

```python
assert 'class="label-hub-operating-stockout-anchor"' in script
assert 'class="label-hub-operating-stockout-details"' in script
assert ".label-hub-operating-stockout-anchor::before" in styles
assert "font-size: 20px;" in styles
assert "justify-content: space-between;" in styles
```

Remove any assertion that requires the old summary wrapper to own the emphasized percentage.

- [x] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
pytest tests/test_label_hub_frontend.py -k "operating_stockout" -q
```

Expected: FAIL because the anchor and details classes do not yet exist.

- [x] **Step 3: Implement the new semantic structure**

Change the footer markup in `renderOperatingStockoutRate()` to:

```html
<footer class="label-hub-operating-stockout-rate">
  <div class="label-hub-operating-stockout-anchor">
    <span>在营断货率</span>
    <strong>30.4%</strong>
  </div>
  <div class="label-hub-operating-stockout-details">
    <span>有效断货 413 / 在营 1,357</span>
    <i>·</i>
    <span>返场再断货 24</span>
    <i>·</i>
    <button data-operating-stockout-formula>查看口径</button>
  </div>
  <aside id="labelHubOperatingStockoutPopover"
         class="label-hub-operating-stockout-popover"
         data-operating-stockout-popover
         role="note"
         hidden>
    <strong>在营断货率口径</strong>
    <p><b>有效断货</b> = 断货中 − 返场期再次断货</p>
    <p><b>在营记录</b> = 正常在售 + 测款扶持 + 返厂品 + 断货中</p>
    <small>清仓中和停售不计入在营记录；返场再断货保留在分母中，仅从断货分子扣除。</small>
  </aside>
</footer>
```

Keep all dynamic values, escaping, ARIA attributes and popover markup unchanged.

- [x] **Step 4: Implement the scheme C styling**

Update CSS so:

```css
.label-hub-operating-stockout-rate {
  align-items: center;
  display: flex;
  justify-content: space-between;
}

.label-hub-operating-stockout-anchor::before {
  background: var(--brand);
  border-radius: 2px;
  content: "";
  height: 28px;
  width: 3px;
}

.label-hub-operating-stockout-anchor strong {
  color: #075bb8;
  font-size: 20px;
}
```

Move the existing flex-wrap/detail button styles to `.label-hub-operating-stockout-details`. Add a narrow-screen rule that changes the footer to wrapped alignment without introducing a background fill.

- [x] **Step 5: Run focused and frontend tests**

Run:

```powershell
pytest tests/test_label_hub_frontend.py -k "operating_stockout" -q
pytest tests/test_label_hub_frontend.py -q
node --check app/static/js/label_hub.js
```

Expected: all commands exit 0.

- [x] **Step 6: Commit the UI slice**

```powershell
git add app/static/js/label_hub.js app/static/css/styles.css tests/test_label_hub_frontend.py
git commit -m "突出显示在营断货率"
```

---

### Task 2: Regression and isolated visual verification

**Files:**
- Verify only.

**Interfaces:**
- Consumes: the rendered label-hub page on an isolated port.
- Produces: evidence that the anchor is visible, the popover still works, and no console errors occur.

- [x] **Step 1: Run the full relevant regression suite**

Run:

```powershell
pytest tests/test_label_hub_data.py tests/test_label_hub_api.py tests/test_label_hub_frontend.py -q
```

Expected: all tests pass.

- [x] **Step 2: Verify in an isolated background server**

Start Uvicorn on a free port other than 8001 and use Playwright CLI to confirm:

- “在营断货率” and the percentage appear as one left-aligned anchor.
- The percentage is visually larger than the detail text.
- Detailed counts remain right aligned.
- “查看口径” opens the existing popover and `Escape` closes it.
- Browser console contains zero errors.

- [x] **Step 3: Review repository state**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: no whitespace errors and no unintended tracked files.
