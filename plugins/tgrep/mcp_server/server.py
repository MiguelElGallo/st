"""Dependency-free MCP stdio server for the Microsoft tgrep CLI."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

SERVER_NAME = "tgrep"
SERVER_VERSION = "0.1.0"
TGREP_VERSION = "1.0.8"
PROTOCOL_VERSION = "2024-11-05"
UPSTREAM_REPOSITORY = "microsoft/tgrep"

# GitHub's SHA-256 digest for each official v1.0.8 release asset. Keeping the
# values in the reviewed plugin makes first-use installation deterministic even
# on platforms omitted from upstream's checksums.txt (currently Windows).
_RELEASES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("Darwin", "arm64"): (
        "aarch64-apple-darwin",
        "tar.gz",
        "b3a352060c329913750f9481c8f01de7e9b8ac33f533fd8c715b92542571659e",
    ),
    ("Darwin", "x86_64"): (
        "x86_64-apple-darwin",
        "tar.gz",
        "62a1c4448aac4413363f1dedd4f73b35fb2999c46b9971fed8b8e2f2a9967aad",
    ),
    ("Linux", "aarch64"): (
        "aarch64-unknown-linux-musl",
        "tar.gz",
        "618e1b80a7e95b47cb91a6ececd07294c397b34ffb00e25d78600c74eb87566e",
    ),
    ("Linux", "x86_64"): (
        "x86_64-unknown-linux-musl",
        "tar.gz",
        "2e3de5b7735eb84aa150d3a48e8cff8f27c05795bfccb8b52c9bd8881f7225ce",
    ),
    ("Windows", "arm64"): (
        "aarch64-pc-windows-msvc",
        "zip",
        "2021f95537887e299b01127e5403981dcebd0be771bcd24a70ccd0210c76b04b",
    ),
    ("Windows", "x86_64"): (
        "x86_64-pc-windows-msvc",
        "zip",
        "e29165914e56bba0296d369d1d4ab4c62074711c90bcafaf8d3567f2811515c0",
    ),
}

_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "Regex or literal search text."},
        "workspace_root": {
            "type": "string",
            "description": "Absolute path of the active repository or workspace root.",
        },
        "path": {
            "type": "string",
            "description": "File or directory under the workspace root. Defaults to '.'.",
            "default": ".",
        },
        "fixed_strings": {
            "type": "boolean",
            "description": "Treat pattern as literal text (-F).",
            "default": False,
        },
        "ignore_case": {"type": "boolean", "default": False},
        "smart_case": {"type": "boolean", "default": False},
        "word_regexp": {"type": "boolean", "default": False},
        "glob": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Repeatable tgrep glob filters.",
        },
        "file_type": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Repeatable file types such as py, rust, or js.",
        },
        "context": {
            "type": "integer",
            "minimum": 0,
            "maximum": 100,
            "default": 0,
        },
        "files_with_matches": {"type": "boolean", "default": False},
        "count": {"type": "boolean", "default": False},
        "max_count": {"type": "integer", "minimum": 1, "maximum": 100000},
        "hidden": {"type": "boolean", "default": False},
        "fresh": {
            "type": "boolean",
            "description": "Bypass the index and scan current files (--no-index).",
            "default": False,
        },
        "timeout_seconds": {
            "type": "integer",
            "minimum": 1,
            "maximum": 300,
            "default": 30,
        },
        "max_output_chars": {
            "type": "integer",
            "minimum": 1000,
            "maximum": 200000,
            "default": 50000,
        },
    },
    "required": ["pattern", "workspace_root"],
    "additionalProperties": False,
}

_INDEX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "workspace_root": {
            "type": "string",
            "description": "Absolute path of the active repository or workspace root.",
        },
        "path": {"type": "string", "default": "."},
        "exclude": {"type": "array", "items": {"type": "string"}},
        "no_ignore": {"type": "boolean", "default": False},
        "no_require_git": {"type": "boolean", "default": False},
        "max_filesize": {
            "type": "string",
            "description": "Maximum indexed file size, for example 8M or 1G.",
        },
        "threads": {"type": "integer", "minimum": 1, "maximum": 256},
        "timeout_seconds": {
            "type": "integer",
            "minimum": 1,
            "maximum": 3600,
            "default": 600,
        },
    },
    "required": ["workspace_root"],
    "additionalProperties": False,
}

_STATUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "workspace_root": {
            "type": "string",
            "description": "Absolute path of the active repository or workspace root.",
        },
        "path": {"type": "string", "default": "."},
    },
    "required": ["workspace_root"],
    "additionalProperties": False,
}

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "tgrep_search",
        "description": (
            "Fast regex or literal search inside the current workspace. Use "
            "fixed_strings for symbols, file_type/glob to narrow, and fresh "
            "when the latest filesystem contents are required."
        ),
        "inputSchema": _SEARCH_SCHEMA,
    },
    {
        "name": "tgrep_index",
        "description": (
            "Build or refresh a persistent .tgrep index for a directory inside "
            "the current workspace."
        ),
        "inputSchema": _INDEX_SCHEMA,
    },
    {
        "name": "tgrep_status",
        "description": "Report the tgrep server status for a workspace directory.",
        "inputSchema": _STATUS_SCHEMA,
    },
]

_ROOTS_REQUEST_ID = "tgrep-roots-1"
_CLIENT_ROOTS: list[Path] = []
_CLIENT_SUPPORTS_ROOTS = False


def _normalized_machine() -> str:
    """Return the architecture spelling used by the release matrix."""
    machine = platform.machine().lower()
    if machine in {"amd64", "x64"}:
        return "x86_64"
    if machine == "arm64":
        return "arm64"
    return machine


def _release_asset() -> tuple[str, str, str, str]:
    """Return target, archive kind, executable name, and expected digest."""
    system = platform.system()
    machine = _normalized_machine()
    try:
        target, archive_kind, digest = _RELEASES[(system, machine)]
    except KeyError as exc:
        raise RuntimeError(
            "automatic tgrep installation is not available for "
            f"{system} {platform.machine()}"
        ) from exc
    executable = "tgrep.exe" if system == "Windows" else "tgrep"
    return target, archive_kind, executable, digest


def _plugin_data_dir() -> Path:
    """Return writable persistent storage for the managed tgrep binary."""
    plugin_data = os.environ.get("PLUGIN_DATA")
    if plugin_data and plugin_data != "${PLUGIN_DATA}":
        return Path(plugin_data)
    if sys.platform == "win32" and (local := os.environ.get("LOCALAPPDATA")):
        return Path(local) / "tgrep-agent-plugin"
    if cache := os.environ.get("XDG_CACHE_HOME"):
        return Path(cache) / "tgrep-agent-plugin"
    return Path.home() / ".cache" / "tgrep-agent-plugin"


def _download_file(url: str, destination: Path) -> None:
    """Download a release asset without shell interpolation."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "tgrep-agent-plugin/0.1.0"}
    )
    with (
        urllib.request.urlopen(request, timeout=90) as response,
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output)


