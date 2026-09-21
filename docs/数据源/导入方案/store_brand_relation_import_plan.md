# 店铺品牌对应表更新规划

## 背景

补货 ETL 当前通过远端表 `opt_db.store_brand_relation` 识别店铺自有品牌，再同步生成：

```text
dashboard_replenishment_self_asin_sync
```

这个同步结果会影响跟卖识别：

- 能匹配到店铺品牌关系的 ASIN，会被识别为自有 ASIN。
- 自有 ASIN 对应的链接更容易被标记为原始主链接或被跟卖原链接。
- 如果店铺品牌关系缺失，例如 `pingter / Taipintee` 缺失，就会导致该 ASIN 只能靠 fallback 逻辑推断主链接，页面上可能出现“是 ASIN 合并目标，但是否被跟卖=否”的情况。

用户提供了最新文件：

```text
data/店铺综合信息.xlsx
```

该文件包含最新店铺与品牌对应关系，其中部分店铺同时存在英标和欧标品牌。

## 当前数据源

Excel 关键列：

| 列名 | 用途 |
| --- | --- |
| 店铺名 | 店铺名称 |
| 英标 | 英国站品牌 |
| 欧标 | 欧洲站品牌 |
| 是否补货 | 可保留为辅助字段 |
| 运营 | 可保留为辅助字段 |

当前初步扫描结果：

| 类型 | 数量 |
| --- | ---: |
| 有效店铺品牌行 | 63 |
| 英标欧标相同 | 29 |
| 英标欧标不同 | 3 |
| 只有一个品牌 | 31 |

英标欧标不同示例：

| 店铺名 | 规范化店铺名 | 英标 | 欧标 |
| --- | --- | --- | --- |
| Zhuoleel | Zhuoleel | ZLFGKPQ | Primesensearo |
| miqiao | miqiao | MEEQIAO | KkeMieQiao |
| pingter-eu | pingter | Taipintee | PtuaTcsce |

## 目标

将 Excel 中的店铺品牌对应关系整理后更新到：

```text
opt_db.store_brand_relation
```

并保证补货 ETL 后续可以正确生成：

```text
dashboard_replenishment_self_asin_sync
```

目标效果：

1. 一个店铺只有一个有效品牌时，只保存一条映射。
2. 一个店铺英标和欧标相同时，只保存一条映射。
3. 一个店铺英标和欧标不同且都有值时，保存两条映射。
4. 店铺名需要规范化，确保能匹配 listing 中的店铺名。
5. 不直接全表覆盖，降低影响范围。

## 生成规则

### 1. 品牌清洗

以下值视为空，不生成品牌映射：

```text
空字符串
#N/A
N/A
NULL
None
无
-
```

品牌值保留原始大小写，但前后空格需要去掉。

### 2. 店铺名规范化

listing 中用于匹配的店铺名来自：

```sql
substring_index(list.seller_name, '-', 1)
```

因此 Excel 中的店铺名需要规范化：

| Excel 店铺名 | 规范化店铺名 |
| --- | --- |
| pingter-eu | pingter |
| ouhao-eu | ouhao |
| Tboke-eu | Tboke |
| QINGLEE-EU | QINGLEE |

建议规则：

```text
去掉末尾 -eu / -EU / -uk / -UK
保留其它内容不变
```

同时保留原始店铺名用于追溯。

### 3. 品牌行生成

对每一行 Excel 数据：

```text
store_name = 规范化店铺名
uk_brand = 清洗后的英标
eu_brand = 清洗后的欧标
```

生成规则：

| 情况 | 生成结果 |
| --- | --- |
| 英标和欧标都为空 | 不生成 |
| 只有英标有值 | 生成 `store_name + 英标` |
| 只有欧标有值 | 生成 `store_name + 欧标` |
| 英标和欧标相同 | 生成一条 |
| 英标和欧标不同 | 生成两条 |

示例：

```text
pingter-eu
英标 = Taipintee
欧标 = PtuaTcsce
```

生成：

```text
pingter / Taipintee
pingter / PtuaTcsce
```

## 表设计建议

### 1. 预览表

先在测试库创建预览表，不直接写远端正式表：

```text
etl_datasync_replenishment_test.store_brand_relation_import_preview
```

建议字段：

| 字段 | 说明 |
| --- | --- |
| raw_store_name | Excel 原始店铺名 |
| store_name | 规范化店铺名 |
| brand_name | 品牌名 |
| brand_source | 英标 / 欧标 / 英标欧标相同 |
| is_replenish | Excel 是否补货 |
| operator_name | Excel 运营 |
| source_file | 来源文件 |
| imported_at | 导入时间 |

建议唯一约束：

```text
store_name + brand_name
```

### 2. 正式远端表

