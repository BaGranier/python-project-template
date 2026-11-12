"""Host-only master dogfooding; no engine socket is exposed to the sandbox."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from test_master_agent import master_helper
from test_template import (
    ROOT,
    command,
    initialize,
    runtime_cleanup,
)

pytestmark = pytest.mark.runtime


def test_master_container_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not shutil.which("podman"):
        pytest.skip(
            "Host-only dogfooding: Podman engine intentionally unavailable in agent/bootstrap"
        )

    info = subprocess.run(["podman", "info", "--format", "json"], capture_output=True, text=True)
    if info.returncode or not json.loads(info.stdout)["host"]["security"]["rootless"]:
        pytest.skip("Host-only dogfooding requires usable rootless Podman")
    # Never start a lifecycle against the real template checkout in a test.
    project = tmp_path / "master"
    shutil.copytree(
        ROOT,
        project,
        ignore=shutil.ignore_patterns(
            ".git",
            ".agent",
            ".venv",
            ".env",
            "generated",
            "__pycache__",
            ".*cache",
            "Dockerfile.dev",
            "docker-compose.yaml",
        ),
    )
    initialize(project)
    helper = master_helper(project)
    # A host may already have the real master sandbox running. Never share its
    # Compose project, image or credentials, even when testing a copied master.
    slug = f"master-runtime-{uuid4().hex[:12]}"
    manifest = project / "containers/compose.agent.yaml"
    manifest.write_text(manifest.read_text().replace("python-project-template", slug))
    monkeypatch.setattr(helper, "IMAGE", helper.IMAGE.replace("python-project-template", slug))
    command(project, "git", "add", ".")
    command(project, "git", "commit", "-m", "test: isolate runtime resources")
    monkeypatch.setenv("AGENT_APP_PORT", "18000")
    with runtime_cleanup(lambda: helper.compose("down", "--volumes")):
        helper.start()
        assert helper.compose("exec", "-T", "agent", "id", "-u", capture=True) == "1000"
        helper.compose("exec", "-T", "agent", "make", "check")
        for agent in helper.AGENTS.values():
            helper.compose("exec", "-T", "agent", "touch", agent.config_dir + "/sentinel")
        for path in ("/home/agent/.cache/uv", "/opt/venv"):
            helper.compose("exec", "-T", "agent", "touch", path + "/persistent-sentinel")
        helper.compose("exec", "-T", "agent", "mkdir", "-p", "/tmp/template-disposable-test")
        helper.compose(
            "exec",
            "-T",
            "agent",
            "dd",
            "if=/dev/zero",
            "of=/tmp/template-disposable-test/blob",
            "bs=1M",
            "count=100",
        )
        stop_state = helper.STATE.read_bytes()
        monkeypatch.setattr(sys, "argv", ["agent.py", "stop"])
        helper.main()
        assert helper.agent_container() is None
        assert helper.STATE.read_bytes() == stop_state
        (helper.WORKSPACE / "harness-work.txt").write_text("preserve workspace\n")
        saved_state = helper.STATE.read_bytes()
        pins = helper.harness_versions()
        helper.update("codex", pins["CODEX_VERSION"])
        assert helper.STATE.read_bytes() == saved_state
        assert (helper.WORKSPACE / "harness-work.txt").read_text() == "preserve workspace\n"
        before = helper.VERSIONS_FILE.read_bytes()
        with pytest.raises(subprocess.CalledProcessError):
            helper.update("codex", "999999.0.0")
        assert helper.VERSIONS_FILE.read_bytes() == before
        assert helper.STATE.read_bytes() == saved_state
        helper.start()
        helper.compose(
            "exec", "-T", "agent", "test", "!", "-e", "/tmp/template-disposable-test/blob"
        )
        for path in ("/home/agent/.cache/uv", "/opt/venv"):
            helper.compose("exec", "-T", "agent", "test", "-f", path + "/persistent-sentinel")
        for name, agent in helper.AGENTS.items():
            actual = helper.compose("exec", "-T", "agent", agent.cli, "--version", capture=True)
            assert helper.parsed_version(name, actual) == pins[helper.VERSION_KEYS[name]]
        helper.compose(
            "exec",
            "-T",
            "agent",
            "python",
            "-c",
            "import os; assert not os.access('/usr/local/bin', os.W_OK); "
            "assert not os.access('/usr/local/lib/node_modules', os.W_OK)",
        )
        for agent in helper.AGENTS.values():
            helper.compose("exec", "-T", "agent", "test", "-f", agent.config_dir + "/sentinel")
        helper.compose("exec", "-T", "agent", "curl", "--fail", "-I", "https://example.com")
        helper.compose(
            "exec",
            "-T",
            "agent",
            "python",
            "-c",
            "import os; assert os.environ['HOME'] == '/home/agent'; "
            "assert not os.path.exists('/var/run/docker.sock'); "
            "assert not os.path.exists('/run/podman/podman.sock')",
        )
        container = helper.agent_container()
        assert container is not None
        binds = [mount for mount in container["Mounts"] if mount["Type"] == "bind"]
        assert len(binds) == 1 and Path(binds[0]["Source"]).resolve() == helper.WORKSPACE
        assert set(helper.published_ports(container)) == {"app"}