def _sha256(path: Path) -> str:
    """Hash a file without reading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract_binary(
    archive_path: Path, archive_kind: str, executable_name: str, destination: Path
) -> None:
    """Extract exactly one binary by basename, without unpacking other entries."""
    if archive_kind == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                name
                for name in archive.namelist()
                if not name.endswith("/") and Path(name).name == executable_name
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    "release archive must contain exactly one tgrep binary"
                )
            with archive.open(matches[0]) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
        return

    with tarfile.open(archive_path, "r:gz") as archive:
        matches = [
            member
            for member in archive.getmembers()
            if member.isfile() and Path(member.name).name == executable_name
        ]
        if len(matches) != 1:
            raise RuntimeError("release archive must contain exactly one tgrep binary")
        source = archive.extractfile(matches[0])
        if source is None:
            raise RuntimeError("release archive binary could not be read")
        with source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)


def _bundled_upstream_license() -> Path:
    return Path(__file__).resolve().parents[1] / "third_party" / "tgrep-LICENSE.txt"


def _install_tgrep() -> str:
    """Download, verify, extract, and cache the pinned official tgrep release."""
    target, archive_kind, executable_name, expected_archive_digest = _release_asset()
    tag = f"v{TGREP_VERSION}"
    suffix = "zip" if archive_kind == "zip" else "tar.gz"
    archive_name = f"tgrep-{tag}-{target}.{suffix}"
    base_url = f"https://github.com/{UPSTREAM_REPOSITORY}/releases/download/{tag}"
    install_dir = _plugin_data_dir() / "bin" / tag / target
    installed_binary = install_dir / executable_name
    binary_digest_path = install_dir / f"{executable_name}.sha256"
    installed_license = install_dir / "LICENSE.microsoft-tgrep.txt"
    bundled_license = _bundled_upstream_license()

    if installed_binary.is_file() and binary_digest_path.is_file():
        expected_binary_digest = binary_digest_path.read_text(encoding="ascii").strip()
        if re.fullmatch(r"[0-9a-f]{64}", expected_binary_digest) and (
            _sha256(installed_binary) == expected_binary_digest
        ):
            shutil.copyfile(bundled_license, installed_license)
            return str(installed_binary)

    install_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=install_dir) as temporary_dir:
        temporary_path = Path(temporary_dir)
        archive_path = temporary_path / archive_name
        staged_binary = temporary_path / executable_name
        _download_file(f"{base_url}/{archive_name}", archive_path)
        actual_archive_digest = _sha256(archive_path)
        if actual_archive_digest != expected_archive_digest:
            raise RuntimeError(
                "tgrep release archive checksum verification failed: "
                f"expected {expected_archive_digest}, got {actual_archive_digest}"
            )
        _extract_binary(archive_path, archive_kind, executable_name, staged_binary)
        staged_binary.chmod(0o755)
        binary_digest = _sha256(staged_binary)
        staged_digest = temporary_path / f"{executable_name}.sha256"
        staged_digest.write_text(f"{binary_digest}\n", encoding="ascii")
        os.replace(staged_binary, installed_binary)
        os.replace(staged_digest, binary_digest_path)
        shutil.copyfile(bundled_license, installed_license)
    return str(installed_binary)


def _find_tgrep() -> str:
    """Prefer a user override, then the verified managed release, then PATH."""
    if override := os.environ.get("TGREP_BIN"):
        candidate = Path(override).expanduser()
        if not candidate.is_file():
            raise FileNotFoundError(f"TGREP_BIN is not a file: {candidate}")
        return str(candidate)

    if os.environ.get("TGREP_AUTO_INSTALL", "1").lower() not in {
        "0",
        "false",
        "no",
    }:
        try:
            return _install_tgrep()
        except Exception as exc:
            raise RuntimeError(
                "automatic tgrep installation failed: "
                f"{exc}. Set TGREP_BIN to a trusted executable or install tgrep "
                "and set TGREP_AUTO_INSTALL=0."
            ) from exc

    if found := shutil.which("tgrep"):
        return found
    raise FileNotFoundError(
        "tgrep was not found and automatic installation is disabled. Install "
        "tgrep, or set TGREP_BIN to its executable path."
    )


def _workspace_roots(explicit_root: Any = None) -> list[Path]:
    """Return roots with the explicit workspace selected as the primary root."""
    configured = os.environ.get("TGREP_WORKSPACE_ROOT")
    allowed_roots = (
        [Path(configured).expanduser()] if configured else list(_CLIENT_ROOTS)
    )
    resolved_allowed: list[Path] = []
    for root in allowed_roots:
        try:
            resolved_allowed.append(root.resolve(strict=True))
        except OSError as exc:
            raise ValueError(f"workspace root is unavailable: {root}: {exc}") from exc

    if not resolved_allowed:
        raise ValueError(
            "no trusted workspace root is available; the client must expose MCP "
            "roots or TGREP_WORKSPACE_ROOT must be configured"
        )
    if explicit_root is None:
        return resolved_allowed
    if not isinstance(explicit_root, str) or not explicit_root.strip():
        raise ValueError("workspace_root must be a non-empty absolute path")
    supplied_root = Path(explicit_root).expanduser()
    if not supplied_root.is_absolute():
        raise ValueError("workspace_root must be an absolute path")
    try:
        resolved_explicit = supplied_root.resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            f"workspace root is unavailable: {supplied_root}: {exc}"
        ) from exc

    if resolved_allowed and not any(
        resolved_explicit.is_relative_to(allowed) for allowed in resolved_allowed
    ):
        joined = ", ".join(str(allowed) for allowed in resolved_allowed)
        raise ValueError(f"workspace_root must stay within a client root: {joined}")
    return [resolved_explicit]


def _workspace_root(explicit_root: Any = None) -> Path:
    """Return the primary workspace root used for relative paths and cwd."""
    return _workspace_roots(explicit_root)[0]


def _store_client_roots(result: Any) -> None:
    """Store valid local filesystem roots returned by the MCP client."""
    if not isinstance(result, dict) or not isinstance(result.get("roots"), list):
        return
    roots: list[Path] = []
    for item in result["roots"]:
        if not isinstance(item, dict) or not isinstance(item.get("uri"), str):
            continue
        parsed = urlparse(item["uri"])
        if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
            continue
        local_path = Path(urllib.request.url2pathname(unquote(parsed.path)))
        try:
            resolved = local_path.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    _CLIENT_ROOTS[:] = roots


def _resolve_workspace_path(
    raw_path: Any, *, workspace_root: Any, directory: bool = False
) -> Path:
    """Resolve a user path and reject traversal outside the workspace root."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("path must be a non-empty string")
    roots = _workspace_roots(workspace_root)
    root = roots[0]
    supplied = Path(raw_path).expanduser()
    candidate = supplied if supplied.is_absolute() else root / supplied
    unresolved = candidate.resolve(strict=False)
    matching_root = next(
        (allowed for allowed in roots if unresolved.is_relative_to(allowed)), None
    )
    if matching_root is None:
        joined = ", ".join(str(allowed) for allowed in roots)
        raise ValueError(f"path must stay within a workspace root: {joined}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"path does not exist: {raw_path}: {exc}") from exc
    if directory and not resolved.is_dir():
        raise ValueError(f"path must be a directory: {raw_path}")
    return resolved


def _validate_known_arguments(arguments: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Validate the simple JSON types and bounds used by one tool schema."""
    if not isinstance(arguments, dict):
        raise TypeError("tool arguments must be an object")
    properties = schema["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ValueError(f"unknown argument: {unknown[0]}")
    for required in schema.get("required", []):
        if required not in arguments:
            raise ValueError(f"missing required argument: {required}")
    for name, value in arguments.items():
        rule = properties[name]
        kind = rule["type"]
        if kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
        if kind == "string" and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{name} must be a non-empty string")
        if kind == "integer":
            if type(value) is not int:
                raise ValueError(f"{name} must be an integer")
            if value < rule.get("minimum", value) or value > rule.get("maximum", value):
                raise ValueError(
                    f"{name} must be from {rule.get('minimum')} to {rule.get('maximum')}"
                )
        if kind == "array":
            if not isinstance(value, list) or not value:
                raise ValueError(f"{name} must be a non-empty array")
            if not all(isinstance(item, str) and item.strip() for item in value):
                raise ValueError(f"{name} entries must be non-empty strings")
    return arguments


def _text_result(
    result: subprocess.CompletedProcess[str],
    *,
    max_output_chars: int,
    omitted_output_bytes: int = 0,
) -> dict[str, Any]:
    """Convert a completed tgrep process into an MCP text result."""
    sections = [f"exit_code: {result.returncode}"]
    if result.stdout:
        sections.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr:
        sections.append(f"stderr:\n{result.stderr.rstrip()}")
    text = "\n".join(sections)
    if omitted_output_bytes:
        marker = f"[truncated {omitted_output_bytes} output bytes]"
        keep = max(0, max_output_chars - len(marker) - 1)
        text = f"{text[:keep]}\n{marker}"
    elif len(text) > max_output_chars:
        omitted = len(text) - max_output_chars
        marker = f"[truncated {omitted} characters]"
        keep = max(0, max_output_chars - len(marker) - 1)
        text = f"{text[:keep]}\n{marker}"
    response: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if result.returncode not in {0, 1}:
        response["isError"] = True
    return response


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    timeout: int,
    max_output_chars: int,
    allowed_exit_codes: frozenset[int] = frozenset({0, 1}),
) -> dict[str, Any]:
    """Run tgrep without a shell while bounding captured output memory."""
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"could not start tgrep: {exc}"}],
        }

    streams = ((process.stdout, []), (process.stderr, []))
    capture_lock = threading.Lock()
    capture_state = {"remaining": max_output_chars, "omitted": 0}

    def drain(stream: Any, chunks: list[bytes]) -> None:
        try:
            while block := stream.read(64 * 1024):
                with capture_lock:
                    keep = min(len(block), capture_state["remaining"])
                    if keep:
                        chunks.append(block[:keep])
                        capture_state["remaining"] -= keep
                    capture_state["omitted"] += len(block) - keep
        finally:
            stream.close()

    threads = [
        threading.Thread(target=drain, args=(stream, chunks), daemon=True)
        for stream, chunks in streams
    ]
    for thread in threads:
        thread.start()
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        for thread in threads:
            thread.join()
        return {
            "isError": True,
            "content": [
                {"type": "text", "text": f"tgrep timed out after {timeout} seconds"}
            ],
        }
    for thread in threads:
        thread.join()
    stdout = b"".join(streams[0][1]).decode("utf-8", errors="replace")
    stderr = b"".join(streams[1][1]).decode("utf-8", errors="replace")
    result = subprocess.CompletedProcess(command, return_code, stdout, stderr)
    response = _text_result(
        result,
        max_output_chars=max_output_chars,
        omitted_output_bytes=capture_state["omitted"],
    )
    if return_code not in allowed_exit_codes:
        response["isError"] = True
    else:
        response.pop("isError", None)
    return response


def _tool_error(exc: Exception) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}


def _run_search(arguments: Any) -> dict[str, Any]:
    """Validate and execute an allowlisted tgrep search."""
    try:
        args = _validate_known_arguments(arguments, _SEARCH_SCHEMA)
        if args.get("ignore_case") and args.get("smart_case"):
            raise ValueError("ignore_case and smart_case cannot both be true")
        if args.get("files_with_matches") and args.get("count"):
            raise ValueError("files_with_matches and count cannot both be true")
        root = _workspace_root(args["workspace_root"])
        path = _resolve_workspace_path(
            args.get("path", "."), workspace_root=args["workspace_root"]
        )
        binary = _find_tgrep()
    except (FileNotFoundError, RuntimeError, TypeError, ValueError) as exc:
        return _tool_error(exc)

    command = [binary]
    boolean_flags = {
        "fixed_strings": "-F",
        "ignore_case": "-i",
        "smart_case": "-S",
        "word_regexp": "-w",
        "files_with_matches": "-l",
        "count": "-c",
        "hidden": "--hidden",
        "fresh": "--no-index",
    }
    command.extend(flag for name, flag in boolean_flags.items() if args.get(name))
    if context := args.get("context"):
        command.extend(["-C", str(context)])
    if max_count := args.get("max_count"):
        command.extend(["-m", str(max_count)])
    for glob in args.get("glob", []):
        command.extend(["-g", glob])
    for file_type in args.get("file_type", []):
        command.extend(["-t", file_type])
    command.extend(["--", args["pattern"], str(path)])
    return _run_process(
        command,
        cwd=root,
        timeout=args.get("timeout_seconds", 30),
        max_output_chars=args.get("max_output_chars", 50000),
    )


def _run_index(arguments: Any) -> dict[str, Any]:
    """Validate and execute tgrep index within the workspace."""
    try:
        args = _validate_known_arguments(arguments, _INDEX_SCHEMA)
        root = _workspace_root(args["workspace_root"])
        path = _resolve_workspace_path(
            args.get("path", "."),
            workspace_root=args["workspace_root"],
            directory=True,
        )
        max_filesize = args.get("max_filesize")
        if max_filesize and not re.fullmatch(r"[1-9][0-9]*(?:[KMG])?", max_filesize):
            raise ValueError("max_filesize must look like 1024, 8M, or 1G")
        binary = _find_tgrep()
    except (FileNotFoundError, RuntimeError, TypeError, ValueError) as exc:
        return _tool_error(exc)

    command = [binary, "index", str(path)]
    if args.get("no_ignore"):
        command.append("--no-ignore")
    if args.get("no_require_git"):
        command.append("--no-require-git")
    if max_filesize:
        command.extend(["--max-filesize", max_filesize])
    if threads := args.get("threads"):
        command.extend(["--threads", str(threads)])
    for excluded in args.get("exclude", []):
        command.extend(["--exclude", excluded])
    return _run_process(
        command,
        cwd=root,
        timeout=args.get("timeout_seconds", 600),
        max_output_chars=50000,
        allowed_exit_codes=frozenset({0}),
    )


def _run_status(arguments: Any) -> dict[str, Any]:
    """Validate and execute tgrep status within the workspace."""
    try:
        args = _validate_known_arguments(arguments, _STATUS_SCHEMA)
        root = _workspace_root(args["workspace_root"])
        path = _resolve_workspace_path(
            args.get("path", "."),
            workspace_root=args["workspace_root"],
            directory=True,
        )
        binary = _find_tgrep()
    except (FileNotFoundError, RuntimeError, TypeError, ValueError) as exc:
        return _tool_error(exc)
    return _run_process(
        [binary, "status", str(path)],
        cwd=root,
        timeout=30,
        max_output_chars=50000,
        allowed_exit_codes=frozenset({0}),
    )


def _send(response: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _handle(request: Any) -> dict[str, Any] | None:
    """Handle one newline-delimited MCP JSON-RPC request."""
    if not isinstance(request, dict):
        return _error_response(None, -32600, "Invalid Request: expected an object")
    request_id = request.get("id")
    method = request.get("method", "")
    if not method and request_id == _ROOTS_REQUEST_ID:
        _store_client_roots(request.get("result"))
        return None
    raw_params = request.get("params")
    if raw_params is not None and not isinstance(raw_params, dict):
        if request_id is not None:
            return _error_response(
                request_id, -32602, "Invalid params: expected an object"
            )
        return None
    params = raw_params or {}
    if method == "initialize":
        global _CLIENT_SUPPORTS_ROOTS
        capabilities = params.get("capabilities")
        _CLIENT_SUPPORTS_ROOTS = isinstance(capabilities, dict) and isinstance(
            capabilities.get("roots"), dict
        )
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method in {"initialized", "notifications/initialized"}:
        if _CLIENT_SUPPORTS_ROOTS:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": _ROOTS_REQUEST_ID,
                    "method": "roots/list",
                    "params": {},
                }
            )
        return None
    if method == "notifications/roots/list_changed":
        if _CLIENT_SUPPORTS_ROOTS:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": _ROOTS_REQUEST_ID,
                    "method": "roots/list",
                    "params": {},
                }
            )
        return None
    if method.startswith("notifications/"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handlers = {
            "tgrep_search": _run_search,
            "tgrep_index": _run_index,
            "tgrep_status": _run_status,
        }
        if name not in handlers:
            return _error_response(request_id, -32601, f"Unknown tool: {name}")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": handlers[name](arguments),
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if request_id is not None:
        return _error_response(request_id, -32601, f"Method not found: {method}")
    return None


def main() -> None:
    """Serve newline-delimited JSON-RPC on standard input and output."""
    for raw_line in sys.stdin:
        if not (raw_line := raw_line.strip()):
            continue
        try:
            request = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            _send(_error_response(None, -32700, f"Parse error: {exc}"))
            continue
        try:
            response = _handle(request)
        except Exception as exc:  # noqa: BLE001 - keep the MCP server alive
            request_id = request.get("id") if isinstance(request, dict) else None
            _send(_error_response(request_id, -32603, f"Internal error: {exc}"))
            continue
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
