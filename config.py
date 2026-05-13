"""Dashboard database and schema configuration.

All settings can be overridden via environment variables.
To change database credentials, edit this file directly.
"""

import os

# Target database (local, dashboard writes here)
DASHBOARD_DB_HOST = os.getenv("DASHBOARD_DB_HOST", "192.168.112.235")
DASHBOARD_DB_PORT = int(os.getenv("DASHBOARD_DB_PORT", "3306"))
DASHBOARD_DB_USER = os.getenv("DASHBOARD_DB_USER", "lanuser")
DASHBOARD_DB_PASSWORD = os.getenv("DASHBOARD_DB_PASSWORD", "123456")
_DASHBOARD_DB_NAME_RAW = (
    os.getenv("DASHBOARD_DB_NAME") or os.getenv("MYSQL_DATABASE") or "etl_datasync_test"
)
DASHBOARD_DB_NAME = _DASHBOARD_DB_NAME_RAW or None
DASHBOARD_DB_CHARSET = os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4")

# Source database (remote, read-only)
DASHBOARD_SOURCE_DB_HOST = os.getenv("DASHBOARD_SOURCE_DB_HOST", "127.0.0.1")
DASHBOARD_SOURCE_DB_PORT = int(os.getenv("DASHBOARD_SOURCE_DB_PORT", "3306"))
DASHBOARD_SOURCE_DB_USER = os.getenv("DASHBOARD_SOURCE_DB_USER", "")
DASHBOARD_SOURCE_DB_PASSWORD = os.getenv("DASHBOARD_SOURCE_DB_PASSWORD", "")
DASHBOARD_SOURCE_DB_NAME = os.getenv("DASHBOARD_SOURCE_DB_NAME", "") or None
DASHBOARD_SOURCE_DB_CHARSET = os.getenv(
    "DASHBOARD_SOURCE_DB_CHARSET",
    os.getenv("DASHBOARD_DB_CHARSET", "utf8mb4"),
)

# Schema names
DASHBOARD_TARGET_SCHEMA = os.getenv(
    "DASHBOARD_TARGET_SCHEMA", DASHBOARD_DB_NAME or "etl_datasync_test"
)
DASHBOARD_ETL_SOURCE_SCHEMA = os.getenv("DASHBOARD_ETL_SOURCE_SCHEMA", "etl_datasync")
DASHBOARD_DWD_SOURCE_SCHEMA = os.getenv("DASHBOARD_DWD_SOURCE_SCHEMA", "dwd_datasync")
DASHBOARD_PRICING_SOURCE_SCHEMA = os.getenv(
    "DASHBOARD_PRICING_SOURCE_SCHEMA", "temporary_APP"
)

# Dashboard defaults
DASHBOARD_DEFAULT_PERIOD_DAYS = int(os.getenv("DASHBOARD_DEFAULT_PERIOD_DAYS", "90"))
