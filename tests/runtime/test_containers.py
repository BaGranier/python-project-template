"""Real engines only. Keep all four providers and multi-project isolation coverage."""

from __future__ import annotations

import json
import shutil
import subprocess
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from test_template import (
    command,
    configure_agent,
    dynamic_ports,
    git_identity_environment,
    runtime_cleanup,
)
from test_template import (
    generate_locked as generate,
)

pytestmark = pytest.mark.runtime


def test_dev_container_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = shutil.which("podman") or shutil.which("docker")
    if not runtime:
        pytest.skip("Docker and Podman unavailable: dev build/start/import not executed")
    usable = subprocess.run([runtime, "info"], capture_output=True, check=False)
    if usable.returncode:
        pytest.skip("Container engine installed but unusable in this environment")
    for key, value in dynamic_ports("DEV").items():
        monkeypatch.setenv(key, value)
    project = generate(
        tmp_path,
        dev_container_runtime=Path(runtime).name,
        project_slug=f"runtime-dev-{uuid4().hex[:12]}",
        package_name="my_python_project",
    )
    # An exported user COMPOSE_PROJECT_NAME must not redirect cleanup to a real stack.
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", f"{project.name}-dev")
    command(project, "make", "setup")
    prefix = (runtime, "compose", "--env-file", ".env", "-f", "containers/compose.yaml")
    with runtime_cleanup(lambda: command(project, *prefix, "down", "--volumes")):
        command(project, "make", "dev-up")
        command(project, *prefix, "exec", "-T", "dev", "uv", "sync", "--locked")
        command(
            project,
            *prefix,
            "exec",
            "-T",
            "dev",
            "uv",
            "run",
            "python",
            "-c",
            "import my_python_project",
        )
        assert command(project, *prefix, "exec", "-T", "dev", "id", "-u").strip() != "0"


