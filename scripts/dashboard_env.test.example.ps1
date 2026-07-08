$ErrorActionPreference = "Stop"

# Copy this file to scripts\dashboard_env.test.ps1 when a test server needs
# settings that differ from the application server. Keep secrets out of git.

# Test web server. The test runner also forces DASHBOARD_PORT to 8001 after
# loading the normal dashboard environment, so this is only needed when you
# want a different test port.
# $env:DASHBOARD_HOST = "127.0.0.1"
# $env:DASHBOARD_PORT = "8001"

# Replenishment ETL validation must use an isolated schema, not the
# application database etl_datasync_test.
# $env:DASHBOARD_DB_NAME = "etl_datasync_replenishment_test"
# $env:DASHBOARD_TARGET_SCHEMA = "etl_datasync_replenishment_test"
