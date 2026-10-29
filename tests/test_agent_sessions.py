"""Real temporary Git histories; container boundaries are mocked, never the Git logic."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest
from test_master_agent import master_helper, temporary_master
from test_template import command


def commit(path: Path, filename: str, contents: str) -> str:
    (path / filename).write_text(contents)
    command(path, "git", "add", filename)
    command(path, "git", "commit", "-m", f"change {filename}")
    return command(path, "git", "rev-parse", "HEAD").strip()


def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str = "both") -> ModuleType:
    project = temporary_master(tmp_path / "primary")
    helper = master_helper(project, profile)
    # No Podman is needed for these Git tests. Record exact runtime teardown argv.
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(helper, "compose", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(helper, "stop_session_runtime", lambda: helper.compose("down"))
    monkeypatch.setattr(helper, "running_containers", lambda: False)
    helper.prepare()
    helper.__dict__["runtime_calls"] = calls
    return helper


def test_current_session_does_not_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = session(tmp_path, monkeypatch)
    saved = helper.state()
    inode = (helper.WORKSPACE / ".git").stat().st_ino
    assert helper.prepare() == saved
    assert (helper.WORKSPACE / ".git").stat().st_ino == inode
    assert helper.runtime_calls == []


@pytest.mark.parametrize("profile", ["codex", "claude", "both", "custom"])
def test_stale_clean_auto_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    helper = session(tmp_path, monkeypatch, profile)
    old = helper.state()
    old["ports"] = {"app": 19283}
    old["preferred_ports"] = {"app": 18000}
    helper.STATE.write_text(json.dumps(old))
    # Even ignored files are retained without copying an entire tree elsewhere.
    (helper.WORKSPACE / ".env").write_text("private-local-setting\n")
    new_head = commit(helper.ROOT, "primary.txt", "new main\n")
    index = (helper.ROOT / ".git/index").read_bytes()
    fresh = helper.prepare()
    assert fresh["base"] == new_head and fresh["profile"] == profile
    assert fresh["branch"] != old["branch"]
    assert command(helper.WORKSPACE, "git", "rev-parse", "HEAD").strip() == new_head
    assert command(helper.ROOT, "git", "rev-parse", "HEAD").strip() == new_head
    assert (helper.ROOT / ".git/index").read_bytes() == index
    assert fresh["ports"] == old["ports"]
    assert fresh["preferred_ports"] == old["preferred_ports"]
    assert helper.runtime_calls == [("down",)]
    archived = next((helper.STATE_DIR / "archive").iterdir())
    assert (archived / "workspace/.env").read_text() == "private-local-setting\n"
    assert json.loads((archived / "state.json").read_text())["base"] == old["base"]


@pytest.mark.parametrize("work", ["dirty", "untracked", "commit", "empty", "operation"])
def test_stale_work_blocks_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, work: str
) -> None:
    helper = session(tmp_path, monkeypatch)
    if work == "dirty":
        (helper.WORKSPACE / "important.txt").write_text("unsaved\n")
    elif work == "untracked":
        (helper.WORKSPACE / "new.txt").write_text("untracked\n")
    elif work == "commit":
        commit(helper.WORKSPACE, "agent.txt", "agent-only\n")
    elif work == "empty":
        command(helper.WORKSPACE, "git", "commit", "--allow-empty", "-m", "intentional metadata")
    else:
        (helper.WORKSPACE / ".git/CHERRY_PICK_HEAD").write_text(helper.state()["base"])
    if work == "empty":
        assert helper.session_work(helper.state())[0] == 1
    head = command(helper.WORKSPACE, "git", "rev-parse", "HEAD")
    saved = helper.STATE.read_bytes()
    commit(helper.ROOT, "primary.txt", "advanced\n")
    with pytest.raises(ValueError, match="unapplied"):
        helper.prepare()
    assert helper.STATE.read_bytes() == saved
    assert command(helper.WORKSPACE, "git", "rev-parse", "HEAD") == head
    assert helper.runtime_calls == []
    if work == "dirty":
        assert (helper.WORKSPACE / "important.txt").read_text() == "unsaved\n"
    if work == "untracked":
        assert (helper.WORKSPACE / "new.txt").read_text() == "untracked\n"


def test_cherry_picked_agent_commit_can_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = session(tmp_path, monkeypatch)
    agent_head = commit(helper.WORKSPACE, "agent.txt", "integrated patch\n")
    commit(helper.ROOT, "primary.txt", "different parent ensures distinct cherry-pick hash\n")
    command(helper.ROOT, "git", "fetch", str(helper.WORKSPACE), helper.state()["branch"])
    command(helper.ROOT, "git", "cherry-pick", agent_head)
    primary = command(helper.ROOT, "git", "rev-parse", "HEAD").strip()
    assert primary != agent_head
    assert helper.prepare()["base"] == primary
    assert (helper.WORKSPACE / "agent.txt").read_text() == "integrated patch\n"


def test_agent_rebase_and_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = session(tmp_path, monkeypatch)
    commit(helper.WORKSPACE, "agent.txt", "agent change\n")
    primary = commit(helper.ROOT, "primary.txt", "primary change\n")
    original_config = (helper.WORKSPACE / ".git/config").read_bytes()
    helper.rebase_session()
    assert helper.state()["base"] == primary
    assert (helper.WORKSPACE / ".git/config").read_bytes() == original_config
    assert command(helper.WORKSPACE, "git", "rev-parse", "HEAD^").strip() == primary
    assert command(helper.ROOT, "git", "rev-parse", "HEAD").strip() == primary
    assert not (helper.ROOT / "agent.txt").exists()
    helper.apply()
    assert (helper.ROOT / "agent.txt").read_text() == "agent change\n"


def test_rebase_conflict_preserved_and_abort_recognized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = session(tmp_path, monkeypatch)
    old = helper.state()["base"]
    agent_head = commit(helper.WORKSPACE, "important.txt", "agent conflict\n")
    primary = commit(helper.ROOT, "important.txt", "primary conflict\n")
    with pytest.raises(ValueError, match="rebase stopped because of conflicts"):
        helper.rebase_session()
    assert helper.git_operation() == "rebase-merge"
    assert helper.state()["base"] == old
    assert helper.state()["pending_rebase_base"] == primary
    assert "<<<<<<<" in (helper.WORKSPACE / "important.txt").read_text()
    assert (helper.ROOT / "important.txt").read_text() == "primary conflict\n"
    assert command(helper.ROOT, "git", "rev-parse", "HEAD").strip() == primary
    command(helper.WORKSPACE, "git", "rebase", "--abort")
    assert helper.finish_rebase(helper.state())["base"] == old
    assert command(helper.WORKSPACE, "git", "rev-parse", "HEAD").strip() == agent_head


def test_archive_keeps_dirty_work_and_allows_new_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = session(tmp_path, monkeypatch)
    (helper.WORKSPACE / "important.txt").write_text("keep this dirty work\n")
    helper.archive_session()
    assert not helper.STATE.exists() and not helper.WORKSPACE.exists()
    archived = next((helper.STATE_DIR / "archive").iterdir())
    assert (archived / "workspace/important.txt").read_text() == "keep this dirty work\n"
    assert helper.prepare()["base"] == command(helper.ROOT, "git", "rev-parse", "HEAD").strip()
    assert helper.runtime_calls == [("down",)]


def test_completed_conflict_resolution_updates_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = session(tmp_path, monkeypatch)
    commit(helper.WORKSPACE, "important.txt", "agent conflict\n")
    primary = commit(helper.ROOT, "important.txt", "primary conflict\n")
    with pytest.raises(ValueError, match="rebase stopped"):
        helper.rebase_session()
    (helper.WORKSPACE / "important.txt").write_text("explicit resolution\n")
    command(helper.WORKSPACE, "git", "add", "important.txt")
    command(helper.WORKSPACE, "git", "-c", "core.editor=true", "rebase", "--continue")
    assert helper.prepare()["base"] == primary
    assert (helper.WORKSPACE / "important.txt").read_text() == "explicit resolution\n"
    assert (helper.ROOT / "important.txt").read_text() == "primary conflict\n"


def test_explicit_refresh_refuses_current_dirty_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = session(tmp_path, monkeypatch)
    (helper.WORKSPACE / "important.txt").write_text("do not remove\n")
    with pytest.raises(ValueError, match="unapplied"):
        helper.refresh()
    assert (helper.WORKSPACE / "important.txt").read_text() == "do not remove\n"
    assert helper.runtime_calls == []


def test_stale_session_status_is_non_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helper = session(tmp_path, monkeypatch)
    commit(helper.ROOT, "primary.txt", "advance\n")
    saved = helper.STATE.read_bytes()
    assert helper.report_session(helper.state())
    output = capsys.readouterr().out
    assert "Agent session: stale" in output
    assert "Safe automatic refresh available" in output
    assert helper.STATE.read_bytes() == saved
    assert helper.runtime_calls == []


def test_grafts_disabled_without_deprecation_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helper = session(tmp_path, monkeypatch)
    commit(helper.WORKSPACE, "agent.txt", "second commit\n")
    head = command(helper.WORKSPACE, "git", "rev-parse", "HEAD").strip()
    (helper.WORKSPACE / ".git/info/grafts").write_text(head + "\n")
    assert helper.git(helper.WORKSPACE, "rev-list", "--count", "HEAD") == "2"
    assert "graft" not in capsys.readouterr().err.lower()


def test_no_runtime_change_after_shutdown_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = session(tmp_path, monkeypatch)
    old = helper.state()
    commit(helper.ROOT, "primary.txt", "advanced\n")
    monkeypatch.setattr(
        helper,
        "stop_session_runtime",
        lambda: (helper.WORKSPACE / "late.txt").write_text("late agent write\n"),
    )
    with pytest.raises(ValueError, match="unapplied"):
        helper.refresh()
    assert helper.state() == old
    assert (helper.WORKSPACE / "late.txt").read_text() == "late agent write\n"


def test_rebase_does_not_execute_clone_merge_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = session(tmp_path, monkeypatch)
    commit(helper.WORKSPACE, "important.txt", "agent\n")
    commit(helper.ROOT, "important.txt", "primary\n")
    marker = tmp_path / "host-code-must-not-run"
    command(helper.WORKSPACE, "git", "config", "merge.evil.driver", f"touch {marker}")
    (helper.WORKSPACE / ".git/info/attributes").write_text("* merge=evil\n")
    with pytest.raises(ValueError, match="rebase stopped"):
        helper.rebase_session()
    assert not marker.exists()


def test_host_inspection_does_not_execute_clone_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = session(tmp_path, monkeypatch)
    marker = tmp_path / "host-filter-must-not-run"
    command(helper.WORKSPACE, "git", "config", "filter.evil.clean", f"touch {marker}; cat")
    command(helper.WORKSPACE, "git", "config", "filter.evil.required", "true")
    (helper.WORKSPACE / ".git/info/attributes").write_text("* filter=evil\n")
    (helper.WORKSPACE / "important.txt").write_text("unsaved\n")
    commit(helper.ROOT, "primary.txt", "primary advanced\n")
    with pytest.raises(ValueError, match="unapplied"):
        helper.prepare()
    assert not marker.exists()
    assert (helper.WORKSPACE / "important.txt").read_text() == "unsaved\n"
