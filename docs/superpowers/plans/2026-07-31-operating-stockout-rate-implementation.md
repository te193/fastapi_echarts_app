# Operating Stockout Rate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for progress tracking.

**Goal:** 在“运营状态”标签分布下增加随现有筛选联动的“在营断货率”脚注，并提供轻量口径说明浮层。

**Architecture:** 复用 `LabelHubDataService.build_payload()` 已聚合好的运营状态 `distribution`，在服务端按标签名称计算可核对的分子、分母和比率，并作为独立 payload 字段返回。前端仅在当前大类为“运营状态”且指标可用时渲染方案 F 的低调脚注；“查看口径”只控制本地浮层，不触发筛选或请求。

**Tech Stack:** Python 3、FastAPI 服务层、原生 JavaScript、CSS、pytest。

## Global Constraints

- 公式固定为：`(断货中 - 返场期再次断货) / (正常在售 + 测款扶持 + 返厂品/返场品 + 断货中)`。
- “清仓中”和“停售”不进入分母；返场期再次断货只从分子扣除，不从分母扣除。
- 指标必须使用当前页面所有公共筛选和联动条件作用后的 `distribution`，不得另起一套查询。
- 分母为 0 时不显示误导性的百分比。
- 不改变运营状态卡片、返场归因按钮和其他标签大类的交互逻辑。
- 验证使用单元测试和独立后台进程，不操作用户正在使用的前台服务。

---

## Task 1: Add a reconciled backend metric

**Files:**
- Modify: `tests/test_label_hub_data.py`
- Modify: `app/services/label_hub_data.py`

- [x] **Step 1: Write the failing service test**

扩充运营状态测试数据，覆盖“正常在售、测款扶持、返厂品、断货中、清仓中、停售”，并断言 payload 中：

```python
self.assertEqual(
    {
        "effective_stockout_count": 1,
        "operating_count": 5,
        "return_restockout_count": 1,
        "rate": 0.2,
    },
    payload["operating_stockout_rate"],
)
```

同时新增非运营状态父标签的断言，确认该字段为 `None`，避免在其他大类误展示。

- [x] **Step 2: Run the focused test and confirm RED**

Run:

```powershell
pytest tests/test_label_hub_data.py -k "operating_stockout_rate or operation_distribution" -q
```

Expected: FAIL because `operating_stockout_rate` is not yet present.

- [x] **Step 3: Implement the smallest backend calculation**

在 `current_distribution(rows)` 完成后：

1. 仅当当前父标签名称为“运营状态”时计算；
2. 按子标签名称读取 `count`，兼容“返厂品”和“返场品”两种现有命名；
3. 从“断货中”的 `return_stage_count` 读取返场期再次断货数；
4. 计算并返回：

```python
{
    "effective_stockout_count": max(0, stockout_count - return_restockout_count),
    "operating_count": operating_count,
    "return_restockout_count": return_restockout_count,
    "rate": round(effective_stockout_count / operating_count, 4) if operating_count else None,
}
```

非运营状态返回 `None`。

- [x] **Step 4: Run focused and service tests**

Run:

```powershell
pytest tests/test_label_hub_data.py -k "operating_stockout_rate or operation_distribution" -q
pytest tests/test_label_hub_data.py -q
```

Expected: PASS.

- [x] **Step 5: Commit backend slice**

```powershell
git add app/services/label_hub_data.py tests/test_label_hub_data.py
git commit -m "增加在营断货率计算"
```

---

## Task 2: Render solution F and its definition popover

**Files:**
- Modify: `tests/test_label_hub_frontend.py`
- Modify: `app/static/js/label_hub.js`
- Modify: `app/static/css/styles.css`

- [x] **Step 1: Write the failing frontend contract test**

断言前端包含：

- `renderOperatingStockoutRate`
- `data-operating-stockout-formula`
- “在营断货率”“有效断货”“在营”“返场再断货”“查看口径”
- 口径文案明确排除清仓中和停售
- `.label-hub-operating-stockout-rate` 与 `.label-hub-operating-stockout-popover`

- [x] **Step 2: Run the focused frontend test and confirm RED**

Run:

```powershell
pytest tests/test_label_hub_frontend.py -k "operating_stockout" -q
```

Expected: FAIL because the footer and popover do not yet exist.

- [x] **Step 3: Implement the low-emphasis footer**

在 `renderCategoryDetail(payload)` 中将指标脚注追加到运营状态子标签网格下方：

```text
在营断货率 26.7% · 有效断货 413 / 在营 1,545 · 返场再断货 24 · 查看口径
```

要求：

- 数字使用现有 `formatNumber` / `formatPercent`；
- 指标无效或分母为 0 时不渲染；
- 视觉为右对齐的次级信息，不增加独立大卡片。

- [x] **Step 4: Implement local popover behavior**

通过 `labelHubCategoryDetail` 内的事件委托处理按钮：

- 点击“查看口径”切换浮层；
- 浮层展示公式、分子和分母包含项；
- `Escape` 和点击浮层外关闭；
- 按钮使用 `aria-expanded`，浮层使用可读的语义结构；
- 不调用 `refresh()`、不改变 URL 状态。

- [x] **Step 5: Add restrained styling**

为脚注与浮层增加 CSS：

- 脚注使用 muted 文本、细分隔线和紧凑间距；
- 仅指标名称/百分比稍加深；
- 浮层宽度受控，阴影和边框沿用页面现有风格；
- 在窄屏下允许自然换行，不遮挡卡片。

- [x] **Step 6: Run frontend tests**

Run:

```powershell
pytest tests/test_label_hub_frontend.py -q
```

Expected: PASS.

- [x] **Step 7: Commit frontend slice**

```powershell
git add app/static/js/label_hub.js app/static/css/styles.css tests/test_label_hub_frontend.py
git commit -m "展示在营断货率及统计口径"
```

---

## Task 3: Regression and background verification

**Files:**
- Verify only

- [x] **Step 1: Run the label-hub regression suite**

Run:

```powershell
pytest tests/test_label_hub_data.py tests/test_label_hub_api.py tests/test_label_hub_frontend.py -q
```

Expected: PASS.

- [x] **Step 2: Check JavaScript syntax**

Run with the workspace Node runtime:

```powershell
node --check app/static/js/label_hub.js
```

Expected: exit code 0.

- [x] **Step 3: Verify payload and UI in an isolated background server**

启动独立端口（不使用用户当前的 8001/60485），请求标签看板 API 并确认：

- 运营状态返回 `operating_stockout_rate`；
- 计算结果与各卡片计数可对账；
- 非运营状态不返回可展示指标；
- 页面加载无控制台错误，脚注和口径浮层可见且不改变筛选。

- [x] **Step 4: Review diff and repository state**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only intended commits/ignored runtime files remain.
