# Docs 第二阶段迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 24 个业务内容文件按“业务模块 → 文档类型”迁入目标目录，同时保持文件名和正文不变，并修复所有当前导航链接。

**Architecture:** 按项目运维与数据源、返场品、标签看板、产品分层看板、补货五个独立批次迁移。每批使用 `git mv` 保留历史，立即更新活动索引并校验链接，然后单独提交；`superpowers/` 中的历史设计和实施记录不随业务文件改写。

**Tech Stack:** Markdown、Git、PowerShell

## Global Constraints

- 在现有 `test/dashboard-test` 分支执行，不创建 worktree。
- 一级按业务模块分类，二级按文档类型分类。
- 所有迁移使用 `git mv`；现有文件名和正文保持不变。
- 不删除、合并或归档任何内容文件。
- 不创建没有文件的空目录，也不创建 `.gitkeep`。
- `docs/superpowers/specs/` 与 `docs/superpowers/plans/` 保持现有职责；其中记录当时路径的历史文本不重写。
- 每个批次只提交该批次的移动及活动索引链接更新。
- 每批提交前运行链接存在性校验与 `git diff --check`。

---

### Task 1: 迁移项目运维与数据源文档

**Files:**
- Move: `docs/windows_deploy.md` → `docs/项目运维/部署/windows_deploy.md`
- Move: `docs/version_control_workflow.md` → `docs/项目运维/协作规范/version_control_workflow.md`
- Move: `docs/store_brand_relation_import_plan.md` → `docs/数据源/导入方案/store_brand_relation_import_plan.md`
- Move: `docs/远端关于ods层的关系/库存数据源整理_ODS层.md` → `docs/数据源/ODS/库存数据源整理_ODS层.md`
- Modify: `docs/README.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: 第一阶段总索引中的项目运维与数据源条目。
- Produces: 可供仓库根 README 和 docs 总索引引用的四个稳定目标路径。

- [ ] **Step 1: 验证四个源文件存在且目标文件不存在**

```powershell
$pairs = @(
  @('docs/windows_deploy.md', 'docs/项目运维/部署/windows_deploy.md'),
  @('docs/version_control_workflow.md', 'docs/项目运维/协作规范/version_control_workflow.md'),
  @('docs/store_brand_relation_import_plan.md', 'docs/数据源/导入方案/store_brand_relation_import_plan.md'),
  @('docs/远端关于ods层的关系/库存数据源整理_ODS层.md', 'docs/数据源/ODS/库存数据源整理_ODS层.md')
)
foreach ($pair in $pairs) {
  if (-not (Test-Path -LiteralPath $pair[0] -PathType Leaf)) { throw "缺少源文件: $($pair[0])" }
  if (Test-Path -LiteralPath $pair[1]) { throw "目标已存在: $($pair[1])" }
}
```

Expected: 无输出，退出码为 0。

- [ ] **Step 2: 创建实际需要的目录并移动文件**

```powershell
@(
  'docs/项目运维/部署',
  'docs/项目运维/协作规范',
  'docs/数据源/导入方案',
  'docs/数据源/ODS'
) | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
git mv -- 'docs/windows_deploy.md' 'docs/项目运维/部署/windows_deploy.md'
git mv -- 'docs/version_control_workflow.md' 'docs/项目运维/协作规范/version_control_workflow.md'
git mv -- 'docs/store_brand_relation_import_plan.md' 'docs/数据源/导入方案/store_brand_relation_import_plan.md'
git mv -- 'docs/远端关于ods层的关系/库存数据源整理_ODS层.md' 'docs/数据源/ODS/库存数据源整理_ODS层.md'
```

- [ ] **Step 3: 更新活动导航链接**

在 `docs/README.md` 中进行四处精确替换：

```text
远端关于ods层的关系/库存数据源整理_ODS层.md → 数据源/ODS/库存数据源整理_ODS层.md
store_brand_relation_import_plan.md → 数据源/导入方案/store_brand_relation_import_plan.md
windows_deploy.md → 项目运维/部署/windows_deploy.md
version_control_workflow.md → 项目运维/协作规范/version_control_workflow.md
```

在仓库根 `README.md` 中进行两处精确替换：

```text
docs/windows_deploy.md → docs/项目运维/部署/windows_deploy.md
docs/version_control_workflow.md → docs/项目运维/协作规范/version_control_workflow.md
```

- [ ] **Step 4: 校验链接和变更范围**

```powershell
$root = (Resolve-Path '.').Path
$files = @('README.md', 'docs/README.md')
foreach ($file in $files) {
  $base = Split-Path -Parent (Join-Path $root $file)
  $text = Get-Content -LiteralPath $file -Encoding UTF8 -Raw
  $targets = [regex]::Matches($text, '\[[^\]]+\]\(([^)]+)\)') |
    ForEach-Object { [uri]::UnescapeDataString($_.Groups[1].Value) } |
    Where-Object { $_ -notmatch '^(https?:|#)' }
  $missing = @($targets | Where-Object { -not (Test-Path -LiteralPath (Join-Path $base $_)) })
  if ($missing.Count) { throw "$file 无效链接: $($missing -join ', ')" }
}
git diff --check
```

Expected: 没有无效链接；`git diff --check` 无错误。

- [ ] **Step 5: 提交项目运维与数据源批次**

```powershell
git add -- 'README.md' 'docs/README.md'
git commit -m '分类迁移项目运维和数据源文档'
```

### Task 2: 迁移返场品文档

**Files:**
- Move: `docs/返场品看板指标字典.md` → `docs/返场品/规则与口径/返场品看板指标字典.md`
- Move: `docs/返场品识别与恢复判定规则_讨论稿.md` → `docs/返场品/规则与口径/返场品识别与恢复判定规则_讨论稿.md`
- Move: `docs/返场品第一版规划.md` → `docs/返场品/方案与规划/返场品第一版规划.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: 第一阶段总索引中的返场品条目。
- Produces: 返场品规则、讨论稿和规划文档的分类路径。

