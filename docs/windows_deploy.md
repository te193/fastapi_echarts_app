# Windows 部署说明

## 一键部署

在项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_windows.ps1
```

默认动作：

- 创建或复用 `.venv`
- 安装 `requirements.txt`
- 加载 `scripts\dashboard_env.ps1` 中的数据库与服务配置
- 测试本地写入库和远程只读源库连接
- 创建 Windows 定时任务 `DashboardDailyUpdate`
- 定时任务每天 `10:00` 执行 `scripts\run_daily_update_task.ps1`

## 常用命令

只安装环境和注册定时任务：

```powershell
.\scripts\deploy_windows.ps1
```

部署后立刻跑一次数据更新：

```powershell
.\scripts\deploy_windows.ps1 -RunUpdateNow
```

只手动跑一次数据更新：

```powershell
.\scripts\run_daily_update_task.ps1
```

启动局域网看板服务：

```powershell
.\scripts\run_web_server.ps1
```

如果需要自动放行 8000 端口，使用管理员 PowerShell 执行：

```powershell
.\scripts\deploy_windows.ps1 -OpenFirewall
```

## 数据更新策略

数据更新逻辑保持不变：

- 产品表现日表：每天回滚刷新最近 50 天
- 快照表：刷新当前快照日期
- 预计算周期表：刷新 7 天、14 天、30 天、90 天、上月
- 交叉矩阵汇总表：跟随预计算周期一起刷新
- 远程数据库只做查询，本地数据库负责建表、删除、插入和汇总

## 脚本目录

- `scripts\dashboard_env.ps1`：统一环境变量和数据库连接配置
- `scripts\deploy_windows.ps1`：Windows 部署入口
- `scripts\run_daily_update_task.ps1`：定时任务执行入口
- `scripts\run_web_server.ps1`：局域网服务启动入口
- `logs\`：数据更新日志目录
