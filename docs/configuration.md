# Requirements and configuration

## Requirements

- Python 3.11 or newer, available to the agent client as `python3`. On Windows,
  the current [Python install manager](https://docs.python.org/3/using/windows.html#python-install-manager)
  includes this command. Confirm with `python3 --version`; older installations
  exposing only `python.exe` need a `python3.exe` alias beside it on `PATH`.
- Network access to GitHub Releases on the first tool call.
- One of these supported platforms, with the `python3` launcher above:
  - macOS on Apple Silicon or Intel
  - Linux on ARM64 or x86-64
  - Windows on ARM64 or x86-64

On first use, the plugin downloads the official tgrep 1.0.8 binary for the
current platform, verifies its SHA-256 digest, and caches it in the
plugin data directory when the client supplies `PLUGIN_DATA`. Otherwise it uses
the user's local application cache (`LOCALAPPDATA` on Windows, `XDG_CACHE_HOME`,
or `~/.cache`). Rust, Homebrew, and administrator access are not required.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `TGREP_BIN` | Use a trusted tgrep executable instead of the managed download. |
| `TGREP_AUTO_INSTALL=0` | Disable downloads and require `tgrep` to be available on `PATH`. |
| `TGREP_WORKSPACE_ROOT` | Explicitly constrain every requested path to this workspace root. |

Without `TGREP_WORKSPACE_ROOT`, the agent supplies the active workspace root on
each tool call and the client must confirm it through the MCP roots capability.
The server fails closed when neither a client root nor the environment variable
provides an independently established boundary.

Clients without MCP roots support must set `TGREP_WORKSPACE_ROOT` in the server
environment. For a manually configured Codex MCP server named `tgrep`, its
configuration includes:

```toml
[mcp_servers.tgrep.env]
TGREP_WORKSPACE_ROOT = "/absolute/path/to/your/repository"
```

For a plugin-managed server, set the equivalent environment value in the
client's MCP server configuration and restart that server.

Use only the repository you intend to search, not your home directory. The
explicit setting takes precedence over client roots. A tool's `workspace_root`
argument selects a directory inside that trusted boundary; it cannot grant
access by itself.

The managed binary is pinned so an upstream update cannot silently change the
executable. Plugin releases must update the version and all six recorded
digests together.

Executable and cache paths are made absolute before a tool changes its working
directory. Relative settings refer to the server's starting directory, not the
searched workspace. Prefer absolute paths when configuring `TGREP_BIN`.

MCP requests have a 1 MiB wire-size limit, including the newline when present.
Oversized or invalid JSON frames are rejected; later valid requests can continue.

[Back to installation](../README.md)
