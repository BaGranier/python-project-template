# Podman rootless on Linux and WSL2

Run these commands on the Linux/WSL host, as your normal user. The temporary
Docker bootstrap container may not have access to host Podman; do not mount
the host socket into it merely to run tests.
{% if cookiecutter.coding_agent != 'none' %}
The agent always uses Podman rootless, independently of the selected human development runtime.
{% endif %}

## Installation

On Ubuntu/Debian with the packages available in the distribution repositories:

```bash
sudo apt update
sudo apt install -y \
    podman \
    uidmap \
    fuse-overlayfs \
    passt
```

`podman` is the runtime; `uidmap` provides newuidmap/newgidmap; fuse-overlayfs
supports rootless storage; `passt` provides pasta for rootless networking.
Older distribution releases may need an OS upgrade or their documented
Podman package source. Administrative installation commands are deliberate
host actions; project helpers never execute sudo automatically.

## Subordinate IDs and rootless verification

```bash
grep "^$(whoami):" /etc/subuid
grep "^$(whoami):" /etc/subgid
```

A typical allocated range is `user:100000:65536`. If absent, ask the host
administrator to allocate non-overlapping ranges. Only when the example range
is unused by other accounts, the corresponding commands are:

```bash
sudo usermod --add-subuids 100000-165535 "$(whoami)"
sudo usermod --add-subgids 100000-165535 "$(whoami)"
```

Restart the user session after changing mappings. On WSL2, a Windows terminal
may need `wsl --shutdown` before reopening the distribution. For an existing
Podman installation, follow its migration instructions after mapping changes;
do not delete container storage to repair it blindly.

```bash
command -v newuidmap
command -v newgidmap
podman info --format '{{ '{{' }}.Host.Security.Rootless{{ '}}' }}'
```

Expected rootless result: `true`. Run Podman as your regular user. Do not use
`sudo podman` for the agent: that selects a different, rootful environment.

## Rootless socket and Compose provider

{% if cookiecutter.coding_agent != 'none' %}
The agent helper selects `podman-compose` explicitly and requires it on the
host (`sudo apt install podman-compose` on supported distributions). This
provider uses the Podman CLI directly. The human dev stack can still use the
host's preferred provider. Socket setup below is needed for socket-based
providers such as docker-compose; the socket is never mounted in the agent.

{% endif %}

With a functioning systemd user session:

```bash
systemctl --user enable --now podman.socket
systemctl --user is-active podman.socket
ls -l "$XDG_RUNTIME_DIR/podman/podman.sock"
podman compose version
```

The socket status should be `active`. It lets compatible external Compose
providers communicate with rootless Podman. `podman compose` delegates to
`docker-compose` or `podman-compose`, depending on the host. A message such as
`Executing external compose provider "/usr/bin/docker-compose"` is normal;
the container engine remains Podman. If no provider is installed, install a
distribution-supported provider (for example `sudo apt install podman-compose`)
and check `podman compose version` again. `PODMAN_COMPOSE_PROVIDER` can select
an installed provider explicitly.

The socket grants control of the user's containers. Keep it on the host;
never mount it into the agent or bootstrap container and never expose it via
an unauthenticated TCP endpoint.

## Compose smoke test

This creates an isolated temporary project; confirm the smoke container appears
in `podman ps`, then stop it. If a command fails, run down before removing the
temporary directory.

```bash
tmpdir="$(mktemp -d)"
cd "$tmpdir"
cat > compose.yaml <<'EOF'
services:
  smoke:
    image: docker.io/library/alpine:latest
    command: ["sh", "-c", "sleep 30"]
EOF
podman compose -p "podman-smoke-$$" up -d
podman ps
podman compose -p "podman-smoke-$$" down
cd -
rm -rf "$tmpdir"
```

The mutable image tags here are only for ad hoc diagnostics, not the project
Containerfile's version policy.

## Networking and published ports

Verify outbound access:

```bash
podman run --rm docker.io/library/alpine:latest \
    wget -qO- https://example.com
```

Verify port forwarding on a free local port (change 18080 if occupied):

```bash
podman run --rm \
    -p 127.0.0.1:18080:80 \
    docker.io/library/nginx:alpine
```

In another terminal, run `curl http://127.0.0.1:18080`. On WSL2 also open
`http://localhost:18080` from Windows. Stop the foreground container with Ctrl-C.
Project ports remain configurable through `.env`; localhost is the default
host binding. Application servers inside containers must listen on 0.0.0.0.
{% if cookiecutter.coding_agent != 'none' %}
Agent values are preferred ports, with automatic collision fallback and
persistent effective mappings. Use `make agent-status` for current URLs.
{% endif %}
Automated template tests allocate distinct ephemeral host ports instead of
assuming 8000 or other common ports are free. Port selection releases the
reservation before container startup, so another process can still race it.

## WSL2

