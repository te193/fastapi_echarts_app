# 标签看板明细筛选按钮视觉优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将“应用筛选”和“重置”改成符合页面蓝灰色视觉体系的主次按钮。

**Architecture:** 保留现有模板、DOM 标识和 JavaScript 事件，仅覆盖两个专属 CSS 类。通过静态契约测试锁定主按钮、次按钮及交互状态。

**Tech Stack:** CSS、pytest 静态前端契约测试。

## Global Constraints

- 不修改按钮文案、位置、DOM 标识或筛选逻辑。
- 控件高度保持 36px，圆角保持 6px。
- 测试在后台静默执行。

---

### Task 1: 统一筛选操作按钮视觉

**Files:**
- Modify: `app/static/css/styles.css`
- Test: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: `.label-hub-detail-apply`、`.label-hub-detail-clear`
- Produces: 主按钮、次按钮及 hover/active/focus-visible 状态

- [ ] **Step 1: 写失败的样式契约测试**

```python
def test_detail_filter_action_buttons_follow_primary_secondary_hierarchy():
    styles = (ROOT / "app" / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    assert ".label-hub-detail-apply:hover" in styles
    assert ".label-hub-detail-clear:hover" in styles
    assert ".label-hub-detail-apply:focus-visible" in styles
```

- [ ] **Step 2: 运行目标测试并确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_label_hub_frontend.py::test_detail_filter_action_buttons_follow_primary_secondary_hierarchy -q`

Expected: FAIL，交互状态尚未定义。

- [ ] **Step 3: 实现按钮样式**

```css
.label-hub-detail-apply { background: #1677e8; color: #fff; }
.label-hub-detail-clear { border: 1px solid #c9d5e5; background: #fff; color: #53657b; }
```

同时补充两个按钮的 hover、active 和 focus-visible 状态。

- [ ] **Step 4: 静默验证**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_label_hub_frontend.py -q`

Run: `git diff --check`

Expected: 全部通过且无新增空白错误。
