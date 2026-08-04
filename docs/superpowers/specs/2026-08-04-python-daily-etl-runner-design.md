# Python 每日 ETL 汇总调度器设计

## 目标

新增一个不依赖 PowerShell 的 Python 每日 ETL 汇总入口。当
`scripts/run_daily_update_task.ps1` 无法使用时，可以直接执行：

```powershell
python -m etl.daily_update_runner
```

该入口应与现有 PowerShell 每日任务保持相同的核心执行顺序、失败处理、
日志保存和钉钉通知行为。

## 范围

本次只新增 Python 调度能力，不修改各 ETL 模块的业务逻辑、数据库 SQL、
定时任务注册方式和现有 PowerShell 脚本。

调度器负责依次执行：

1. `etl.dashboard_source_preflight`
2. `etl.dashboard_daily_update`
3. `etl.product_performance_history_sync`
4. `etl.sales_role_snapshot_update`
5. `etl.label_rule_evidence_snapshot_update`
6. `etl.replenishment_update`
7. `etl.replenishment_tracking_summary_update`
8. `etl.return_goods_update`

## 架构

新增 `etl/daily_update_runner.py` 作为独立调度器。调度器使用当前 Python
解释器通过 `subprocess` 启动每个 ETL 模块，使各步骤具有独立进程、
独立退出码和独立日志，避免某个模块修改进程内全局状态后影响后续模块。

调度器不调用 PowerShell。现有 `scripts/notify_daily_task_dingtalk.py`
继续作为钉钉消息生成和发送入口，保证 Python 与 PowerShell 两种启动方式
使用同一套通知模板。

## 命令行接口

正式执行：

```powershell
python -m etl.daily_update_runner
```

流程验证：

```powershell
python -m etl.daily_update_runner --dry-run
```

`--dry-run` 会继续传递给支持该参数的现有 ETL 模块，按当前每日任务的
验证口径执行，不写业务结果表，并跳过钉钉通知。

除调度器自身参数外，其余参数原样传递给各 ETL 模块，以保持现有
`--steps`、日期参数及其他 ETL 参数的使用能力。

## 执行提示

控制台在每一步输出：

- 当前步骤序号和总步骤数
- 中文步骤名称和 Python 模块名
- 开始时间
- 完成时间
- 单步耗时
- 成功、警告或失败状态
- 标准输出日志和错误日志路径

全部结束后输出总耗时和各步骤结果汇总。失败时额外输出失败步骤、
退出码和错误日志位置。

## 日志

日志继续写入项目 `logs` 目录，并沿用现有钉钉脚本能够识别的文件前缀：

- `etl_source_preflight_run_<批次>.log`
- `etl_daily_run_<批次>.log`
- `etl_product_history_run_<批次>.log`
- `etl_sales_role_run_<批次>.log`
- `etl_label_rule_evidence_run_<批次>.log`
- `etl_replenishment_run_<批次>.log`
- `etl_replenishment_tracking_summary_run_<批次>.log`
- `etl_return_goods_run_<批次>.log`

每一步同时生成对应的 `.err.log`。子进程输出既写入日志，也实时显示到
当前控制台，便于人工观察进度。

## 失败与警告处理

以下步骤失败时立即停止后续流程，并发送失败通知：

- 远端数据预检
- 看板总 ETL
- 产品表现历史同步
- 销售角色/生命周期
- 补货 ETL
- 补货追踪汇总
- 返厂品 ETL

标签规则证据步骤保持现有 PowerShell 行为：失败时记录警告并发送对应
失败通知，但不阻断后续补货和返厂品流程。

调度器自身出现无法创建日志、无法启动 Python 子进程等异常时，返回非零
退出码，并尽可能发送失败通知。

## 钉钉通知

调度器在结束时调用 `scripts/notify_daily_task_dingtalk.py`：

- 全部必需步骤成功：发送成功通知，阶段为 `all`
- 阻断步骤失败：发送失败通知，阶段对应失败模块
- 标签证据步骤失败：发送一次该阶段失败通知，后续流程继续；最终必需步骤
  均成功时仍发送完整流程成功通知
- `--dry-run`：不发送任何钉钉通知

通知调用失败不改变 ETL 的原始执行结果，但在控制台显示警告。

## 退出码

- 全部必需步骤成功：`0`
- 必需 ETL 步骤失败：返回该步骤的非零退出码
- 调度器自身异常：`1`

## 测试

新增单元测试覆盖：

- 默认步骤顺序与 PowerShell 当前顺序一致
- 每一步使用当前 Python 解释器和 `-m` 模块方式启动
- 成功时继续执行全部步骤
- 必需步骤失败时停止后续步骤并返回原退出码
- 标签证据失败时继续后续步骤
- `--dry-run` 不发送钉钉通知
- 成功和失败通知收到正确阶段、日志路径及批次号
- 额外命令行参数能够传递给 ETL 子进程
- 控制台汇总包含步骤状态与耗时

验证时不运行真实写库 ETL；子进程执行和通知发送通过依赖注入替代，
确保测试不会修改数据库或发送真实钉钉消息。

