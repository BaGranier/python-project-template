"""Validate rendered context without interpolating user text into Python syntax."""

import json
import keyword
import re
import sys

context = json.loads(r'''{{ cookiecutter | tojson }}''')


def fail(message):
    sys.exit(f"Invalid project configuration: {message}")


if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", context["project_slug"]):
    fail("project_slug must contain lowercase words separated by single hyphens.")
package = context["package_name"]
if not re.fullmatch(r"[a-z][a-z0-9_]*", package) or keyword.iskeyword(package):
    fail("package_name must be a lowercase Python identifier, not a keyword.")
if not re.fullmatch(r"3\.(?:1[2-9]|[2-9][0-9])(?:\.(?:0|[1-9][0-9]*))?", context["python_version"]):
    fail("python_version must be 3.12 or newer, e.g. 3.12 or 3.12.9.")
for key in ("project_name", "description", "author_name"):
    if any(ord(c) < 32 or ord(c) == 127 for c in context[key]):
        fail(f"{key} cannot contain control characters.")
    if any(c in context[key] for c in ("<", ">", "`", "$", "\\", "\"", "'")):
        fail(f"{key} contains unsafe punctuation.")
for key, choices in {
    "dev_container_runtime": {"podman", "docker", "none"},
    "ci_provider": {"github", "gitlab", "none"},
    "enable_notebooks": {"yes", "no"},
    "enable_docs": {"yes", "no"},
    "enable_agent": {"yes", "no"},
}.items():
    if context[key] not in choices:
        fail(f"unknown {key}: {context[key]}")
