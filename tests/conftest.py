"""Retain tmp_path diagnostics for failures in setup, call *or* teardown."""

from __future__ import annotations

import re
import shutil
from collections.abc import Generator
from pathlib import Path

import pytest

_TEMP_PATH = pytest.StashKey[Path]()
_FAILED = pytest.StashKey[bool]()


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    # pytest 9.1's builtin fixture deletes successful call data before teardown
    # errors are known, and treats missing call reports after setup errors as passed.
    # The factory still owns numbering, retention count, locking and session cleanup.
    name = re.sub(r"[\W]", "_", request.node.name)[:30]
    path = tmp_path_factory.mktemp(name, numbered=True)
    request.node.stash[_TEMP_PATH] = path
    return path


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    report = yield
    item.stash[_FAILED] = item.stash.get(_FAILED, False) or report.failed
    if report.when == "teardown" and _TEMP_PATH in item.stash:
        policy = item.config.getini("tmp_path_retention_policy")
        if policy == "none" or (policy == "failed" and not item.stash[_FAILED]):
            shutil.rmtree(item.stash[_TEMP_PATH], ignore_errors=True)
    return report


@pytest.fixture(autouse=True)
def isolate_child_uv_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    # Parent pytest may run in the agent's /opt/venv. Child uv commands must
    # select their own project's environment, including expected failures.
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
