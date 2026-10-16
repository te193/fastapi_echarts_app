"""Imported fixtures must preserve their opt-in boundary before opening a database."""
from unittest.mock import MagicMock

import pytest

from test_label_local_store_mysql import local_store


def test_imported_mysql_fixture_skips_before_loading_business_credentials(monkeypatch):
    from etl import dashboard_daily_update, replenishment_update
    monkeypatch.delenv('LABEL_LOCAL_MYSQL_TEST', raising=False)
    connect = MagicMock(side_effect=AssertionError('business DB must never be reached by default tests'))
    load_config = MagicMock(side_effect=AssertionError('business credentials must not be loaded'))
    monkeypatch.setattr(dashboard_daily_update, 'connect_target', connect)
    monkeypatch.setattr(replenishment_update, 'apply_database_ini_env', load_config)
    with pytest.raises(pytest.skip.Exception, match='opt-in'):
        next(local_store.__wrapped__())
    load_config.assert_not_called()
    connect.assert_not_called()
