from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = REPOSITORY_ROOT / "plugins/tgrep/mcp_server/server.py"
SPEC = importlib.util.spec_from_file_location("tgrep_plugin_server", SERVER_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class ReleaseSelectionTests(unittest.TestCase):
    def test_selects_every_published_platform_asset(self) -> None:
        cases = [
            ("Darwin", "arm64", "aarch64-apple-darwin", "tar.gz", "tgrep"),
            ("Darwin", "AMD64", "x86_64-apple-darwin", "tar.gz", "tgrep"),
            ("Linux", "aarch64", "aarch64-unknown-linux-musl", "tar.gz", "tgrep"),
            ("Linux", "x86_64", "x86_64-unknown-linux-musl", "tar.gz", "tgrep"),
            ("Windows", "arm64", "aarch64-pc-windows-msvc", "zip", "tgrep.exe"),
            ("Windows", "AMD64", "x86_64-pc-windows-msvc", "zip", "tgrep.exe"),
        ]
        for system, machine, target, archive, executable in cases:
            with (
                self.subTest(system=system, machine=machine),
                mock.patch.object(server.platform, "system", return_value=system),
                mock.patch.object(server.platform, "machine", return_value=machine),
            ):
                selected_target, kind, selected_executable, digest = (
                    server._release_asset()
                )
                self.assertEqual(selected_target, target)
                self.assertEqual(kind, archive)
                self.assertEqual(selected_executable, executable)
                self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_rejects_an_unsupported_platform(self) -> None:
        with (
            mock.patch.object(server.platform, "system", return_value="Plan9"),
            mock.patch.object(server.platform, "machine", return_value="mips"),
            self.assertRaisesRegex(RuntimeError, "not available"),
        ):
            server._release_asset()


class ManagedInstallTests(unittest.TestCase):
    def _fixture_archive(
        self, root: Path, kind: str, executable: str, payload: bytes
    ) -> Path:
        archive = root / ("fixture.zip" if kind == "zip" else "fixture.tar.gz")
        member = f"release/{executable}"
        if kind == "zip":
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(member, payload)
            return archive
        with tarfile.open(archive, "w:gz") as bundle:
            info = tarfile.TarInfo(member)
            info.size = len(payload)
            info.mode = 0o755
            bundle.addfile(info, io.BytesIO(payload))
        return archive

    def test_downloads_verifies_caches_and_licenses_tar_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture_archive(root, "tar.gz", "tgrep", b"binary")
            archive_digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
            plugin_data = root / "plugin-data"

            def download(_url: str, destination: Path) -> None:
                shutil.copyfile(fixture, destination)

            with (
                mock.patch.object(
                    server,
                    "_release_asset",
                    return_value=("test-target", "tar.gz", "tgrep", archive_digest),
                ),
                mock.patch.object(server, "_plugin_data_dir", return_value=plugin_data),
                mock.patch.object(
                    server, "_download_file", side_effect=download
                ) as fetch,
            ):
                installed = Path(server._install_tgrep())
                cached = Path(server._install_tgrep())

            self.assertEqual(installed, cached)
            self.assertEqual(installed.read_bytes(), b"binary")
            if os.name != "nt":
                self.assertTrue(installed.stat().st_mode & 0o100)
            self.assertEqual(fetch.call_count, 1)
            installed_license = installed.parent / "LICENSE.microsoft-tgrep.txt"
            self.assertIn("Microsoft Corporation", installed_license.read_text())
            self.assertEqual(
                (installed.parent / "tgrep.sha256").read_text().strip(),
                hashlib.sha256(b"binary").hexdigest(),
            )

    def test_downloads_and_extracts_windows_zip_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = self._fixture_archive(root, "zip", "tgrep.exe", b"windows")
            archive_digest = hashlib.sha256(fixture.read_bytes()).hexdigest()

            def download(_url: str, destination: Path) -> None:
                shutil.copyfile(fixture, destination)

            with (
                mock.patch.object(
                    server,
                    "_release_asset",
                    return_value=(
                        "windows-target",
                        "zip",
                        "tgrep.exe",
                        archive_digest,
                    ),
                ),
                mock.patch.object(
                    server, "_plugin_data_dir", return_value=root / "data"
                ),
                mock.patch.object(server, "_download_file", side_effect=download),
            ):
                installed = Path(server._install_tgrep())

            self.assertEqual(installed.name, "tgrep.exe")
            self.assertEqual(installed.read_bytes(), b"windows")

    def test_rejects_archive_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def download(_url: str, destination: Path) -> None:
                destination.write_bytes(b"wrong archive")

            with (
                mock.patch.object(
                    server,
                    "_release_asset",
                    return_value=("test-target", "tar.gz", "tgrep", "0" * 64),
                ),
                mock.patch.object(server, "_plugin_data_dir", return_value=root),
                mock.patch.object(server, "_download_file", side_effect=download),
                self.assertRaisesRegex(RuntimeError, "checksum verification failed"),
            ):
                server._install_tgrep()

    def test_explicit_override_skips_managed_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "tgrep"
            binary.write_bytes(b"test")
            with (
                mock.patch.dict(os.environ, {"TGREP_BIN": str(binary)}, clear=True),
                mock.patch.object(server, "_install_tgrep") as install,
            ):
                self.assertEqual(server._find_tgrep(), str(binary))
                install.assert_not_called()

    @unittest.skipUnless(
        os.environ.get("TGREP_LIVE_TEST") == "1",
        "set TGREP_LIVE_TEST=1 to download and execute the official release",
    )
    def test_live_managed_download_and_search(self) -> None:
        fixture = REPOSITORY_ROOT / "tests/fixtures/live-repository"
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(
                os.environ,
                {
                    "PLUGIN_DATA": directory,
                    "TGREP_AUTO_INSTALL": "1",
                    "TGREP_WORKSPACE_ROOT": str(fixture),
                },
                clear=False,
            ),
        ):
            result = server._run_search(
                {
                    "pattern": "tgrep-live-acceptance",
                    "workspace_root": str(fixture),
                    "path": ".",
                    "fixed_strings": True,
                    "fresh": True,
                    "files_with_matches": True,
                }
            )
        self.assertNotIn("isError", result, result)
        output = result["content"][0]["text"]
        self.assertIn("app.py", output)
        self.assertIn("README.md", output)


class PathAndCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "src").mkdir()
        (self.root / "src/main.rs").write_text("fn main() {}\n", encoding="utf-8")
        self.environment = mock.patch.dict(
            os.environ, {"TGREP_WORKSPACE_ROOT": str(self.root)}, clear=True
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_path_must_stay_inside_workspace(self) -> None:
        with self.assertRaisesRegex(ValueError, "workspace root"):
            server._resolve_workspace_path("../outside", workspace_root=str(self.root))

    def test_search_builds_allowlisted_command(self) -> None:
        with (
            mock.patch.object(server, "_find_tgrep", return_value="/bin/tgrep"),
            mock.patch.object(
                server, "_run_process", return_value={"content": []}
            ) as run,
        ):
            result = server._run_search(
                {
                    "pattern": "main",
                    "workspace_root": str(self.root),
                    "path": "src",
                    "fixed_strings": True,
                    "smart_case": True,
                    "glob": ["*.rs"],
                    "file_type": ["rust"],
                    "context": 2,
                    "max_count": 10,
                    "fresh": True,
                }
            )
        self.assertEqual(result, {"content": []})
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/bin/tgrep")
        self.assertEqual(command[-3:], ["--", "main", str(self.root / "src")])
        for expected in ("-F", "-S", "-g", "*.rs", "-t", "rust", "-C", "2"):
            self.assertIn(expected, command)
        self.assertIn("--no-index", command)

    def test_invalid_search_stops_before_install(self) -> None:
        cases = [
            {},
            {"pattern": "x", "workspace_root": str(self.root), "unknown": True},
            {
                "pattern": "x",
                "workspace_root": str(self.root),
                "ignore_case": True,
                "smart_case": True,
            },
            {
                "pattern": "x",
                "workspace_root": str(self.root),
                "files_with_matches": True,
                "count": True,
            },
            {"pattern": "x", "workspace_root": str(self.root), "context": 101},
            {"pattern": "x", "workspace_root": str(self.root), "glob": []},
        ]
        for arguments in cases:
            with (
                self.subTest(arguments=arguments),
                mock.patch.object(server, "_find_tgrep") as find,
            ):
                result = server._run_search(arguments)
                self.assertTrue(result["isError"])
                find.assert_not_called()

    def test_index_builds_command_and_rejects_bad_size(self) -> None:
        with (
            mock.patch.object(server, "_find_tgrep", return_value="/bin/tgrep"),
            mock.patch.object(
                server, "_run_process", return_value={"content": []}
            ) as run,
        ):
            server._run_index(
                {
                    "workspace_root": str(self.root),
                    "path": ".",
                    "exclude": ["vendor", "generated"],
                    "no_require_git": True,
                    "max_filesize": "8M",
                    "threads": 4,
                }
            )
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["/bin/tgrep", "index", str(self.root)])
        self.assertEqual(command.count("--exclude"), 2)
        self.assertIn("--no-require-git", command)
        self.assertEqual(run.call_args.kwargs["allowed_exit_codes"], frozenset({0}))

        with mock.patch.object(server, "_find_tgrep") as find:
            result = server._run_index(
                {
                    "workspace_root": str(self.root),
                    "path": ".",
                    "max_filesize": "eight",
                }
            )
            self.assertTrue(result["isError"])
            find.assert_not_called()

    def test_search_exit_one_is_not_error_but_index_exit_one_is(self) -> None:
        no_match = subprocess.CompletedProcess([], 1, "", "")
        search = server._text_result(no_match, max_output_chars=1000)
        self.assertNotIn("isError", search)
        with (
            mock.patch.object(server.subprocess, "run", return_value=no_match),
            mock.patch.object(server, "_workspace_root", return_value=self.root),
        ):
            index = server._run_process(
                ["tgrep", "index", "."],
                cwd=self.root,
                timeout=1,
                max_output_chars=1000,
                allowed_exit_codes=frozenset({0}),
            )
        self.assertTrue(index["isError"])

    def test_process_capture_is_bounded(self) -> None:
        result = server._run_process(
            [sys.executable, "-c", "print('x' * 2000000)"],
            cwd=self.root,
            timeout=10,
            max_output_chars=1000,
            allowed_exit_codes=frozenset({0}),
        )
        text = result["content"][0]["text"]
        self.assertLessEqual(len(text), 1000)
        self.assertIn("truncated", text)


