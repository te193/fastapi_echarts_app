# FastAPI ECharts 产品结构看板

## 目录

- `app/`：FastAPI 应用、模板、静态资源
- `etl/`：数据更新 Python 逻辑，更新策略保持不变
- `scripts/`：Windows 部署、启动、定时任务脚本
- `docs/`：指标口径、更新方案、部署说明
- `logs/`：ETL 执行日志
- `sqlcode/`：原始 SQL 代码
- `backups/`：版本备份

## Windows 一键部署

在项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_windows.ps1
```

部署脚本会创建或复用 `.venv`，安装依赖，加载本地库和远程只读库配置，测试连接，并创建每天早上 `10:00` 执行的 Windows 定时任务 `DashboardDailyUpdate`。

更多参数见 [Windows 部署说明](docs/windows_deploy.md)。

## 开发与测试依赖

运行测试前安装开发依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 手动启动

启动局域网看板服务：

```powershell
.\scripts\run_web_server.ps1
```

本机访问：

```text
http://127.0.0.1:8000
```

同一局域网访问：

```text
http://你的本机局域网IP:8000
```

## 测试版启动

新需求先在测试版预览，默认端口 `8001`：

```powershell
.\scripts\run_web_server_test.ps1
```

完整隔离开发建议先创建测试 worktree，再在测试目录启动测试版：

```powershell
.\scripts\setup_test_worktree.ps1 -BaseBranch release -BranchName test\summary-page
cd .worktrees\dashboard-test
.\scripts\run_web_server_test.ps1
```

版本控制和发布流程见 [应用版 / 测试版版本控制流程](docs/version_control_workflow.md)。

## 手动更新数据

```powershell
.\scripts\run_daily_update_task.ps1
```

如果 PowerShell 启动脚本不可用，可以直接运行独立的 Python 汇总调度器：

```powershell
python -m etl.daily_update_runner
```

只验证完整流程、不写业务结果表且不发送钉钉通知：

```powershell
python -m etl.daily_update_runner --dry-run
```

两个入口执行相同的每日 ETL 顺序。Python 入口会显示每一步的开始时间、
完成状态、耗时和日志位置，失败时立即停止必需步骤并保留原退出码。

数据更新策略：

- 产品表现日表每天回滚刷新最近 50 天
- 快照表刷新当前快照日期
- 预计算周期表刷新 7 天、14 天、30 天、90 天、上月
- 交叉矩阵汇总表跟随周期表刷新
- 远程数据库只做查询，本地数据库负责写入和汇总
