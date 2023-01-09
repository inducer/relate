import pytest


# from pytest_factoryboy import register


def pytest_addoption(parser):
    parser.addoption(
        "--slow", action="store_true", default=False, help="run slow tests",
    )
    parser.addoption(
        "--all", action="store_true", default=False, help="run all tests",
    )


def _is_connection_psql():
    from django.db import connection
    return connection.vendor == 'postgresql'


def pytest_collection_modifyitems(config, items):
    skip_pg = pytest.mark.skip(reason="connection is not a postgres database")
    if not _is_connection_psql():
        for item in items:
            if "postgres" in item.keywords:
                item.add_marker(skip_pg)

    if config.getoption("--all"):
        return
    elif config.getoption("--slow"):
        skip_non_slow = pytest.mark.skip(reason="need --slow option to run")
        for item in items:
            if "slow" not in item.keywords:
                item.add_marker(skip_non_slow)
    else:
        skip_slow = pytest.mark.skip(reason="need --slow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