class McpProtocolTests(unittest.TestCase):
    def tearDown(self) -> None:
        server._CLIENT_ROOTS.clear()
        vars(server)["_CLIENT_SUPPORTS_ROOTS"] = False

    def test_negotiates_and_uses_client_workspace_roots(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
            tempfile.TemporaryDirectory() as outside_directory,
        ):
            first_root = Path(first_directory).resolve()
            second_root = Path(second_directory).resolve()
            outside_root = Path(outside_directory).resolve()
            initialize = server._handle(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"capabilities": {"roots": {"listChanged": True}}},
                }
            )
            self.assertEqual(initialize["result"]["serverInfo"]["name"], "tgrep")
            with mock.patch.object(server, "_send") as send:
                server._handle(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    }
                )
            request = send.call_args.args[0]
            self.assertEqual(request["method"], "roots/list")
            server._handle(
                {
                    "jsonrpc": "2.0",
                    "id": server._ROOTS_REQUEST_ID,
                    "result": {
                        "roots": [
                            {"uri": first_root.as_uri(), "name": "first"},
                            {"uri": second_root.as_uri(), "name": "second"},
                            {"uri": "https://example.test/not-local"},
                        ]
                    },
                }
            )
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(Path, "cwd", return_value=REPOSITORY_ROOT),
            ):
                self.assertEqual(server._workspace_root(), first_root)
                self.assertEqual(server._workspace_root(str(second_root)), second_root)
                self.assertEqual(
                    server._resolve_workspace_path(
                        ".", workspace_root=str(second_root), directory=True
                    ),
                    second_root,
                )
                with self.assertRaisesRegex(ValueError, "client root"):
                    server._workspace_root(str(outside_root))

    def test_fails_closed_without_a_host_established_root(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            server._CLIENT_ROOTS.clear()
            for handler, arguments in (
                (
                    server._run_search,
                    {"pattern": "x", "workspace_root": directory},
                ),
                (server._run_index, {"workspace_root": directory}),
                (server._run_status, {"workspace_root": directory}),
            ):
                with (
                    self.subTest(handler=handler.__name__),
                    mock.patch.object(server, "_find_tgrep") as find,
                ):
                    result = handler(arguments)
                    self.assertTrue(result["isError"])
                    self.assertIn(
                        "no trusted workspace root",
                        result["content"][0]["text"],
                    )
                    find.assert_not_called()

    def test_initialize_without_roots_does_not_request_them(self) -> None:
        server._handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"capabilities": {}},
            }
        )
        with mock.patch.object(server, "_send") as send:
            server._handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send.assert_not_called()

    def test_rejects_non_object_params(self) -> None:
        response = server._handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": []}
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_lists_three_tools_and_rejects_unknown_tool(self) -> None:
        listed = server._handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(
            [tool["name"] for tool in listed["result"]["tools"]],
            ["tgrep_search", "tgrep_index", "tgrep_status"],
        )
        unknown = server._handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "shell", "arguments": {}},
            }
        )
        self.assertEqual(unknown["error"]["code"], -32601)

    def test_stdio_handshake(self) -> None:
        mcp_config = json.loads(
            (REPOSITORY_ROOT / "plugins/tgrep/mcp.json").read_text(encoding="utf-8")
        )
        launcher = mcp_config["mcpServers"]["tgrep"]
        command = launcher["command"]
        arguments = [
            argument.replace("${PLUGIN_ROOT}", str(REPOSITORY_ROOT / "plugins/tgrep"))
            for argument in launcher["args"]
        ]
        requests = "\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05"},
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                "",
            ]
        )
        completed = subprocess.run(
            [command, *arguments],
            input=requests,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "tgrep")
        self.assertEqual(len(responses[1]["result"]["tools"]), 3)
        self.assertEqual(completed.stderr, "")


