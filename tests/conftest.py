import pytest

from config.settings.embedded_postgres import cleanup


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del session, exitstatus
    cleanup()
