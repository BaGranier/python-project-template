# Getting started

Install uv, Git and GNU Make. Supported: Linux/WSL2 with bash/zsh;
macOS best effort. Native Windows shells are outside the initial scope.

```bash
cd ~/projects
cruft create <template>
cd {{ cookiecutter.project_slug }}
make init
make shell
make check
```

`make init` checks the canonical project root, creates a project-local `.git`
on branch main if missing (even inside a parent repository), and checks Git
identity before committing. Set it yourself if needed:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
make init
```

It calls `make setup`, then stages non-ignored files and creates
`chore: initialize project`. Repeating init synchronizes the environment without
another commit. Existing committed repositories keep all user changes untouched.
For an existing repository with no commit that init did not create, review and
create the first commit manually; init refuses to silently stage that work.
If initialization is interrupted, correct the reported error and rerun init.

`make setup` synchronizes uv (creating uv.lock if needed), creates `.env` only
when absent and installs pre-commit when this project has its own Git repository.
It never initializes Git or creates a commit. Package `author_name` is independent
of the user's Git identity. Real projects belong beside the template, not in
its disposable ignored `generated/` directory.
{% if cookiecutter.coding_agent != 'none' %}

After initialization, use `make agent-check`, then `make agent-login` and `make agent`.
For noninteractive validation use `make agent-start`, `make agent-status`,
and `make agent-test`. Read [Podman setup](podman.md) first.
{% endif %}

Use `exit` to leave the child shell. Normal Bash/Zsh startup files and existing Oh My Zsh are loaded; the child
receives the project virtual environment. The parent shell is unchanged.
