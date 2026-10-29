"""Adapt trusted generator sources for the master repository, without generating a project."""

from __future__ import annotations

import argparse
from pathlib import Path

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "{{cookiecutter.project_slug}}"
PROFILES = ("codex", "claude", "both", "custom")


def render(name: str, profile: str) -> str:
    context = {
        "project_slug": "python-project-template",
        "coding_agent": profile,
        "python_version": (ROOT / ".python-version").read_text().strip(),
        "dev_container_runtime": "none",
        "enable_notebooks": "no",
        "enable_docs": "no",
    }
    result = Environment(undefined=StrictUndefined).from_string((SOURCE / name).read_text())
    text = result.render(cookiecutter=context)
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip() + "\n"


def runtime_source(profile: str) -> str:
    if profile not in PROFILES:
        raise ValueError("AGENT_PROFILE must be codex, claude, both or custom.")
    filename = "compose.agent.yaml" if profile == "both" else f"compose.agent.{profile}.yaml"
    return (
        render("scripts/agent.py", profile)
        .replace("containers/compose.agent.yaml", f"containers/{filename}")
        .replace('print(f"Agent:', 'print(f"Template agent:')
        .replace('print(f"Default provider:', 'print(f"Selected provider:')
    )


def artifacts() -> dict[str, str]:
    # One shared base; only final provider stages differ. Pins remain in the generator source.
    shared, _ = render("containers/Containerfile", "both").split("FROM agent-base AS agent\n")
    containerfile = shared
    files = {}
    for profile in PROFILES:
        stage = render("containers/Containerfile", profile).split("FROM agent-base AS agent\n")[1]
        containerfile += f"\nFROM agent-base AS {profile}\n" + stage
        filename = "compose.agent.yaml" if profile == "both" else f"compose.agent.{profile}.yaml"
        files[f"containers/{filename}"] = render("containers/compose.agent.yaml", profile).replace(
            "target: agent", f"target: {profile}"
        )
    files["containers/Containerfile"] = containerfile
    files["CLAUDE.md"] = (ROOT / "AGENTS.md").read_text()
    files["docs/podman.md"] = render("docs/podman.md", "both")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    for filename, content in artifacts().items():
        path = ROOT / filename
        if options.check:
            if not path.exists() or path.read_text() != content:
                raise SystemExit(f"Stale {filename}; run make agent-sync.")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)


if __name__ == "__main__":
    main()
