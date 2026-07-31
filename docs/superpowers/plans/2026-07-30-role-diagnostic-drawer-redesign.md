# Role Diagnostic Drawer Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将销售角色诊断抽屉改造成按需加载的全站点与国家站点升级诊断，展示当前值、目标阈值、未达标指标和升级差距。

**Architecture:** 新建独立服务读取当前 MSKU 的标签证据 JSON，并在服务层把现有指标和角色规则转换成稳定的诊断 DTO。新增轻量 GET API；前端打开抽屉和切换周期时按需加载，并以全站摘要加国家折叠列表呈现，避免扩大主看板接口。

**Tech Stack:** FastAPI、Python、PyMySQL、原生 JavaScript、CSS、pytest、Playwright CLI

## Global Constraints

- 不修改标签生成 SQL 和现有标签规则。
- 不向标签看板主接口批量返回证据 JSON。
- 周期仅支持 `7d`、`14d`、`30d`、`90d`。
- 默认跟随页面 `label_period`；页面为 `all` 时使用 `30d`。
- 只重构角色诊断模式，不影响 MSKU 画像和国家画像抽屉。
- 当前工作区不提交、不推送。

---

### Task 1: 诊断规则与证据服务

**Files:**
- Create: `app/services/label_hub_role_diagnostics.py`
- Create: `tests/test_label_hub_role_diagnostics.py`

**Interfaces:**
- Produces: `LabelHubRoleDiagnosticService.get_payload(data_date, country_category, store, msku, diagnostic_period) -> dict`
- Payload keys: `identity`, `period`, `global_diagnostic`, `country_diagnostics`, `meta`

- [ ] 写服务测试，覆盖全站潜力、国家瘦狗、问题产品、已达标和缺失指标。
- [ ] 运行测试，确认因服务不存在而失败。
- [ ] 实现证据 JSON 解析、目标规则分支、指标状态、差距格式和国家优先级排序。
- [ ] 运行服务测试并确认通过。

### Task 2: 按需诊断 API

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_label_hub_api.py`

**Interfaces:**
- Produces: `GET /api/label-hub/msku-role-diagnostics`
- Consumes: Task 1 的 `get_payload`

- [ ] 写 API 参数透传测试并确认失败。
- [ ] 注册服务与路由，校验周期及必需身份字段。
- [ ] 运行 API 测试并确认通过。

### Task 3: 抽屉数据加载与渲染

**Files:**
- Modify: `app/static/js/label_hub.js`
- Modify: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: Task 2 的诊断 payload。
- Produces: `loadRoleDiagnosticDrawer`、`renderRoleDiagnosticDrawer`、周期切换与单国家展开。

- [ ] 写前端静态契约测试，覆盖新接口、页面周期跟随、周期按钮、全站摘要和国家折叠。
- [ ] 运行测试并确认失败。
- [ ] 用按需加载替换旧标签卡片列表；保留请求令牌，避免快速切换覆盖新结果。
- [ ] 实现抽屉内周期切换和单国家展开。
- [ ] 运行前端测试和 `node --check`。

### Task 4: 视觉样式与状态

**Files:**
- Modify: `app/static/css/styles.css`
- Modify: `tests/test_label_hub_frontend.py`

**Interfaces:**
- Consumes: Task 3 的角色诊断 DOM 类。
- Produces: 全站诊断卡、指标卡、差距提示、国家折叠列表、加载和错误状态。

- [ ] 增加样式契约测试并确认失败。
- [ ] 实现已确认的方案 A 样式及窄屏布局。
- [ ] 运行聚焦前端测试。

### Task 5: 回归与真实数据验证

**Files:**
- Verify: `output/playwright/`

**Interfaces:**
- Consumes: 完整实现。
- Produces: HW065a 30d 桌面与窄屏截图。

- [ ] 运行完整 `python -m pytest -q`。
- [ ] 运行 `node --check app/static/js/label_hub.js` 和 `git diff --check`。
- [ ] 重启 8001 服务并验证 HW065a 真实接口。
- [ ] 使用 Playwright 检查打开抽屉、周期切换、国家折叠、桌面和窄屏状态。
- [ ] 确认浏览器控制台 0 错误。