class PackagingTests(unittest.TestCase):
    def test_versions_marketplaces_and_attribution_are_consistent(self) -> None:
        expected = server.SERVER_VERSION
        manifests = [
            REPOSITORY_ROOT / "plugins/tgrep/plugin.json",
            REPOSITORY_ROOT / "plugins/tgrep/.codex-plugin/plugin.json",
        ]
        for manifest in manifests:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["name"], "tgrep", manifest)
            self.assertEqual(payload["version"], expected, manifest)
            self.assertEqual(payload["license"], "MIT", manifest)
            self.assertEqual(payload["author"]["name"], "MiguelElGallo", manifest)

        codex_marketplace = json.loads(
            (REPOSITORY_ROOT / ".agents/plugins/marketplace.json").read_text()
        )
        vscode_marketplace = json.loads(
            (REPOSITORY_ROOT / ".github/plugin/marketplace.json").read_text()
        )
        self.assertEqual(codex_marketplace["name"], "tgrep")
        self.assertEqual(
            codex_marketplace["plugins"][0]["source"]["path"], "./plugins/tgrep"
        )
        self.assertEqual(vscode_marketplace["metadata"]["version"], expected)
        self.assertEqual(
            vscode_marketplace["plugins"][0]["source"],
            "./plugins/tgrep",
        )
        self.assertEqual(vscode_marketplace["plugins"][0]["version"], expected)

        self.assertFalse(
            (REPOSITORY_ROOT / "plugins/tgrep-vscode/plugin.json").exists()
        )

    def test_documentation_links_and_release_media_exist(self) -> None:
        expected_paths = (
            "docs/usage.md",
            "docs/configuration.md",
            "docs/development.md",
            "docs/licensing.md",
            (
                "marketing/linkedin-tgrep-videos/output/"
                "tgrep-vscode-linkedin-thumbnail.png"
            ),
            (
                "marketing/linkedin-tgrep-videos/output/"
                "tgrep-vscode-linkedin-1080x1350.mp4"
            ),
            (
                "marketing/linkedin-tgrep-videos/output/"
                "tgrep-codex-linkedin-thumbnail.png"
            ),
            (
                "marketing/linkedin-tgrep-videos/output/"
                "tgrep-codex-linkedin-1080x1350.mp4"
            ),
            "plugins/tgrep/third_party/tgrep-LICENSE.txt",
        )
        for relative in expected_paths:
            with self.subTest(path=relative):
                self.assertTrue((REPOSITORY_ROOT / relative).is_file(), relative)

        notices = (REPOSITORY_ROOT / "THIRD_PARTY_NOTICES.md").read_text()
        self.assertIn("https://github.com/microsoft/tgrep", notices)
        self.assertIn("Copyright (c) Microsoft Corporation", notices)
        self.assertIn(server.TGREP_VERSION, notices)

    def test_portable_manifest_is_closed_and_uses_canonical_schema(self) -> None:
        manifest = json.loads(
            (REPOSITORY_ROOT / "plugins/tgrep/plugin.json").read_text()
        )
        allowed = {
            "$schema",
            "name",
            "version",
            "description",
            "author",
            "homepage",
            "repository",
            "license",
            "keywords",
            "extensions",
        }
        self.assertLessEqual(set(manifest), allowed)
        self.assertEqual(
            manifest["$schema"],
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        )
        mcp = json.loads((REPOSITORY_ROOT / "plugins/tgrep/mcp.json").read_text())
        self.assertEqual(
            mcp["$schema"],
            "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        )


if __name__ == "__main__":
    unittest.main()
