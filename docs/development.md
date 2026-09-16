# Development and testing

Run the automated checks from the repository root:

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 -m compileall -q plugins tests
ruff check plugins tests
ruff format --check plugins tests
ty check plugins tests
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

The single portable package is in `plugins/tgrep`. VS Code and Codex both load
that Agent Plugins 1.0 package; there is no client-specific copy to synchronize.

[Back to installation](../README.md)