- [ ] **Step 1: 验证源和目标路径**

```powershell
$pairs = @(
  @('docs/返场品看板指标字典.md', 'docs/返场品/规则与口径/返场品看板指标字典.md'),
  @('docs/返场品识别与恢复判定规则_讨论稿.md', 'docs/返场品/规则与口径/返场品识别与恢复判定规则_讨论稿.md'),
  @('docs/返场品第一版规划.md', 'docs/返场品/方案与规划/返场品第一版规划.md')
)
foreach ($pair in $pairs) {
  if (-not (Test-Path -LiteralPath $pair[0] -PathType Leaf)) { throw "缺少源文件: $($pair[0])" }
  if (Test-Path -LiteralPath $pair[1]) { throw "目标已存在: $($pair[1])" }
}
```

- [ ] **Step 2: 创建目录并使用 git mv 迁移**

```powershell
New-Item -ItemType Directory -Force -Path 'docs/返场品/规则与口径', 'docs/返场品/方案与规划' | Out-Null
git mv -- 'docs/返场品看板指标字典.md' 'docs/返场品/规则与口径/返场品看板指标字典.md'
git mv -- 'docs/返场品识别与恢复判定规则_讨论稿.md' 'docs/返场品/规则与口径/返场品识别与恢复判定规则_讨论稿.md'
git mv -- 'docs/返场品第一版规划.md' 'docs/返场品/方案与规划/返场品第一版规划.md'
```

- [ ] **Step 3: 更新 docs 总索引的三个相对链接**

```text
返场品看板指标字典.md → 返场品/规则与口径/返场品看板指标字典.md
返场品识别与恢复判定规则_讨论稿.md → 返场品/规则与口径/返场品识别与恢复判定规则_讨论稿.md
返场品第一版规划.md → 返场品/方案与规划/返场品第一版规划.md
```

