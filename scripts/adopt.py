"""Plan and install common infrastructure into an existing, clean Git repository."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "{{cookiecutter.project_slug}}"
PROFILES = ("auto", "python", "node", "mixed", "generic")
HARNESSES = ("codex", "claude", "both", "custom", "none")
IGNORED = {".git", ".agent", ".venv", "node_modules", ".template", "vendor", "dist", "build"}
PYTHON = {
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "poetry.lock",
    "pdm.lock",
}
NODE = {"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb"}
OTHER = {"Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "CMakeLists.txt"}


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(repo), *args], text=True
    ).strip()


def repository_files(repo: Path) -> Iterator[Path]:
    """Walk application metadata without traversing dependency trees or symlink directories."""
    for base, dirs, names in os.walk(repo, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED and not Path(base, d).is_symlink())
        for name in sorted(names):
            yield Path(base, name).relative_to(repo)


def audit(repo: Path) -> dict[str, Any]:
    if not repo.is_dir():
        raise ValueError("Target directory does not exist.")
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError("Target must be the Git repository root.")
    git(repo, "rev-parse", "HEAD")  # Require recoverable history, never initialize Git.
    found = []
    for path in repository_files(repo):
        if path.name in PYTHON | NODE | OTHER | {
            "Dockerfile",
            "Containerfile",
            "compose.yaml",
            "docker-compose.yml",
            ".gitlab-ci.yml",
        } or str(path).startswith((".github/workflows/", ".devcontainer/")):
            found.append(str(path))
    python = any(Path(p).name in PYTHON for p in found)
    node = any(Path(p).name in NODE for p in found)
    profile = "mixed" if python and node else "python" if python else "node" if node else "generic"
    managers = {}
    for name in found:
        if Path(name).name != "package.json" or (repo / name).is_symlink():
            continue
        data = json.loads((repo / name).read_text())
        parent = (repo / name).parent
        locks = [
            manager
            for lock, manager in (
                ("package-lock.json", "npm"),
                ("yarn.lock", "yarn"),
                ("pnpm-lock.yaml", "pnpm"),
                ("bun.lock", "bun"),
                ("bun.lockb", "bun"),
            )
            if (parent / lock).exists()
        ]
        declared = data.get("packageManager", "").split("@")[0]
        managers[name] = {
            "manager": declared or (locks[0] if len(set(locks)) == 1 else "unknown"),
            "locks": locks,
            "typescript": (parent / "tsconfig.json").exists(),
            "scripts": sorted(data.get("scripts", {})),
        }
    sections = {}
    import tomllib

    for name in found:
        if Path(name).name == "pyproject.toml" and not (repo / name).is_symlink():
            data = tomllib.loads((repo / name).read_text())
            sections[name] = {
                key: key in data for key in ("project", "build-system", "dependency-groups")
            }
            sections[name].update(
                {f"tool.{key}": key in data.get("tool", {}) for key in ("pytest", "ruff", "mypy")}
            )
    return {
        "profile": profile,
        "detected": found,
        "node": managers,
        "python_sections": sections,
        "branch": git(repo, "branch", "--show-current"),
        "dirty": bool(git(repo, "status", "--porcelain")),
    }


def render(name: str, context: dict[str, str]) -> bytes:
    template = Environment(undefined=StrictUndefined).from_string((SOURCE / name).read_text())
    text = template.render(cookiecutter=context)
    return ("\n".join(line.rstrip() for line in text.splitlines()).rstrip() + "\n").encode()


def commands(report: dict[str, Any], profile: str) -> dict[str, Any]:
    # Only unambiguous root Node commands are inferred. Mixed monorepos are explicit.
    if profile != "node" or "package.json" not in report["node"]:
        return {}
    node = report["node"]["package.json"]
    manager = node["manager"]
    if manager not in {"npm", "pnpm", "yarn", "bun"}:
        return {}
    result = {}
    for name in ("format", "format-check", "lint", "typecheck", "test", "build", "docs-build"):
        if name in node["scripts"]:
            result[name] = [{"argv": [manager, "run", name]}]
    install = (
        [manager, "ci"] if manager == "npm" and "npm" in node["locks"] else [manager, "install"]
    )
    result["setup"] = [{"argv": install}]
    return result


@dataclass
class Entry:
    name: str
    action: str
    before: bytes | None
    after: bytes | None
    reason: str = ""
    blocking: bool = False


def safe_path(repo: Path, name: str) -> Path:
    path = repo / name
    for part in (path, *path.parents):
        if part == repo:
            break
        if part.is_symlink() or (part != path and part.exists() and not part.is_dir()):
            raise ValueError(f"Unsafe destination (symlink or non-directory ancestor): {name}")
    if path.exists() and not path.is_file():
        raise ValueError(f"Destination is not a regular file: {name}")
    return path


def plan(repo: Path, report: dict[str, Any], profile: str, harness: str) -> list[Entry]:
    slug = re.sub(r"[^a-z0-9]+", "-", repo.name.lower()).strip("-") or "adopted-project"
    context = {
        "project_slug": slug,
        "project_name": repo.name,
        "package_name": slug.replace("-", "_"),
        "coding_agent": harness,
        "_adoption": "yes",
        "project_profile": profile,
        "python_version": "3.12",
        "dev_container_runtime": "none",
        "enable_notebooks": "no",
        "enable_docs": "no",
    }
    files = {}
    for name in (
        "scripts/agent.py",
        "scripts/disk_usage.py",
        "scripts/project.py",
        "containers/Containerfile",
        "containers/compose.agent.yaml",
        ".template/make/agent.mk",
        "docs/agent.md",
        "docs/agent-security.md",
        "docs/podman.md",
    ):
        target = "containers/Containerfile.agent" if name == "containers/Containerfile" else name
        content = render(name, context).replace(
            b"containers/Containerfile", b"containers/Containerfile.agent"
        )
        files[target] = content
    if harness == "custom":
        files["containers/agent-custom-install.sh"] = render(
            "containers/agent-custom-install.sh", context
        )
    elif harness != "none":
        files["containers/harness-versions.env"] = render(
            "containers/harness-versions.env", context
        )
    files[".template/project.json"] = (
        json.dumps({"profile": profile, "commands": commands(report, profile)}, indent=2) + "\n"
    ).encode()
    # Prefix application targets to preserve historical Make recipes. Add aliases only if absent.
    make_name = next(
        (name for name in ("GNUmakefile", "makefile", "Makefile") if (repo / name).exists()),
        "Makefile",
    )
    makefile = repo / make_name
    existing = (
        makefile.read_bytes().decode() if makefile.is_file() and not makefile.is_symlink() else ""
    )
    make_sources = existing
    inspected_makes = set()
    for relative in repository_files(repo):
        path = repo / relative
        if path.suffix == ".mk" and not path.is_symlink():
            inspected_makes.add(str(relative))
            make_sources += "\n" + path.read_text()
    targets = set()
    dynamic_make = False
    for line in make_sources.splitlines():
        if line.startswith(("include ", "-include ", "sinclude ")):
            # Includes can hide recipes. Only inspected static .mk files are safe to merge.
            includes = line.split()[1:]
            dynamic_make |= any(
                "$" in name
                or name not in inspected_makes
                or not name.endswith(".mk")
                or not (repo / name).is_file()
                or (repo / name).is_symlink()
                or not (repo / name).resolve().is_relative_to(repo)
                for name in includes
            )
        if line and not line[0].isspace() and ":" in line and not line.startswith("#"):
            left, right = line.split(":", 1)
            if right.startswith("="):
                continue
            dynamic_make |= "$" in left
            targets.update(left.split())
    project_targets = (
        "setup",
        "format",
        "format-check",
        "lint",
        "typecheck",
        "test",
        "check",
        "build",
        "docs-build",
    )
    module = "TEMPLATE_PYTHON := uv run --no-project --python 3.12 python\n"
    for target in project_targets:
        names = f"template-{target}" + (f" {target}" if target not in targets else "")
        module += f".PHONY: {names}\n{names}:\n\t$(TEMPLATE_PYTHON) scripts/project.py {target}\n"
    files[".template/make/project.mk"] = module.encode()
    files[make_name] = (
        existing
        + ("\n" if existing and not existing.endswith("\n") else "")
        + (".DEFAULT_GOAL := check\n" if not targets else "")
        + "\ninclude .template/make/agent.mk\ninclude .template/make/project.mk\n"
    ).encode()
    files[".gitignore"] = b".agent/\n.env\n"
    files[".env.example"] = render(".env.example", context)
    instruction = (
        "# Template sandbox\n"
        "\n"
        "Use `make agent-check`, `make agent-start`, `make agent-diff` and `make agent-apply`.\n"
        "The sandbox uses an independent clone and explicit commit recovery; see docs/agent.md.\n"
        "Application commands are configured in .template/project.json.\n"
        "Python/uv runs internal tooling only and does not imply a Python application.\n"
        ""
    )
    if harness in {"codex", "both"}:
        files["AGENTS.md"] = instruction.encode()
    if harness in {"claude", "both"}:
        files["CLAUDE.md"] = instruction.encode()
    entries = []
    for name, candidate in files.items():
        path = safe_path(repo, name)
        before = path.read_bytes() if path.exists() else None
        action, reason, blocking = "ADD", "", False
        if before is not None:
            if before == candidate:
                action = "SKIP"
            elif name == ".gitignore":
                lines = before.decode().splitlines()
                candidate = (
                    before
                    + (b"\n" if before and not before.endswith(b"\n") else b"")
                    + b"".join(
                        line + b"\n"
                        for line in candidate.splitlines()
                        if line.decode() not in lines
                    )
                )
                action = "MERGE" if candidate != before else "SKIP"
            elif name == ".env.example":
                values = {}
                for line in before.decode().splitlines():
                    match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=(.*)", line)
                    if match:
                        values[match[1]] = match[2]
                additions = []
                for line in candidate.decode().splitlines():
                    key, sep, value = line.partition("=")
                    if not sep:
                        continue
                    if key in values and values[key] != value:
                        blocking, reason = True, f"CONFLICT: variable {key} has a different value"
                    elif key not in values:
                        additions.append(line)
                candidate = (
                    before
                    + (b"\n" if before and not before.endswith(b"\n") else b"")
                    + "".join(line + "\n" for line in additions).encode()
                )
                action = "REVIEW" if blocking else "MERGE" if candidate != before else "SKIP"
            elif name == make_name:
                collisions = sorted(
                    t for t in targets if t == "agent" or t.startswith(("agent-", "template-"))
                )
                blocking = bool(collisions) or dynamic_make
                action = "REVIEW" if blocking else "MERGE"
                reason = (
                    "Existing infrastructure targets: " + ", ".join(collisions)
                    if collisions
                    else "Append modular includes; preserve existing targets"
                )
                if dynamic_make:
                    reason = (
                        "Dynamic targets or uninspected includes require manual Make integration"
                    )
            else:
                action, blocking = "REVIEW", name not in {"AGENTS.md", "CLAUDE.md"}
                reason = "Existing file preserved"
        entries.append(Entry(name, action, before, candidate, reason, blocking))
        if action == "REVIEW" and name in {"AGENTS.md", "CLAUDE.md"}:
            alternate = name.replace(".md", ".template.md")
            alt = safe_path(repo, alternate)
            old = alt.read_bytes() if alt.exists() else None
            entries.append(
                Entry(
                    alternate,
                    "ADD" if old is None else "SKIP" if old == candidate else "REVIEW",
                    old,
                    candidate,
                    "Instruction candidate for manual review",
                    old is not None and old != candidate,
                )
            )
    managed = {
        e.name: hashlib.sha256(e.after).hexdigest()
        for e in entries
        if e.after is not None and e.action in {"ADD", "MERGE", "SKIP"}
    }
    metadata = {
        "template": "python-project-template",
        "adopted": True,
        "infrastructure_version": 1,
        "template_revision": git(ROOT, "rev-parse", "HEAD"),
        "profile": profile,
        "coding_agent": harness,
        "base_commit": git(repo, "rev-parse", "HEAD"),
        "files": managed,
        "audit": report,
    }
    name = ".template/adoption.json"
    path = safe_path(repo, name)
    old = path.read_bytes() if path.exists() else None
    entries.append(
        Entry(
            name,
            "ADD" if old is None else "REVIEW",
            old,
            (json.dumps(metadata, indent=2) + "\n").encode(),
            "Already adopted; infrastructure updates require manual review" if old else "",
            old is not None,
        )
    )
    for name in report["detected"]:
        entries.append(
            Entry(
                name,
                "REVIEW"
                if name.startswith((".github/", ".devcontainer/"))
                or Path(name).name
                in {
                    "Dockerfile",
                    "Containerfile",
                    "compose.yaml",
                    "docker-compose.yml",
                    ".gitlab-ci.yml",
                    "pyproject.toml",
                }
                else "SKIP",
                None,
                None,
                "Preserved; application configuration is never replaced",
            )
        )
    return entries


def apply(repo: Path, entries: list[Entry]) -> None:
    if git(repo, "status", "--porcelain"):
        raise ValueError(
            "Existing repository has uncommitted changes.\n"
            "\n"
            "Commit or stash them before adopting the template."
        )
    if any(e.blocking for e in entries):
        raise ValueError("Blocking conflicts require review. No files modified.")
    changes = [e for e in entries if e.action in {"ADD", "MERGE"}]
    # Validate the entire plan again before any write, including symlink ancestors.
    for entry in changes:
        path = safe_path(repo, entry.name)
        if (path.read_bytes() if path.exists() else None) != entry.before:
            raise ValueError(f"Destination changed since audit: {entry.name}. No files modified.")
    written = []
    created_dirs: list[Path] = []
    try:
        for entry in changes:
            path = repo / entry.name
            missing = []
            parent = path.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_dirs.append(directory)
            assert entry.after is not None
            if entry.before is None:
                with path.open("xb") as stream:
                    written.append(entry)
                    stream.write(entry.after)
            else:
                written.append(entry)
                path.write_bytes(entry.after)
    except BaseException:
        for entry in reversed(written):
            path = repo / entry.name
            if entry.before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(entry.before)
        for directory in reversed(created_dirs):
            directory.rmdir()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--profile", choices=PROFILES, default="auto")
    parser.add_argument("--agent", choices=HARNESSES, default="both")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        repo = args.repo.expanduser().resolve()
        if repo == ROOT or ROOT.is_relative_to(repo) or repo.is_relative_to(ROOT):
            raise ValueError("Adoption target must be separate from the template sources.")
        report = audit(repo)
        profile = report["profile"] if args.profile == "auto" else args.profile
        print(
            f"Repository: {repo}\n"
            f"Git: existing repository\n"
            f"Branch: {report['branch']}\n"
            f"Working tree: {'dirty' if report['dirty'] else 'clean'}\n"
            f"Detected profile: {report['profile']}\n"
            f"Selected profile: {profile}\n"
            f"Harness: {args.agent}"
        )
        print("Detected application stack:\n" + json.dumps(report, indent=2))
        entries = plan(repo, report, profile, args.agent)
        print("Adoption plan:")
        for action in ("ADD", "MERGE", "REVIEW", "SKIP"):
            print("REVIEW REQUIRED" if action == "REVIEW" else action)
            for entry in entries:
                if entry.action == action:
                    print(f"  {entry.name}" + (f" — {entry.reason}" if entry.reason else ""))
        for entry in entries:
            if entry.after is not None and entry.action in {"ADD", "MERGE"}:
                print(
                    "".join(
                        difflib.unified_diff(
                            (entry.before or b"").decode().splitlines(True),
                            entry.after.decode().splitlines(True),
                            fromfile=f"a/{entry.name}",
                            tofile=f"b/{entry.name}",
                        )
                    ),
                    end="",
                )
        if args.dry_run:
            print("No files modified.")
            return
        apply(repo, entries)
        print(
            "Template infrastructure adopted successfully.\n"
            "\n"
            "Review:\n"
            "    git status\n"
            "    git diff\n"
            "    git diff --no-index /dev/null <added-file>\n"
            "\n"
            "Then commit:\n"
            "    git add <reviewed-files>\n"
            '    git commit -m "chore: adopt project template infrastructure"\n'
            "\n"
            "Commit before make agent-start so the independent clone includes the infrastructure."
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
