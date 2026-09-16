"""Generate the self-contained VS Code adapter from the portable tgrep package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANONICAL = REPO / "plugins/tgrep"
DESTINATION = REPO / "plugins/vscode/tgrep"
COPIED_FILES = (
    "LICENSE",
    ".mcp.json",
    "mcp_server/__init__.py",
    "mcp_server/server.py",
    "skills/tgrep-search/SKILL.md",
    "third_party/tgrep-LICENSE.txt",
)


def expected_files() -> dict[str, bytes]:
    """Use a fixed inventory; never package repository media or build outputs."""
    files = {name: (CANONICAL / name).read_bytes() for name in COPIED_FILES}
    manifest = json.loads((CANONICAL / "plugin.json").read_text(encoding="utf-8"))
    manifest.pop("$schema")
    manifest["skills"] = "./skills/"
    manifest["mcpServers"] = "./.mcp.json"
    files["plugin.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return files


def main() -> None:
    """Write deterministic package files, or fail if any expected bytes differ."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    for name, content in expected_files().items():
        destination = DESTINATION / name
        if destination.is_symlink():
            raise SystemExit(f"Refusing generated symlink: {destination}")
        if options.check:
            if not destination.is_file() or destination.read_bytes() != content:
                raise SystemExit(f"Regenerate VS Code adapter: {name}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)


if __name__ == "__main__":
    main()