- [ ] **Step 4: 校验并提交返场品批次**

```powershell
$base = (Resolve-Path 'docs').Path
$text = Get-Content -LiteralPath 'docs/README.md' -Encoding UTF8 -Raw
$targets = [regex]::Matches($text, '\[[^\]]+\]\(([^)]+)\)') | ForEach-Object { [uri]::UnescapeDataString($_.Groups[1].Value) } | Where-Object { $_ -notmatch '^(https?:|#)' }
$missing = @($targets | Where-Object { -not (Test-Path -LiteralPath (Join-Path $base $_)) })
if ($missing.Count) { throw "无效链接: $($missing -join ', ')" }
git diff --check
git add -- 'docs/README.md' 'docs/返场品'
git commit -m '分类迁移返场品文档'
```

### Task 3: 迁移标签看板文档

**Files:**
- Move: `docs/标签打标证据字段规范.md` → `docs/标签看板/规则与口径/标签打标证据字段规范.md`
- Move: `docs/标签看板销售角色诊断扩展_设计与实施交接.md` → `docs/标签看板/方案与交接/标签看板销售角色诊断扩展_设计与实施交接.md`
- Move: `docs/标签看板返场规则对齐部署说明_20260728.md` → `docs/标签看板/部署说明/标签看板返场规则对齐部署说明_20260728.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: 第一阶段总索引中的标签看板条目。
- Produces: 标签规则、交接和部署文档的分类路径。

- [ ] **Step 1: 验证源和目标路径**

```powershell
$pairs = @(
  @('docs/标签打标证据字段规范.md', 'docs/标签看板/规则与口径/标签打标证据字段规范.md'),
  @('docs/标签看板销售角色诊断扩展_设计与实施交接.md', 'docs/标签看板/方案与交接/标签看板销售角色诊断扩展_设计与实施交接.md'),
  @('docs/标签看板返场规则对齐部署说明_20260728.md', 'docs/标签看板/部署说明/标签看板返场规则对齐部署说明_20260728.md')
)
foreach ($pair in $pairs) {
  if (-not (Test-Path -LiteralPath $pair[0] -PathType Leaf)) { throw "缺少源文件: $($pair[0])" }
  if (Test-Path -LiteralPath $pair[1]) { throw "目标已存在: $($pair[1])" }
}
```

- [ ] **Step 2: 创建目录并使用 git mv 迁移**

```powershell
New-Item -ItemType Directory -Force -Path 'docs/标签看板/规则与口径', 'docs/标签看板/方案与交接', 'docs/标签看板/部署说明' | Out-Null
git mv -- 'docs/标签打标证据字段规范.md' 'docs/标签看板/规则与口径/标签打标证据字段规范.md'
git mv -- 'docs/标签看板销售角色诊断扩展_设计与实施交接.md' 'docs/标签看板/方案与交接/标签看板销售角色诊断扩展_设计与实施交接.md'
git mv -- 'docs/标签看板返场规则对齐部署说明_20260728.md' 'docs/标签看板/部署说明/标签看板返场规则对齐部署说明_20260728.md'
```

- [ ] **Step 3: 更新 docs 总索引的三个相对链接**

```text
标签打标证据字段规范.md → 标签看板/规则与口径/标签打标证据字段规范.md
标签看板销售角色诊断扩展_设计与实施交接.md → 标签看板/方案与交接/标签看板销售角色诊断扩展_设计与实施交接.md
标签看板返场规则对齐部署说明_20260728.md → 标签看板/部署说明/标签看板返场规则对齐部署说明_20260728.md
```

- [ ] **Step 4: 校验并提交标签看板批次**

```powershell
$base = (Resolve-Path 'docs').Path
$text = Get-Content -LiteralPath 'docs/README.md' -Encoding UTF8 -Raw
$targets = [regex]::Matches($text, '\[[^\]]+\]\(([^)]+)\)') | ForEach-Object { [uri]::UnescapeDataString($_.Groups[1].Value) } | Where-Object { $_ -notmatch '^(https?:|#)' }
$missing = @($targets | Where-Object { -not (Test-Path -LiteralPath (Join-Path $base $_)) })
if ($missing.Count) { throw "无效链接: $($missing -join ', ')" }
git diff --check
git add -- 'docs/README.md' 'docs/标签看板'
git commit -m '分类迁移标签看板文档'
```

### Task 4: 迁移产品分层看板文档

**Files:**
- Move: `docs/指标口径与SQL占位文档.md` → `docs/产品分层看板/指标与口径/指标口径与SQL占位文档.md`
- Move: `docs/每日更新任务设计方案.md` → `docs/产品分层看板/任务与运维/每日更新任务设计方案.md`
- Move: `docs/看板功能与数据更新说明.md` → `docs/产品分层看板/任务与运维/看板功能与数据更新说明.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: 第一阶段总索引中的产品分层看板条目。
- Produces: 指标口径和运维资料的分类路径。

