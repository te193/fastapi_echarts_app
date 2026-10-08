# 本地目标库名称直写设计

## 目标

将 Python 业务代码中本地看板目标表的基准名称从
`etl_datasync.dashboard_*` 改为当前实际使用的
`etl_datasync_test.dashboard_*`，让代码中的名称与本地数据库一致，减少阅读误解。

## 范围

- 本地看板目标表 `dashboard_*` 统一使用 `etl_datasync_test`。
- 本地补货计算结果表 `pur_plan_*` 统一使用 `etl_datasync_test`。
- 远端源表 `etl_datasync.etl_dispose_*` 保持不变。
- 远端 DWD 表、定价表及其 Schema 配置保持不变。
- 不修改数据库结构、表数据、字段口径或 ETL 执行顺序。

## 兼容方式

`etl_datasync_test` 作为代码中的默认目标 Schema 基准名。`render_sql()` 和
`render_replenishment_sql()` 仍根据 `DASHBOARD_TARGET_SCHEMA` 渲染目标表，因此临时测试库
或其他部署环境仍可覆盖目标 Schema。

例如：

```text
代码基准名：
etl_datasync_test.dashboard_inventory_daily_snapshot

默认执行：
etl_datasync_test.dashboard_inventory_daily_snapshot

临时配置 DASHBOARD_TARGET_SCHEMA=etl_datasync_replenishment_test 后：
etl_datasync_replenishment_test.dashboard_inventory_daily_snapshot
```

远端源表不会参与上述目标 Schema 替换：

```text
etl_datasync.etl_dispose_lx_storage_fba_warehouse_detail
```

## 验证

- 新增目标 Schema 渲染测试，先验证旧逻辑无法识别新的基准名。
- 检查 Python 运行代码中不再出现 `etl_datasync.dashboard_*`。
- 检查 `etl_datasync.etl_dispose_*` 仍然存在且不被改成本地库。
- 运行看板每日 ETL、补货 ETL、返厂品、销售角色及服务层相关测试。
- 运行完整测试集，确认没有 SQL 字符串断言或行为回归。
