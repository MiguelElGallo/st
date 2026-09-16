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
client-managed plugin data directory. Rust, Homebrew, and administrator access
are not required.

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

The managed binary is pinned so an upstream update cannot silently change the
executable. Plugin releases must update the version and all six recorded
digests together.

[Back to installation](../README.md)
