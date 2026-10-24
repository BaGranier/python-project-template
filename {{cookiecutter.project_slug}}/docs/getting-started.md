# Getting started

Install uv, Git and GNU Make. Supported: Linux/WSL2 with bash/zsh;
macOS best effort. Native Windows shells are outside the initial scope.

```bash
make setup
make shell
make check
```

`make setup` synchronizes uv (creating uv.lock if needed), creates `.env` only
when absent and installs pre-commit when this project is a Git repository.
Initialize Git and commit all generated sources and uv.lock before agent use.
Use `exit` to leave the child shell. Its startup files are skipped intentionally.
