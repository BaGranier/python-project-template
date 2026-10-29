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
if shutil.which("uv"):
    try:
        subprocess.run(["uv", "lock"], check=True, timeout=180)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"Lock generation failed: {exc}")
if not Path("uv.lock").exists():
    print("uv lock was not generated.\nInstall uv and run:\nmake setup")
print("Project generated. Next: cd {{ cookiecutter.project_slug }} && make init")
