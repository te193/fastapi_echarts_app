# 标签看板明细表点击交互 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 MSKU 可自由选择和一键复制，并将标签画像、国家画像改为显式入口，彻底移除整行误触。

**Architecture:** 保留现有 AG Grid 和抽屉加载函数，仅调整列渲染与 `onCellClicked` 事件分发。复制行为封装为独立前端函数，单元格按钮通过 `data-copy-msku` 触发；标签画像通过 `label_summary` 列触发，国家画像继续通过 `country_profile` 列触发。

**Tech Stack:** 原生 JavaScript、AG Grid、现有 CSS、pytest 前端契约测试。

## Global Constraints

- 不修改接口、数据库或统计口径。
- MSKU 维度与国家明细视图都取消整行点击。
- MSKU 文本必须可以拖选；复制按钮必须支持键盘操作。
- 标签画像与国家画像只通过各自显式入口打开。
- 测试使用后台隐藏进程执行。

---

### Task 1: 明细表显式操作入口

**Files:**
- Modify: `app/static/js/label_hub.js`
- Modify: `app/static/css/styles.css`
- Modify: `app/templates/label_hub.html`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: `openDrawer(row)`、`openCountryProfileDrawer(row)`、`app.escapeHtml(value)`。
- Produces: `renderMskuCell(params)`、`copyText(value)`、`copyMsku(button, value)`；`msku` 列输出 `data-copy-msku` 按钮，`label_summary` 列成为标签画像入口。

- [ ] **Step 1: 写失败的前端契约测试**

```python
def test_label_hub_table_uses_explicit_profile_and_copy_actions():
    script = (ROOT / "app" / "static" / "js" / "label_hub.js").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function renderMskuCell(params)" in script
    assert 'data-copy-msku="' in script
    assert "function copyMsku(button, value)" in script
    assert 'event.colDef.field === "label_summary"' in script
    assert "openDrawer(event.data)" in script
    assert "onRowClicked:" not in script
    assert ".label-hub-msku-copy" in styles
```

- [ ] **Step 2: 静默执行测试并确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_label_hub_frontend.py::test_label_hub_table_uses_explicit_profile_and_copy_actions -q`

Expected: FAIL，缺少显式复制函数且仍存在 `onRowClicked`。

- [ ] **Step 3: 实现最小交互修改**

在 `label_hub.js` 中：

```javascript
function renderMskuCell(params) {
  var value = String(params.value || "");
  return '<span class="label-hub-msku-cell"><span class="label-hub-msku-value">' +
    app.escapeHtml(value || "--") +
    '</span><button type="button" class="label-hub-msku-copy" data-copy-msku="' +
    app.escapeHtml(value) + '" aria-label="复制 MSKU ' + app.escapeHtml(value) +
    '" title="复制 MSKU">复制</button></span>';
}
```

将两个 `msku` 列的 `cellRenderer` 改为 `renderMskuCell`。在 `onCellClicked` 中先识别 `data-copy-msku`，复制后直接返回；再按 `label_summary` 打开 `openDrawer(event.data)`，按 `country_profile` 打开国家画像。删除 `onRowClicked`。

复制函数优先调用 `navigator.clipboard.writeText`，失败或不可用时用隐藏 `textarea` 与 `document.execCommand("copy")` 回退；按钮短暂显示“已复制”或“复制失败”。

在 `styles.css` 中为 `.label-hub-msku-cell`、`.label-hub-msku-value`、`.label-hub-msku-copy` 增加同行布局、文本选择和弱化按钮样式；标签画像单元格增加指针和键盘焦点态。

提升 `label_hub.html` 中 `label_hub.js` 与 `styles.css` 的缓存版本。

- [ ] **Step 4: 静默执行测试并确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_label_hub_frontend.py -q`

Expected: PASS。

- [ ] **Step 5: 语法与回归验证**

Run: `node --check app\static\js\label_hub.js`

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_label_hub_detail_data.py tests\test_label_hub_data.py tests\test_country_label_hub_data.py tests\test_label_hub_api.py tests\test_label_hub_frontend.py -q`

Expected: JavaScript 语法检查通过，相关回归全部通过。
