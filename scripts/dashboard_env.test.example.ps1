$ErrorActionPreference = "Stop"

# Copy this file to scripts\dashboard_env.test.ps1 when a test server needs
# settings that differ from the application server. Keep secrets out of git.

# Test web server. The test runner also forces DASHBOARD_PORT to 8001 after
# loading the normal dashboard environment, so this is only needed when you
# want a different test port.
# $env:DASHBOARD_HOST = "127.0.0.1"
# $env:DASHBOARD_PORT = "8001"

# First phase: reuse the same local database as the application server.
# Uncomment these only after a separate test database is created.
# $env:DASHBOARD_DB_NAME = "etl_datasync_test_dev"
# $env:DASHBOARD_TARGET_SCHEMA = "etl_datasync_test_dev"
