"""Remove disabled components; locking is best effort, never silently ignored."""

import json
from pathlib import Path
import shutil
import subprocess

context = json.loads(r'''{{ cookiecutter | tojson }}''')


def remove(name):
    path = Path(name)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


if context["enable_notebooks"] == "no":
    remove("notebooks")
    remove("jupytext.toml")
    remove("docs/notebooks.md")
if context["enable_docs"] == "no":
    remove("docs")
    remove("mkdocs.yml")
    remove(".github/workflows/pages.yml")
if context["ci_provider"] != "github":
    remove(".github")
if context["ci_provider"] != "gitlab":
    remove(".gitlab-ci.yml")
if context["coding_agent"] == "both":
    shutil.copyfile("AGENTS.md", "CLAUDE.md")
if context["coding_agent"] == "custom":
    remove("AGENTS.md")
    remove("CLAUDE.md")
if context["coding_agent"] != "custom":
    remove("containers/agent-custom-install.sh")
if context["coding_agent"] in ("none", "custom"):
    remove("containers/harness-versions.env")
if context["coding_agent"] == "none":
    remove("scripts/agent.py")
    remove("containers/compose.agent.yaml")
    remove("docs/agent-security.md")
    remove("docs/agent.md")
    remove("AGENTS.md")
    remove("CLAUDE.md")
if context["dev_container_runtime"] == "none":
    remove("containers/compose.yaml")
if context["dev_container_runtime"] == "none" and context["coding_agent"] == "none":
    remove("containers")
    remove("docs/containers.md")
if context["dev_container_runtime"] != "podman" and context["coding_agent"] == "none":
    remove("docs/podman.md")
# Non-Python profiles ship common infrastructure, without application Python metadata.
# auto has nothing to detect in a new repository and starts as generic.
if context["project_profile"] != "python":
    for name in ("pyproject.toml", "uv.lock", ".python-version", "src", "tests",
                 "notebooks", "jupytext.toml", "mkdocs.yml", ".pre-commit-config.yaml",
                 ".github", ".gitlab-ci.yml", "containers/compose.yaml"):
        remove(name)
    agent_include = "include .template/make/agent.mk\n"
    Path("Makefile").write_text(
        ".DEFAULT_GOAL := check\ninclude .template/make/project.mk\n" + agent_include
    )
    Path(".template/project.json").write_text(json.dumps({
        "profile": "generic" if context["project_profile"] == "auto" else context["project_profile"],
        "commands": {},
    }, indent=2) + "\n")
    Path("README.md").write_text(
        "# " + context["project_name"] + "\n\n"
        "Common template infrastructure. Configure application argv in `.template/project.json`.\n"
        "Python/uv runs template tooling only; no application stack is imposed.\n"
        "Run `make setup`, `make check`, `make build`; unconfigured commands report a no-op.\n"
    )
    Path("CONTRIBUTING.md").write_text(
        "Configure application commands in `.template/project.json`. See `docs/agent.md` for sandbox use.\n"
    )
    for name in ("setup.py", "shell.py", "init_project.py", "clean.py"):
        remove("scripts/" + name)
    for name in ("AGENTS.md", "CLAUDE.md"):
        if Path(name).exists():
            Path(name).write_text(
                "# Project instructions\n\n"
                "Configure application commands in `.template/project.json`.\n"
                "Run `make check` to execute the configured checks.\n"
                "Python/uv is internal template tooling, independent of the application stack.\n"
                "See `docs/agent.md` for the independent sandbox and explicit commit recovery.\n"
            )
    Path(".gitignore").write_text(".agent/\n.env\nnode_modules/\n")
    for name in ("getting-started.md", "testing.md", "development.md", "notebooks.md"):
        remove("docs/" + name)
# Conditional Jinja blocks can leave blank endings or whitespace when a value
# is empty. Ship text already compliant with the generated pre-commit hooks.
for path in Path(".").rglob("*"):
    if path.is_file():
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            continue  # Future binary template assets are preserved verbatim.
        content = "\n".join(line.rstrip() for line in content.splitlines()).rstrip()
        path.write_text(content + "\n" if content else "")
if context["project_profile"] == "python" and shutil.which("uv"):
    try:
        subprocess.run(["uv", "lock"], check=True, timeout=180)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"Lock generation failed: {exc}")
if context["project_profile"] == "python" and not Path("uv.lock").exists():
    print("uv lock was not generated.\nInstall uv and run:\nmake setup")
print("Project generated. Next: cd {{ cookiecutter.project_slug }} && " +
      ("make init" if context["project_profile"] == "python" else "make setup"))
