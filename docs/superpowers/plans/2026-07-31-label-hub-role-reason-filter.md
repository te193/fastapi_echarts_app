# 标签看板角色原因筛选 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将经营明细高级筛选中的“销售趋势”替换为按明细维度和销售角色联动的“角色原因”多选筛选。

**Architecture:** 前端从现有标签元数据读取父标签 15/16 的子标签并维护 `role_reason_ids`；后端明细服务按 `detail_view` 校验允许的子标签 ID，再复用行内 `_by_parent` / `labels` 完成同父标签 OR、跨筛选 AND。维度切换清空原因，销售角色变化裁剪不兼容原因。

**Tech Stack:** FastAPI、Pydantic、Python unittest/pytest、原生 JavaScript、SlimSelect、Jinja2。

## Global Constraints

- 不修改诊断标签生成规则和证据 JSON。
- 不修改角色诊断抽屉、明细表格字段和排序逻辑。
- MSKU 维度只使用父标签 15；国家明细只使用父标签 16。
- 角色原因同字段多选为 OR，与销售角色及其他筛选条件为 AND。
- 不创建分支或 worktree，不提交或推送 Git。
- 浏览器验证仅使用独立后台无头会话，不操作用户前台浏览器。

---

### Task 1: 明细服务支持角色原因筛选

**Files:**
- Modify: `tests/test_label_hub_detail_data.py`
- Modify: `app/services/label_hub_detail_data.py`

**Interfaces:**
- Consumes: `get_details(**filters)` 中的 `detail_view`、行的 `_by_parent` / `labels`。
- Produces: `role_reason_ids: list[int]` 筛选参数及 `applied_filters.role_reason_ids`。

- [ ] **Step 1: 写失败测试**

在业务行夹具中加入父标签 15 子标签，并增加测试：

```python
def test_business_role_reason_multiselect_is_or_and_combines_with_role(self):
    service, _ = self.make_service()
    payload = service.get_details(
        sales_roles=["potential"],
        role_reason_ids=[1502, 1503],
    )
    self.assertEqual(["MSKU-2"], [row["msku"] for row in payload["rows"]])
    self.assertEqual([1502, 1503], payload["applied_filters"]["role_reason_ids"])
```

为国家行构造父标签 16，并增加口径测试：

```python
def test_role_reason_ids_are_limited_to_the_current_detail_view(self):
    service, _ = self.make_country_service()
    with self.assertRaisesRegex(ValueError, "角色原因"):
        service.get_details(detail_view="business_unit", role_reason_ids=[1602])
    with self.assertRaisesRegex(ValueError, "角色原因"):
        service.get_details(detail_view="country", role_reason_ids=[1502])
```

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
pytest tests/test_label_hub_detail_data.py -q
```

Expected: 新增断言失败，因为 `role_reason_ids` 尚未筛选和校验。

- [ ] **Step 3: 实现最小服务逻辑**

在 `app/services/label_hub_detail_data.py` 增加：

```python
ROLE_REASON_PARENT_BY_VIEW = {"business_unit": 15, "country": 16}
ROLE_REASON_IDS_BY_VIEW = {
    "business_unit": set(range(1501, 1509)),
    "country": set(range(1601, 1619)),
}
```

在 `get_details()` 中规范化为整数集合，拒绝非当前视图 ID；在 `row_matches()` 中判断当前父标签已有子标签与所选集合是否相交；将字段加入 `detail_filters_active` 和 `applied_filters`。

- [ ] **Step 4: 运行服务测试并确认通过**

Run:

```powershell
pytest tests/test_label_hub_detail_data.py -q
```

Expected: 全部通过。

---

### Task 2: API 请求模型透传角色原因

**Files:**
- Modify: `tests/test_label_hub_api.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: POST `/api/label-hub/details` JSON。
- Produces: `LabelHubDetailRequest.role_reason_ids: list[int]`，完整透传给明细服务。

- [ ] **Step 1: 写失败测试**

在现有明细请求透传测试中传入：

```python
role_reason_ids=[1502, 1503],
```

并断言：

```python
self.assertEqual([1502, 1503], service.calls[0]["role_reason_ids"])
```

同时移除该明细请求夹具的 `sales_trends`。

- [ ] **Step 2: 运行测试并确认按预期失败**

Run:

```powershell
pytest tests/test_label_hub_api.py -q
```

Expected: Pydantic 请求模型不接受或不透传 `role_reason_ids`。

- [ ] **Step 3: 实现请求字段**

将 `LabelHubDetailRequest.sales_trends` 替换为：

