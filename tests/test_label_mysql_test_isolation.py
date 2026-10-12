import pytest

from test_label_local_store_mysql import local_store


@pytest.mark.parametrize("opt_in", [None, "0", "yes"])
def test_mysql_fixture_requires_explicit_opt_in(monkeypatch, opt_in):
    if opt_in is None:
        monkeypatch.delenv("LABEL_LOCAL_MYSQL_TEST", raising=False)
    else:
        monkeypatch.setenv("LABEL_LOCAL_MYSQL_TEST", opt_in)

    def unexpected_connection():
        pytest.fail("MySQL connection attempted without explicit opt-in")

    monkeypatch.setattr(
        "etl.dashboard_daily_update.connect_target", unexpected_connection
    )
    fixture = local_store.__wrapped__()
    with pytest.raises(pytest.skip.Exception):
        next(fixture)