- [ ] **Step 1: 验证源和目标路径**

```powershell
$pairs = @(
  @('docs/指标口径与SQL占位文档.md', 'docs/产品分层看板/指标与口径/指标口径与SQL占位文档.md'),
  @('docs/每日更新任务设计方案.md', 'docs/产品分层看板/任务与运维/每日更新任务设计方案.md'),
  @('docs/看板功能与数据更新说明.md', 'docs/产品分层看板/任务与运维/看板功能与数据更新说明.md')
)
foreach ($pair in $pairs) {
  if (-not (Test-Path -LiteralPath $pair[0] -PathType Leaf)) { throw "缺少源文件: $($pair[0])" }
  if (Test-Path -LiteralPath $pair[1]) { throw "目标已存在: $($pair[1])" }
}
```

- [ ] **Step 2: 创建目录并使用 git mv 迁移**

```powershell
New-Item -ItemType Directory -Force -Path 'docs/产品分层看板/指标与口径', 'docs/产品分层看板/任务与运维' | Out-Null
git mv -- 'docs/指标口径与SQL占位文档.md' 'docs/产品分层看板/指标与口径/指标口径与SQL占位文档.md'
git mv -- 'docs/每日更新任务设计方案.md' 'docs/产品分层看板/任务与运维/每日更新任务设计方案.md'
git mv -- 'docs/看板功能与数据更新说明.md' 'docs/产品分层看板/任务与运维/看板功能与数据更新说明.md'
```

- [ ] **Step 3: 更新 docs 总索引的三个相对链接**

```text
指标口径与SQL占位文档.md → 产品分层看板/指标与口径/指标口径与SQL占位文档.md
每日更新任务设计方案.md → 产品分层看板/任务与运维/每日更新任务设计方案.md
看板功能与数据更新说明.md → 产品分层看板/任务与运维/看板功能与数据更新说明.md
```

- [ ] **Step 4: 校验并提交产品分层看板批次**

```powershell
$base = (Resolve-Path 'docs').Path
$text = Get-Content -LiteralPath 'docs/README.md' -Encoding UTF8 -Raw
$targets = [regex]::Matches($text, '\[[^\]]+\]\(([^)]+)\)') | ForEach-Object { [uri]::UnescapeDataString($_.Groups[1].Value) } | Where-Object { $_ -notmatch '^(https?:|#)' }
$missing = @($targets | Where-Object { -not (Test-Path -LiteralPath (Join-Path $base $_)) })
if ($missing.Count) { throw "无效链接: $($missing -join ', ')" }
git diff --check
git add -- 'docs/README.md' 'docs/产品分层看板'
git commit -m '分类迁移产品分层看板文档'
```

### Task 5: 迁移补货文档并完成阶段验收