```python
role_reason_ids: list[int] = Field(default_factory=list)
```

- [ ] **Step 4: 运行 API 测试并确认通过**

Run:

```powershell
pytest tests/test_label_hub_api.py -q
```

Expected: 全部通过。

---

### Task 3: 前端控件、联动和请求状态

**Files:**
- Modify: `tests/test_label_hub_frontend.py`
- Modify: `app/templates/label_hub.html`
- Modify: `app/static/js/label_hub.js`
- Modify: `app/static/css/styles.css`

**Interfaces:**
- Consumes: `meta.excluded_categories` 中父标签 15、16，`detailState.detail_view` 和 `detailState.sales_roles`。
- Produces: `detailState.role_reason_ids`、`buildDetailPayload().role_reason_ids` 和 `labelHubDetailRoleReasons` 多选控件。

- [ ] **Step 1: 写失败测试**

更新经营明细筛选契约测试：

```python
assert 'id="labelHubDetailRoleReasons"' in template
assert 'data-placeholder="全部角色原因"' in template
assert 'id="labelHubDetailSalesTrends"' not in template
assert "role_reason_ids: []" in script
assert "role_reason_ids: detailState.role_reason_ids" in script
assert "function roleReasonOptions()" in script
assert "function reconcileRoleReasonSelections()" in script
assert '["role_reason_ids", "角色原因", elements.labelHubDetailRoleReasons]' in script
```

并断言样式包含口径提示及分组下拉类：

```python
assert ".label-hub-role-reason-scope" in styles
assert ".label-hub-role-reason-group" in styles
```

- [ ] **Step 2: 运行前端契约测试并确认按预期失败**

Run:

```powershell
pytest tests/test_label_hub_frontend.py -q
```

Expected: 新控件、状态和辅助函数不存在。

- [ ] **Step 3: 实现模板和前端状态**

模板中将“销售趋势”控件替换为：

```html
<label class="label-hub-detail-filter-control label-hub-role-reason-control">
  <span>角色原因 <small id="labelHubRoleReasonScope" class="label-hub-role-reason-scope">MSKU维度 · 全站诊断</small></span>
  <select id="labelHubDetailRoleReasons" multiple data-placeholder="全部角色原因"></select>
</label>
```

JavaScript 中：

- 用 `role_reason_ids: []` 替换明细状态中的 `sales_trends`。
- `roleReasonCategory()` 按视图返回父标签 15 或 16。
- `roleReasonOptions()` 从该父标签读取子标签，按标签名称映射到销售角色并按当前 `sales_roles` 裁剪。
- `reconcileRoleReasonSelections()` 清除当前选项集合之外的选择。
- 维度切换时清空角色原因、重新填充控件。
- 收集销售角色后裁剪原因选择。
- 请求、重置、原生选择同步、已选条件和筛选数量统一使用 `role_reason_ids`。
- 展开选项显示角色分组标题，顶部口径文字随维度切换。

CSS 只增加分组标题、口径提示及控件宽度所需样式，复用现有 SlimSelect 颜色与边框。

- [ ] **Step 4: 运行前端测试并确认通过**

Run:

```powershell
pytest tests/test_label_hub_frontend.py -q
```

Expected: 全部通过。

---

### Task 4: 集成回归与后台视觉验证

**Files:**
- Modify only if verification finds a regression.

**Interfaces:**
- Consumes: Tasks 1–3 的完整实现。
- Produces: 可验证的接口筛选和方案 1 视觉状态。

- [ ] **Step 1: 运行针对性测试**

Run:

```powershell
pytest tests/test_label_hub_detail_data.py tests/test_label_hub_api.py tests/test_label_hub_frontend.py -q
```

Expected: 0 failures。

- [ ] **Step 2: 运行全量测试**

Run:

```powershell
pytest -q
```

Expected: 0 failures。

- [ ] **Step 3: 后台接口检查**

分别请求业务维度父标签 15 和国家维度父标签 16 的原因，确认返回行均命中相应父标签子标签；提交错误口径 ID 时确认 HTTP 400。

- [ ] **Step 4: 后台无头浏览器视觉检查**

使用独立无头浏览器打开 `http://127.0.0.1:8001/label-hub`，验证：

- 高级筛选默认显示“全部角色原因”。
- 未选角色时下拉按角色分组。
- 选择潜力产品后只保留潜力原因。
- 维度切换后口径文字变更且已选原因清空。
- 1366px 和 1600px 下控件不裁切、不覆盖表格。

关闭无头浏览器会话，不触碰用户前台浏览器。