Keep repositories under `~/projects/my-project`, rather than
`/mnt/c/Users/.../my-project`, for Git, uv, Unix permissions and many small files.
If `systemctl --user` cannot connect, verify systemd is enabled in the WSL
distribution. See Microsoft's [systemd instructions](https://learn.microsoft.com/windows/wsl/systemd).
After changing WSL configuration or subordinate IDs, use `wsl --shutdown`
from Windows and reopen WSL. This host administration command does not imply
native PowerShell support for project scripts.

## Copyable diagnostics

The `|| true` clauses below intentionally let this diagnostic block continue
when an optional tool or inactive socket needs attention; lifecycle commands
do not suppress those errors.

```bash
echo "=== USER ==="
whoami
id
echo
echo "=== PODMAN ==="
podman --version
echo
echo "=== ROOTLESS ==="
podman info --format '{{ '{{' }}.Host.Security.Rootless{{ '}}' }}'
echo
echo "=== SOCKET ==="
systemctl --user is-active podman.socket || true
ls -l "$XDG_RUNTIME_DIR/podman/podman.sock" || true
echo
echo "=== SUBUID ==="
grep "^$(whoami):" /etc/subuid
echo
echo "=== SUBGID ==="
grep "^$(whoami):" /etc/subgid
echo
echo "=== UIDMAP ==="
command -v newuidmap
command -v newgidmap
echo
echo "=== NETWORK ==="
command -v pasta || true
echo
echo "=== STORAGE ==="
command -v fuse-overlayfs || true
echo
echo "=== COMPOSE ==="
podman compose version
```

## Troubleshooting

### Podman says there is no systemd user session

Symptoms include `The cgroupv2 manager is set to systemd but there is no systemd
user session available`, `Failed to connect to bus: No such file or directory`,
or a missing `/run/user/<uid>/bus`.

First run `ps -p 1 -o comm=`. If it prints `systemd` and `/etc/wsl.conf` already
contains `[boot]` with `systemd=true`, do not immediately change configuration
or reinstall systemd. Close relevant WSL shells/processes, then from Windows:

```powershell
wsl --shutdown
```

Reopen WSL and retest:

```bash
ps -p 1 -o comm=
systemctl --user status
podman info --format '{{ '{{' }}.Host.Security.Rootless{{ '}}' }}'
```

If systemd is already enabled but its user session is inconsistent, this full
WSL shutdown is the first remedy. Only if it persists, inspect:

```bash
cat /etc/wsl.conf
echo "$XDG_RUNTIME_DIR"
loginctl user-status "$USER"
```

Then continue the diagnostics below. A fallback from systemd cgroups to
cgroupfs can be a warning while rootless execution still works.
{% if cookiecutter.coding_agent != 'none' %}
agent-check does not reject it solely for that warning. Missing rootless execution,
podman-compose, or the selected CLI in an existing image is a blocking error.
{% endif %}

| Symptom | Check and remedy |
| --- | --- |
| `rootless=false` | Use your regular user, not sudo/root; inspect `podman info` and subordinate IDs. |
| Missing subuid/subgid | Have the administrator allocate non-overlapping ranges; restart the session. |
| Missing newuidmap/newgidmap | Install `uidmap`, then verify both executables. |
| Missing pasta / networking fails | Install `passt`; inspect Podman network configuration and run the outbound smoke test. |
| Missing fuse-overlayfs / storage fails | Install `fuse-overlayfs`; inspect `podman info` storage details. |
| Socket inactive or missing | Enable `podman.socket` with systemctl --user; check the user session and XDG_RUNTIME_DIR. |
| No Compose provider | Install a supported provider; run `podman compose version`. |
| Port already in use | Identify the listener, then change the relevant `.env` port and recreate the stack. |

For example, identify a listener with `ss -ltnp | grep ':8000'`. Do not kill a
process arbitrarily before identifying its purpose. The Docker bootstrap may
legitimately own this port. Runtime tests must still pass with it running.

References: [rootless tutorial](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md),
[socket service](https://docs.podman.io/en/latest/markdown/podman-system-service.1.html),
[Compose providers](https://docs.podman.io/en/latest/markdown/podman-compose.1.html).

{% if cookiecutter.coding_agent != 'none' %}
## Disk usage and cleanup

Run `make agent-disk` and `podman system df -v` to distinguish writable layers,
images, persistent volumes, caches and the agent Git workspace. Successful
pytest temporary projects are deleted; the last failed session is retained.
`make test-disk-report` shows retained fixtures and generated `.venv` sizes.

`agent-stop` removes this disposable runtime/network without deleting named
volumes, credentials, `.agent/workspace` or `.agent/state.json`. A later start
has a fresh `/tmp`. `agent-clean-temp` explicitly cleans known pytest data;
`agent-clean-cache` explicitly cleans uv/npm caches inside the running agent.
Neither command treats credentials, the workspace, state or venv as cache.
Caches are not purged at stop. There is no persistent `/tmp` volume or tmpfs.

See [Disk usage and cleanup](agent.md#disk-usage-and-cleanup) for measurement,
one-time removal of reviewed obsolete containers, and host WSL stop/start
validation. Never run global system/image/volume pruning to clean this project.
{% endif %}