**Files:**
- Move 6 rule files to: `docs/补货/规则与口径/`
- Move 3 planning files to: `docs/补货/方案与规划/`
- Move 2 investigation files to: `docs/补货/排查与差异/`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: 第一阶段总索引中的全部补货条目，以及前四个批次形成的目录结构。
- Produces: 根目录仅保留 `docs/README.md` 的完整第二阶段结果。

- [ ] **Step 1: 验证补货源文件和目标目录均符合预期**

```powershell
$mapping = [ordered]@{
  'docs/current_follow_replenishment_rules.md' = 'docs/补货/规则与口径/current_follow_replenishment_rules.md'
  'docs/是否补货规则新方案v2.md' = 'docs/补货/规则与口径/是否补货规则新方案v2.md'
  'docs/补货追踪链路新版梳理.md' = 'docs/补货/规则与口径/补货追踪链路新版梳理.md'
  'docs/补货追踪页面完整流程与链路口径.md' = 'docs/补货/规则与口径/补货追踪页面完整流程与链路口径.md'
  'docs/补货追踪页面完整流程与链路口径.html' = 'docs/补货/规则与口径/补货追踪页面完整流程与链路口径.html'
  'docs/补货追踪页面状态判断口径.md' = 'docs/补货/规则与口径/补货追踪页面状态判断口径.md'
  'docs/补货分层采购发货追踪规划.md' = 'docs/补货/方案与规划/补货分层采购发货追踪规划.md'
  'docs/低销量SKU支持天数波动优化方案.md' = 'docs/补货/方案与规划/低销量SKU支持天数波动优化方案.md'
  'docs/方案8-低销量SKU单日大跳变拦截详细规划.md' = 'docs/补货/方案与规划/方案8-低销量SKU单日大跳变拦截详细规划.md'
  'docs/2026-07-07-紧急补货大量退出排查记录.md' = 'docs/补货/排查与差异/2026-07-07-紧急补货大量退出排查记录.md'
  'docs/补货看板与原SQL历史兜底差异说明.md' = 'docs/补货/排查与差异/补货看板与原SQL历史兜底差异说明.md'
}
foreach ($entry in $mapping.GetEnumerator()) {
  if (-not (Test-Path -LiteralPath $entry.Key -PathType Leaf)) { throw "缺少源文件: $($entry.Key)" }
  if (Test-Path -LiteralPath $entry.Value) { throw "目标已存在: $($entry.Value)" }
}
```

- [ ] **Step 2: 创建三个目录并逐个使用 git mv 迁移**

```powershell
New-Item -ItemType Directory -Force -Path 'docs/补货/规则与口径', 'docs/补货/方案与规划', 'docs/补货/排查与差异' | Out-Null
$mapping = [ordered]@{
  'docs/current_follow_replenishment_rules.md' = 'docs/补货/规则与口径/current_follow_replenishment_rules.md'
  'docs/是否补货规则新方案v2.md' = 'docs/补货/规则与口径/是否补货规则新方案v2.md'
  'docs/补货追踪链路新版梳理.md' = 'docs/补货/规则与口径/补货追踪链路新版梳理.md'
  'docs/补货追踪页面完整流程与链路口径.md' = 'docs/补货/规则与口径/补货追踪页面完整流程与链路口径.md'
  'docs/补货追踪页面完整流程与链路口径.html' = 'docs/补货/规则与口径/补货追踪页面完整流程与链路口径.html'
  'docs/补货追踪页面状态判断口径.md' = 'docs/补货/规则与口径/补货追踪页面状态判断口径.md'
  'docs/补货分层采购发货追踪规划.md' = 'docs/补货/方案与规划/补货分层采购发货追踪规划.md'
  'docs/低销量SKU支持天数波动优化方案.md' = 'docs/补货/方案与规划/低销量SKU支持天数波动优化方案.md'
  'docs/方案8-低销量SKU单日大跳变拦截详细规划.md' = 'docs/补货/方案与规划/方案8-低销量SKU单日大跳变拦截详细规划.md'
  'docs/2026-07-07-紧急补货大量退出排查记录.md' = 'docs/补货/排查与差异/2026-07-07-紧急补货大量退出排查记录.md'
  'docs/补货看板与原SQL历史兜底差异说明.md' = 'docs/补货/排查与差异/补货看板与原SQL历史兜底差异说明.md'
}
foreach ($entry in $mapping.GetEnumerator()) { git mv -- $entry.Key $entry.Value }
```

