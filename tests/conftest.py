"""Keep child commands independent from the generator's container environment."""

import pytest


@pytest.fixture(autouse=True)
def isolate_child_uv_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Parent pytest is already running in /opt/venv. Even commands testing an
    # expected failure can invoke uv before failing; never let them sync there.
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