目标表仍为：

```text
opt_db.store_brand_relation
```

现有 ETL 依赖字段：

```text
店铺名
品牌名
是否补货
运营
```

本次只更新补货识别需要的店铺品牌映射，不改变补货 ETL 的读取表名。

## 更新策略

使用“备份后清空重建”，不做增量更新。

原因：

1. `data/店铺综合信息.xlsx` 是最新店铺品牌关系来源。
2. `opt_db.store_brand_relation` 本质是店铺品牌映射基础表，不需要保留 Excel 外的旧关系。
3. 增量更新容易残留旧品牌，反而会让自有 ASIN 识别范围不准确。

步骤：

1. 解析 Excel，生成规范化映射结果。
2. 写入测试库预览表。
3. 核对预览表数据。
4. 备份远端旧表数据。
5. 清空 `opt_db.store_brand_relation`。
6. 插入 Excel 生成的新映射。
7. 重新跑 `self_asin_sync`，让补货自有 ASIN 结果表重新生成。

这样可以保证远端表完全以最新 Excel 为准，不残留旧店铺旧品牌。

## 验证方案

### 1. 预览表验证

重点检查：

```text
pingter 是否生成 Taipintee 和 PtuaTcsce
miqiao 是否生成 MEEQIAO 和 KkeMieQiao
Zhuoleel 是否生成 ZLFGKPQ 和 Primesensearo
英标欧标相同的店铺是否只生成一条
#N/A 是否被过滤
-eu / -EU 后缀是否被规范化
```

### 2. 正式表更新前对比

生成差异清单：

| 类型 | 说明 |
| --- | --- |
| 新增 | Excel 中有，远端表没有 |
| 删除 | 远端旧表中存在，但 Excel 不再提供 |
| 保持 | Excel 和远端表一致 |
| 拆分 | 原来一店一品牌，现在一店两品牌 |

### 3. 补货 ETL 验证

更新后在测试库重新同步：

```text
self_asin_sync
replenishment_result
```

验证：

```text
dashboard_replenishment_self_asin_sync
```

重点检查：

| 店铺 | 品牌 | 预期 |
| --- | --- | --- |
| pingter | Taipintee | 应能生成自有 ASIN |
| pingter | PtuaTcsce | 应能生成自有 ASIN |
| miqiao | MEEQIAO | 应能生成自有 ASIN |
| miqiao | KkeMieQiao | 应能生成自有 ASIN |

### 4. 跟卖识别验证

重点回看此前异常案例：

```text
DJ0027a / B0CFQ2MFW4 / pingter / PT068a
```

预期：

1. `pingter / Taipintee` 有映射后，`B0CFQ2MFW4` 可以进入 `dashboard_replenishment_self_asin_sync`。
2. `PT068a` 不再只是 fallback 主链接。
3. 页面上的“是否被跟卖”应符合业务语义。

## 风险点

### 1. 店铺名规范化风险

如果某些店铺后缀不是 `-eu` 或 `-uk`，可能仍然匹配不上 listing。

应输出规范化前后对比表，人工确认。

### 2. 品牌大小写风险

当前匹配是：

```sql
store.`品牌名` = list.seller_brand
```

如果远端数据库排序规则大小写敏感，品牌大小写不同可能导致匹配失败。

建议预览时对品牌做精确匹配检查。

### 3. 清空重建风险

清空重建后，所有不在 Excel 中的旧店铺品牌关系都会被删除。

这是本次预期行为，但正式执行前仍需：

1. 备份旧表。
2. 输出旧表与新 Excel 生成表的差异清单。
3. 确认 Excel 已经覆盖当前应使用的全部店铺品牌关系。

### 4. 多品牌带来的 ASIN 扩大风险

一个店铺增加第二个品牌后，会让更多 ASIN 被识别为自有 ASIN。

这是本次目标，但需要在补货结果中抽样确认是否符合业务预期。

## 推荐执行顺序

1. 写 Excel 解析脚本，只生成预览表。
2. 跑预览，不改远端正式表。
3. 输出新增、删除、保持、拆分差异清单。
4. 人工确认差异清单。
5. 备份整张 `opt_db.store_brand_relation`。
6. 清空并重建远端表。
7. 重新跑测试库 `self_asin_sync` 和补货 ETL。
8. 验证 `PT068a` 等案例。
9. 确认后再安排正式库补货 ETL。

## 暂不做的事

本次规划不直接改：

```text
dashboard_replenishment_self_asin_sync
```

因为它是 ETL 结果表，应该通过更新 `opt_db.store_brand_relation` 后重新同步生成。

本次也不直接调整跟卖识别代码，先修正店铺品牌源数据，避免把源数据缺失和识别逻辑混在一起。