- [ ] **Step 3: 更新 docs 总索引的 11 个补货链接**

在 `docs/README.md` 中执行以下精确替换；只修改链接目标，不修改标题、用途、状态和日期：

```text
current_follow_replenishment_rules.md → 补货/规则与口径/current_follow_replenishment_rules.md
是否补货规则新方案v2.md → 补货/规则与口径/是否补货规则新方案v2.md
补货追踪链路新版梳理.md → 补货/规则与口径/补货追踪链路新版梳理.md
补货追踪页面完整流程与链路口径.md → 补货/规则与口径/补货追踪页面完整流程与链路口径.md
补货追踪页面完整流程与链路口径.html → 补货/规则与口径/补货追踪页面完整流程与链路口径.html
补货追踪页面状态判断口径.md → 补货/规则与口径/补货追踪页面状态判断口径.md
补货分层采购发货追踪规划.md → 补货/方案与规划/补货分层采购发货追踪规划.md
低销量SKU支持天数波动优化方案.md → 补货/方案与规划/低销量SKU支持天数波动优化方案.md
方案8-低销量SKU单日大跳变拦截详细规划.md → 补货/方案与规划/方案8-低销量SKU单日大跳变拦截详细规划.md
2026-07-07-紧急补货大量退出排查记录.md → 补货/排查与差异/2026-07-07-紧急补货大量退出排查记录.md
补货看板与原SQL历史兜底差异说明.md → 补货/排查与差异/补货看板与原SQL历史兜底差异说明.md
```

- [ ] **Step 4: 验证全部业务文件覆盖、根目录收敛和项目测试**

```powershell
$docsRoot = (Resolve-Path 'docs').Path
$text = Get-Content -LiteralPath 'docs/README.md' -Encoding UTF8 -Raw
$targets = [regex]::Matches($text, '\[[^\]]+\]\(([^)]+)\)') | ForEach-Object { [uri]::UnescapeDataString($_.Groups[1].Value) } | Where-Object { $_ -notmatch '^(https?:|#)' }
$missing = @($targets | Where-Object { -not (Test-Path -LiteralPath (Join-Path $docsRoot $_)) })
if ($missing.Count) { throw "无效链接: $($missing -join ', ')" }
$content = @(Get-ChildItem -LiteralPath $docsRoot -File -Recurse | Where-Object { $_.FullName -notmatch '[\\/]superpowers[\\/]' -and $_.Name -ne 'README.md' })
$linked = @($targets | Where-Object { $_ -notmatch '^superpowers[\\/]' } | ForEach-Object { (Resolve-Path -LiteralPath (Join-Path $docsRoot $_)).Path } | Sort-Object -Unique)
$unindexed = @($content.FullName | Where-Object { $_ -notin $linked })
if ($unindexed.Count) { throw "未被索引: $($unindexed -join ', ')" }
$rootFiles = @(Get-ChildItem -LiteralPath $docsRoot -File | Where-Object Name -ne 'README.md')
if ($rootFiles.Count) { throw "docs 根目录仍有业务文件: $($rootFiles.Name -join ', ')" }
python -m pytest -q
git diff --check
```

Expected: 25 个本地链接有效、24 个业务内容文件全部索引、`docs/` 根目录无其他文件、594 项测试通过。

- [ ] **Step 5: 提交补货批次**

```powershell
git add -- 'docs/README.md' 'docs/补货'
git commit -m '分类迁移补货文档并完成目录收敛'
git status --short
```

Expected: 提交后工作区干净。
