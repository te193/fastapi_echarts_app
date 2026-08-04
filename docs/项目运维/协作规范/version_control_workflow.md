# 应用版 / 测试版版本控制流程

## 目标

当前给别人使用的看板作为应用版，后续新需求先进入测试版。测试通过后再发布到应用版，避免直接改坏正在使用的页面。

## 环境划分

| 环境 | 用途 | 默认端口 | 启动脚本 |
| --- | --- | --- | --- |
| 应用版 | 给使用者访问的稳定版本 | `8000` | `scripts\run_web_server.ps1` |
| 测试版 | 新功能开发、验收、截图确认 | `8001` | `scripts\run_web_server_test.ps1` |

测试版默认复用应用版数据库配置，只隔离 Web 端口。需要测试 ETL 写库时，再创建单独测试库，并在 `scripts\dashboard_env.test.ps1` 里覆盖 `DASHBOARD_DB_NAME` 和 `DASHBOARD_TARGET_SCHEMA`。

## 推荐分支

- `release`：应用版稳定分支，只放已经验收的代码。
- `test/<feature>` 或 `codex/<feature>`：测试版开发分支。
- 发布 tag：`app-vYYYY-MM-DD-说明`，例如 `app-v2026-06-04-stable`。

## 首次固定当前应用版

先确认当前页面就是要给别人用的应用版，然后执行：

```powershell
git status
git add <确认要纳入应用版的文件>
git commit -m "Freeze current application dashboard version"
git branch release
.\scripts\release_app_version.ps1 -TagName app-v2026-06-04-stable -ReleaseBranch release
```

如果当前有未提交改动，不要直接 `git add .`。先逐个确认哪些文件属于当前应用版。

## 创建测试版工作区

应用版固定后，在项目根目录执行：

```powershell
.\scripts\setup_test_worktree.ps1 -BaseBranch release -BranchName test\summary-page
cd .worktrees\dashboard-test
.\scripts\run_web_server_test.ps1
```

测试版地址：

```text
http://127.0.0.1:8001
```

应用版继续使用：

```text
http://127.0.0.1:8000
```

## 新需求开发流程

1. 从 `release` 创建测试分支或测试 worktree。
2. 在测试版 `8001` 完成功能开发和页面验收。
3. 发布前运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

4. 验收通过后，合并测试分支到 `release`。
5. 在 `release` 分支执行：

```powershell
.\scripts\release_app_version.ps1 -TagName app-v2026-06-10-summary-page -ReleaseBranch release
.\scripts\run_web_server.ps1
```

## 回退应用版

如果发布后异常，切回上一个 tag：

```powershell
git switch release
git reset --hard <上一个app-v标签>
.\scripts\run_web_server.ps1
```

注意：`git reset --hard` 会丢弃当前未提交改动。执行前必须确认没有需要保留的工作。

## 快速本地测试版

如果只是短时间看页面，可以直接在当前目录启动测试版：

```powershell
.\scripts\run_web_server_test.ps1
```

但这不是完整隔离。模板和静态文件仍来自同一目录，应用版长期运行时也可能读到磁盘上的新静态文件。正式新需求应使用测试 worktree。
