# Development and testing

Run the automated checks from the repository root:

```sh
python3 -m pip install -r requirements-dev.txt
python3 scripts/build_vscode_plugin.py
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins tests
ruff check plugins scripts tests
ruff format --check plugins scripts tests
ty check plugins scripts tests
```

Validate the manifests, marketplace wiring, documentation references, and
license attribution with the packaging tests:

```sh
python3 -m unittest tests/test_server.py -v
```

Set `TGREP_LIVE_TEST=1` to include a real managed download and search on the
current platform. CI runs that live acceptance test on Linux, macOS, and Windows.

The tests cover platform selection, verified download and extraction, upstream
license placement, path containment, command construction, JSON-RPC behavior,
manifests, marketplace wiring, documentation links, and release media.

The canonical Agent Plugins 1.0 package is in `plugins/tgrep`; Codex loads it.
VS Code 1.138 currently leaves portable MCP `${PLUGIN_ROOT}` placeholders
unexpanded. Its marketplace therefore selects the native compatibility package
at `plugins/vscode/tgrep`, generated from the canonical source. It is
self-contained, with identical server, skill, and license bytes. Do not edit the
generated files: run `python3 scripts/build_vscode_plugin.py` after canonical
changes. CI verifies byte equality and the complete tracked package inventory.
Git preserves LF line endings in both packages for deterministic Windows
checkouts. Neither package includes the videos or marketing tools.

[Back to installation](../README.md)