@pytest.mark.parametrize("provider", ["codex", "claude", "both", "custom"])
def test_agent_container_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    if not shutil.which("podman"):
        pytest.skip("Podman unavailable: agent/security/HTTP-port runtime tests not executed")
    info = subprocess.run(
        ["podman", "info", "--format", "json"], text=True, capture_output=True, check=False
    )
    if info.returncode or not json.loads(info.stdout).get("host", {}).get("security", {}).get(
        "rootless"
    ):
        pytest.skip("Usable rootless Podman unavailable")
    for key, value in dynamic_ports("AGENT").items():
        monkeypatch.setenv(key, value)
    project = generate(
        tmp_path,
        project_slug=f"runtime-agent-{uuid4().hex[:12]}",
        package_name="my_python_project",
        coding_agent=provider,
    )
    if provider == "custom":
        (project / "containers/agent-custom-install.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "mkdir -p /opt/agent-tools/bin\n"
            "printf '%s\\n' '#!/bin/sh' 'echo fake-harness \"$PWD\" \"$@\"' "
            "> /opt/agent-tools/bin/fake-harness\n"
            "chmod +x /opt/agent-tools/bin/fake-harness\n"
        )
    command(project, "make", "init", env=git_identity_environment(tmp_path))
    helper = configure_agent(project)
    with runtime_cleanup(lambda: helper.compose("down", "--volumes")):
        command(project, "make", "agent-check")
        command(project, "make", "agent-start")
        assert helper.compose("exec", "-T", "agent", "id", "-u", capture=True) == "1000"
        helper.compose("exec", "-T", "agent", "make", "check")
        for agent in helper.AGENTS.values():
            helper.compose("exec", "-T", "agent", agent.cli, "--version")
        if provider == "custom":
            helper.compose(
                "exec",
                "-T",
                "agent",
                "python",
                "-c",
                "import shutil; assert shutil.which('codex') is None; "
                "assert shutil.which('claude') is None",
            )
        helper.compose("exec", "-T", "agent", "node", "--version")
        helper.compose("exec", "-T", "agent", "npm", "--version")
        config_sentinels = [
            path + "/template-test-sentinel" for path in helper.PERSISTENT_PATHS.values()
        ] + ["/home/agent/.cache/uv/template-cache-sentinel", "/opt/venv/template-venv-sentinel"]
        for sentinel_path in config_sentinels:
            helper.compose("exec", "-T", "agent", "touch", sentinel_path)
        command(project, "make", "agent-refresh")
        command(project, "make", "agent-start")
        for sentinel_path in config_sentinels:
            helper.compose("exec", "-T", "agent", "test", "-f", sentinel_path)
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
        command(project, "make", "agent-stop")
        assert helper.agent_container() is None
        assert helper.STATE.read_bytes() == stop_state
        (helper.WORKSPACE / "harness-work.txt").write_text("preserve workspace\n")
        saved_state = helper.STATE.read_bytes()
        command(project, "make", "agent-rebuild")
        assert helper.STATE.read_bytes() == saved_state
        assert (helper.WORKSPACE / "harness-work.txt").read_text() == "preserve workspace\n"
        command(project, "make", "agent-start")
        helper.compose(
            "exec", "-T", "agent", "test", "!", "-e", "/tmp/template-disposable-test/blob"
        )
        for name, agent in helper.AGENTS.items():
            actual = helper.compose("exec", "-T", "agent", agent.cli, "--version", capture=True)
            assert (
                helper.parsed_version(name, actual)
                == helper.harness_versions()[helper.VERSION_KEYS[name]]
            )
        for sentinel_path in config_sentinels:
            helper.compose("exec", "-T", "agent", "test", "-f", sentinel_path)
        if provider == "custom":
            (project / ".env").write_text(
                (project / ".env").read_text()
                + "\nCUSTOM_AGENT_COMMAND=fake-harness\nCUSTOM_AGENT_ARGS=--example\n"
            )
            assert "fake-harness /workspace --example" in command(project, "make", "agent")
            helper.compose(
                "exec",
                "-T",
                "agent",
                "python",
                "-c",
                "from pathlib import Path; Path('/opt/agent-tools/bin/fake-harness').unlink()",
            )
        command(project, "make", "agent-stop")
        if provider != "custom":
            command(project, "make", "agent-start")
            for sentinel_path in config_sentinels:
                helper.compose("exec", "-T", "agent", "test", "-f", sentinel_path)
        command(project, "make", "agent-clean")
        if provider == "custom":
            command(project, "make", "agent-rebuild")
        command(project, "make", "agent-start")
        for sentinel_path in config_sentinels:
            helper.compose("exec", "-T", "agent", "test", "-f", sentinel_path)
        if provider == "custom":
            assert "fake-harness /workspace --example" in command(project, "make", "agent")
        if provider == "both":
            helper.compose(
                "exec",
                "-T",
                "agent",
                "python",
                "-c",
                f"from pathlib import Path; Path({config_sentinels[0]!r}).unlink()",
            )
            helper.compose("exec", "-T", "agent", "test", "-f", config_sentinels[1])
        ids = helper.compose("ps", "-q", capture=True).splitlines()
        inspection = json.loads(command(project, "podman", "inspect", *ids))[0]
        mounts = inspection["Mounts"]
        binds = [mount for mount in mounts if mount["Type"] == "bind"]
        assert len(binds) == 1
        assert Path(binds[0]["Source"]).resolve() == helper.WORKSPACE.resolve()
        assert all(".sock" not in mount["Source"] for mount in mounts)
        for mappings in inspection["NetworkSettings"]["Ports"].values():
            assert all(mapping["HostIp"] == "127.0.0.1" for mapping in mappings)
        sentinel = tmp_path / "host-only"
        sentinel.write_text("preserve")
        result = subprocess.run(
            [
                "podman",
                "compose",
                "--env-file",
                "/dev/null",
                "-f",
                str(project / "containers/compose.agent.yaml"),
                "exec",
                "-T",
                "agent",
                "sh",
                "-c",
                f"echo changed > {sentinel}",
            ],
            cwd=project,
            env=helper.environment(),
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0 and sentinel.read_text() == "preserve"
        helper.compose(
            "exec",
            "-d",
            "agent",
            "uv",
            "run",
            "python",
            "-m",
            "http.server",
            "8000",
            "--bind",
            "0.0.0.0",
        )
        port = helper.environment()["AGENT_APP_PORT"]
        command(
            project,
            "curl",
            "--fail",
            "--retry",
            "10",
            "--retry-connrefused",
            "--retry-delay",
            "1",
            f"http://127.0.0.1:{port}",
        )


def test_agent_multi_project_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not shutil.which("podman"):
        pytest.skip("Podman unavailable: simultaneous multi-project agents not executed")
    info = subprocess.run(
        ["podman", "info", "--format", "json"], text=True, capture_output=True, check=False
    )
    if info.returncode or not json.loads(info.stdout).get("host", {}).get("security", {}).get(
        "rootless"
    ):
        pytest.skip("Usable rootless Podman unavailable")
    # Keep the identical user defaults. Even if another host service owns one,
    # both projects must start through the runtime's automatic allocation.
    for key in ("AGENT_APP_PORT", "AGENT_JUPYTER_PORT", "AGENT_DOCS_PORT"):
        monkeypatch.delenv(key, raising=False)
    projects = [
        generate(
            tmp_path,
            project_slug=f"ports-{name}-{uuid4().hex[:12]}",
            coding_agent=provider,
            package_name="my_python_project",
        )
        for name, provider in (("a", "codex"), ("b", "claude"))
    ]
    for project in projects:
        command(project, "make", "init", env=git_identity_environment(tmp_path))
    helpers = [configure_agent(project) for project in projects]
    effective: list[dict[str, int]] = []
    with ExitStack() as stack:
        for helper in helpers:
            stack.enter_context(runtime_cleanup(partial(helper.compose, "down", "--volumes")))
        for index, (project, helper) in enumerate(zip(projects, helpers, strict=True)):
            command(project, "make", "agent-start")
            container = helper.agent_container()
            assert container is not None and container["State"]["Running"]
            ports = helper.published_ports(container)
            assert ports == json.loads(helper.STATE.read_text())["ports"]
            effective.append(ports)
            output = command(project, "make", "agent-status")
            assert "Agent: running" in output
            for port in ports.values():
                assert f"http://127.0.0.1:{port}" in output
            helper.compose(
                "exec",
                "-T",
                "agent",
                "uv",
                "run",
                "python",
                "-c",
                f"from pathlib import Path; Path('identity.txt').write_text('project-{index}')",
            )
            helper.compose(
                "exec",
                "-d",
                "agent",
                "uv",
                "run",
                "python",
                "-m",
                "http.server",
                "8000",
                "--bind",
                "0.0.0.0",
            )
        assert set(effective[0].values()).isdisjoint(effective[1].values())
        for index, (project, ports) in enumerate(zip(projects, effective, strict=True)):
            response = command(
                project,
                "curl",
                "--fail",
                "--retry",
                "10",
                "--retry-connrefused",
                "--retry-delay",
                "1",
                f"http://127.0.0.1:{ports['app']}/identity.txt",
            )
            assert response == f"project-{index}"
        command(projects[0], "make", "agent-stop")
        stopped = helpers[0].agent_container()
        assert stopped is None or not stopped["State"]["Running"]
        still_running = helpers[1].agent_container()
        assert still_running is not None and still_running["State"]["Running"]
        assert helpers[1].published_ports(still_running) == effective[1]
        assert (
            command(
                projects[1],
                "curl",
                "--fail",
                f"http://127.0.0.1:{effective[1]['app']}/identity.txt",
            )
            == "project-1"
        )
        assert "Agent: running" in command(projects[1], "make", "agent-status")
