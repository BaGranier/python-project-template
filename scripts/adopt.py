"""Plan and install common infrastructure into an existing, clean Git repository."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import traceback
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
                        blocking = True
                        reason += ("; " if reason else "") + (
                            f"CONFLICT {key}: existing: {values[key]}, template: {value}"
                        )
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
                    reason = (reason + "; " if collisions else "") + (
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
    except BaseException as exc:
        for entry in reversed(written):
            path = repo / entry.name
            if entry.before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(entry.before)
        for directory in reversed(created_dirs):
            directory.rmdir()
        exc.add_note("Transaction rollback completed; adoption writes were reverted.")
        raise


LIST_LIMIT = 6


def output_action(entry: Entry) -> str:
    return "BLOCK" if entry.blocking else entry.action


def render_paths(title: str, rows: list[str], *, verbose: bool = False) -> None:
    if not rows:
        return
    print(title)
    for row in rows if verbose else rows[:LIST_LIMIT]:
        print(f"  {row}")
    if not verbose and len(rows) > LIST_LIMIT:
        print(f"  ... and {len(rows) - LIST_LIMIT} more (use VERBOSE=1)")


def merge_delta(entry: Entry) -> str:
    changes = difflib.ndiff(
        (entry.before or b"").decode().splitlines(), (entry.after or b"").decode().splitlines()
    )
    added = removed = 0
    for line in changes:
        added += line.startswith("+ ")
        removed += line.startswith("- ")
    return f"+{added}" + (f"/-{removed}" if removed else "")


def render_summary(
    repo: Path,
    report: dict[str, Any],
    profile: str,
    harness: str,
    entries: list[Entry],
    *,
    head: str,
    preview: bool,
    verbose: bool = False,
) -> None:
    print("Repository adoption dry-run" if preview else "Adopting template infrastructure")
    print(f"Repository: {repo}\n")
    print(f"Git:\n  branch: {report['branch'] or '(detached HEAD)'}\n  HEAD: {head}")
    state_label = "working tree" if preview else "working tree before adoption"
    print(f"  {state_label}: {'dirty' if report['dirty'] else 'clean'}")
    print(f"Detected stack:\n  profile: {report['profile']}")
    if profile != report["profile"]:
        print(f"  selected profile: {profile}")
    for label, names in (
        ("Python", [p for p in report["detected"] if Path(p).name in PYTHON]),
        ("Node", [p for p in report["detected"] if Path(p).name == "package.json"]),
    ):
        parents = {str(Path(p).parent) for p in names}
        detail = ", ".join(names) if len(names) <= 2 else f"{len(parents)} projects"
        if label == "Python" and names:
            tools = sorted(
                {
                    key.removeprefix("tool.")
                    for sections in report["python_sections"].values()
                    for key, enabled in sections.items()
                    if key.startswith("tool.") and enabled
                }
            )
            if tools:
                detail += " (tools: " + ", ".join(tools) + ")"
        print(f"  {label}: {detail or 'none detected'}")
    detected = report["detected"]
    docker = sum(Path(p).name in {"Dockerfile", "Containerfile"} for p in detected)
    compose = sum(Path(p).name in {"compose.yaml", "docker-compose.yml"} for p in detected)
    ci = []
    if any(p.startswith(".github/workflows/") for p in detected):
        ci.append("GitHub Actions")
    if ".gitlab-ci.yml" in detected:
        ci.append("GitLab CI")
    dev = any(p.startswith(".devcontainer/") for p in detected)
    print(f"Existing infrastructure: Docker: {docker}; Compose: {compose}")
    print(f"  CI: {', '.join(ci) or 'none detected'}; Dev Container: {'yes' if dev else 'no'}")
    print(f"Agent:\n  profile: {harness}\n")
    print("Plan:" if preview else "Applied:")
    for action in ("ADD", "MERGE", "REVIEW", "SKIP", "BLOCK"):
        print(f"  {action}: {sum(output_action(e) == action for e in entries)}")
    print()
    for action, title in (
        ("ADD", "ADD" if preview else "Added:"),
        ("MERGE", "MERGE" if preview else "Merged:"),
        ("REVIEW", "REVIEW" if preview else "Existing files preserved (REVIEW):"),
        ("SKIP", "SKIP"),
    ):
        if action == "SKIP" and not verbose:
            continue
        rows = []
        for entry in entries:
            if output_action(entry) != action:
                continue
            suffix = f" ({merge_delta(entry)})" if action == "MERGE" else ""
            if verbose and entry.reason:
                suffix += f" — {entry.reason}"
            rows.append(entry.name + suffix)
        render_paths(title, rows, verbose=verbose)


def render_diffs(entries: list[Entry], *, include_added: bool) -> None:
    for entry in entries:
        if entry.after is None or entry.action not in (
            {"ADD", "MERGE"} if include_added else {"MERGE"}
        ):
            continue
        print(
            "".join(
                difflib.unified_diff(
                    (entry.before or b"").decode().splitlines(True),
                    entry.after.decode().splitlines(True),
                    fromfile="/dev/null" if entry.before is None else f"a/{entry.name}",
                    tofile=f"b/{entry.name}",
                )
            ),
            end="",
        )


def render_verbose(report: dict[str, Any], entries: list[Entry]) -> None:
    print("\nDetection details:")
    for name in report["detected"]:
        print(f"  {name}")
        if name in report["python_sections"]:
            tools = [
                key.removeprefix("tool.")
                for key, enabled in report["python_sections"][name].items()
                if key.startswith("tool.") and enabled
            ]
            print("    Python tools: " + (", ".join(tools) or "none detected"))
        if name in report["node"]:
            node = report["node"][name]
            print(f"    package manager: {node['manager']}")
            print(f"    TypeScript: {'yes' if node['typescript'] else 'no'}")
            print("    Available scripts: " + (", ".join(node["scripts"]) or "none"))
    print("Application commands:")
    configured = next(e for e in entries if e.name == ".template/project.json")
    assert configured.after is not None
    commands = json.loads(configured.after)["commands"]
    for name, steps in commands.items():
        for step in steps:
            print(f"  {name}: {shlex.join(step['argv'])} (cwd: {step.get('cwd', '.')})")
    if not commands:
        print("  none inferred; configure .template/project.json explicitly")


def render_debug(report: dict[str, Any], entries: list[Entry]) -> None:
    def digest(content: bytes | None) -> dict[str, Any] | None:
        if content is None:
            return None
        return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}

    metadata = next(e for e in entries if e.name == ".template/adoption.json")
    assert metadata.after is not None
    diagnostics = {
        "audit": report,
        "candidate_plan": [
            {
                "path": e.name,
                "action": e.action,
                "blocking": e.blocking,
                "reason": e.reason,
                "before": digest(e.before),
                "after": digest(e.after),
            }
            for e in entries
        ],
        "adoption_provenance": {
            key: value
            for key, value in json.loads(metadata.after).items()
            if key not in {"files", "audit"}
        },
    }
    print("\nDEBUG: internal adoption diagnostics")
    print(json.dumps(diagnostics, indent=2))


def render_blocks(entries: list[Entry]) -> None:
    blocked = [e for e in entries if e.blocking]
    print(
        f"Adoption blocked.\n\n{len(blocked)} conflicts require manual resolution:", file=sys.stderr
    )
    for entry in blocked:  # Never truncate blockers, even if other lists are truncated.
        reason = entry.reason
        if reason == "Existing file preserved":
            reason = "path already exists with unrelated content"
        print(f"  {entry.name}\n    {reason}", file=sys.stderr)
    print("No files modified.", file=sys.stderr)


def render_success(repo: Path, entries: list[Entry]) -> None:
    print("\nAdoption completed successfully.")
    for label, actions in (
        ("Files added", {"ADD"}),
        ("Files modified", {"MERGE"}),
        ("Existing files preserved", {"REVIEW", "SKIP"}),
    ):
        print(f"{label}: {len({e.name for e in entries if e.action in actions})}")
    print(f"\nNext steps:\n  cd {shlex.quote(str(repo))}")
    print("  git status --short\n  git diff\n  git add <reviewed-files>\n  git diff --cached")
    print('  git commit -m "chore: adopt project template infrastructure"')
    print("\nThen:\n  make agent-check\n  make agent-start\n  make agent")
    print("Commit the reviewed infrastructure before starting the independent agent clone.")


def environment_flag(name: str) -> bool:
    value = os.environ.get(name, "0").strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"", "0", "false", "no"}:
        return False
    raise ValueError(f"{name} must be 1/true/yes or 0/false/no.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--profile", choices=PROFILES, default="auto")
    parser.add_argument("--agent", choices=HARNESSES, default="both")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="Show a concise read-only preview")
    modes.add_argument("--diff", action="store_true", help="Show full read-only candidate diffs")
    parser.add_argument(
        "--verbose", action="store_true", help="Show detailed human-readable output"
    )
    parser.add_argument("--debug", action="store_true", help="Include internal diagnostics")
    args = parser.parse_args()
    debug = False
    applying = False
    applied = False
    try:
        debug = args.debug or environment_flag("DEBUG")
        verbose = args.verbose or environment_flag("VERBOSE") or debug
        preview = args.dry_run or args.diff
        repo = args.repo.expanduser().resolve()
        if repo == ROOT or ROOT.is_relative_to(repo) or repo.is_relative_to(ROOT):
            raise ValueError("Adoption target must be separate from the template sources.")
        report = audit(repo)
        profile = report["profile"] if args.profile == "auto" else args.profile
        entries = plan(repo, report, profile, args.agent)
        head = git(repo, "rev-parse", "--short", "HEAD")
        if not preview and (report["dirty"] or any(e.blocking for e in entries)):
            if verbose:
                render_verbose(report, entries)
            if debug:
                render_debug(report, entries)
        if not preview and report["dirty"]:
            print(
                "Adoption blocked.\n\nWorking tree is not clean.\n\nRun:\n"
                "  git status --short\n\nCommit or stash the current changes, then retry.\n"
                "No files modified.",
                file=sys.stderr,
            )
            sys.exit(1)
        if not preview and any(e.blocking for e in entries):
            render_blocks(entries)
            sys.exit(1)
        if not preview:
            applying = True
            apply(repo, entries)
            applied = True
            applying = False
        render_summary(
            repo, report, profile, args.agent, entries, head=head, preview=preview, verbose=verbose
        )
        if verbose:
            render_verbose(report, entries)
        if debug:
            render_debug(report, entries)
        if preview:
            if args.diff or verbose:
                render_diffs(entries, include_added=args.diff)
            print("\nResult:")
            if any(e.blocking for e in entries):
                print("  Adoption is blocked; resolve the infrastructure conflicts.")
                render_blocks(entries)
            elif report["dirty"]:
                print("  Actual adoption requires a clean working tree.")
            else:
                print("  No blocking conflicts. Adoption can be applied safely.")
                print(
                    f"Run:\n  make adopt REPO={shlex.quote(str(repo))} "
                    f"PROFILE={args.profile} AGENT={args.agent}"
                )
            print("No files modified.")
        else:
            render_success(repo, entries)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        title = (
            "Adoption applied, but reporting failed"
            if applied
            else "Adoption failed during write or rollback"
            if applying
            else "Adoption not applied"
        )
        print(f"{title}: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", []):
            print(note, file=sys.stderr)
        print("Re-run with DEBUG=1 for diagnostics.", file=sys.stderr)
        if debug:
            traceback.print_exc()
        sys.exit(1)
    except Exception as exc:
        title = "Adoption applied, but reporting failed" if applied else "Adoption failed"
        print(f"{title}: {exc}\nRe-run with DEBUG=1 for diagnostics.", file=sys.stderr)
        if debug:
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
