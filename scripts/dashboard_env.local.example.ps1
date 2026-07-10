$ErrorActionPreference = "Stop"

# Copy this file to scripts\dashboard_env.local.ps1 and override only the
# values that differ on the deployment machine.

# Local write database.
# $env:DASHBOARD_DB_HOST = "127.0.0.1"
# $env:DASHBOARD_DB_PORT = "3306"
# $env:DASHBOARD_DB_USER = "dashboard_writer"
# $env:DASHBOARD_DB_PASSWORD = "change-me"
# $env:DASHBOARD_DB_NAME = "etl_datasync_test"

# Remote read-only source database.
# $env:DASHBOARD_SOURCE_DB_HOST = "your_remote_host"
# $env:DASHBOARD_SOURCE_DB_PORT = "3306"
# $env:DASHBOARD_SOURCE_DB_USER = "readonly_user"
# $env:DASHBOARD_SOURCE_DB_PASSWORD = "change-me"
# $env:DASHBOARD_SOURCE_DB_NAME = ""

# Web server.
# $env:DASHBOARD_HOST = "0.0.0.0"
# $env:DASHBOARD_PORT = "8000"

# Optional DingTalk robot notifications for scripts\run_daily_update_task.ps1.
# $env:DASHBOARD_DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=..."
# $env:DASHBOARD_DINGTALK_SECRET = "SEC..."
