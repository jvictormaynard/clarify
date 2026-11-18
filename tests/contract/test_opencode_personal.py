"""Personal inference cannot borrow account authority or run provider tools."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from opencode_acp import TextSession
from opencode_provider import OpenCodeAdapter, _private_directory
from provider_http import (
    CancellationToken,
    ProviderCancelledError,
    ProviderTimeoutError,
)
from provider_types import (
    ProviderConnection,
    ProviderConfigurationError,
    ProviderResponseError,
    RewriteRequest,
)
from repositories import AppConfig


class OpenCodePersonalTests(unittest.TestCase):
    def test_windows_cleanup_retries_late_file_release_and_preserves_cancellation(self):
        windows = Mock(wraps=os)
        windows.name = "nt"
        directory = Mock(name="private_directory")
        directory.cleanup.side_effect = [PermissionError("locked DLL"), None]
        with (
            patch("opencode_provider.os", windows),
            patch(
                "opencode_provider.tempfile.TemporaryDirectory", return_value=directory
            ),
            patch("opencode_provider.time.sleep"),
        ):
            with self.assertRaises(ProviderCancelledError):
                with _private_directory():
                    raise ProviderCancelledError()
        self.assertEqual(directory.cleanup.call_count, 2)

    def setUp(self):
        self.adapter = OpenCodeAdapter()
        self.connection = ProviderConnection("", "")
        self.request = RewriteRequest(
            "Hello", "opencode/example-free", "en", "Rewrite", "Hello"
        )
        self.free_catalog = json.dumps(
            {
                "data": [
                    {
                        "id": "example-free",
                        "providerID": "opencode",
                        "type": "chat",
                        "enabled": True,
                        "cost": [{"input": 0, "output": 0}],
                    }
                ]
            }
        )

    def test_discovery_excludes_paid_and_unrelated_models_and_roundtrips_config(self):
        with patch.object(
            self.adapter,
            "_run",
            return_value="opencode/example-free\nopencode/paid\nother/free\nopencode/big-pickle\n",
        ):
            self.assertEqual(
                self.adapter.discover_models(self.connection).text_models,
                (),  # A name alone does not establish zero provider pricing.
            )
        values = AppConfig().to_mapping()
        values["opencode_text_model"] = self.request.model
        self.assertEqual(
            AppConfig.from_mapping(values).opencode.text_model, self.request.model
        )

    def test_verbose_catalog_exposes_names_and_rejects_priced_free_suffix(self):
        output = json.dumps(
            {
                "data": [
                    {
                        "id": "example-free",
                        "providerID": "opencode",
                        "name": "Example Free",
                        "type": "chat",
                        "enabled": True,
                        "cost": [{"input": 0, "output": 0}],
                    },
                    {
                        "id": "priced-free",
                        "providerID": "opencode",
                        "type": "chat",
                        "enabled": True,
                        "cost": [{"input": 1, "output": 2}],
                    },
                    {
                        "id": "unknown-free",
                        "providerID": "opencode",
                        "type": "chat",
                        "enabled": True,
                    },
                ]
            }
        )
        with patch.object(self.adapter, "_run", return_value=output):
            catalog = self.adapter.discover_models(self.connection)
        self.assertEqual(catalog.text_models, ("opencode/example-free",))
        self.assertEqual(
            catalog.display_names, {"opencode/example-free": "Example Free"}
        )

    def test_empty_catalog_and_missing_cli_are_explicit_errors(self):
        with patch.object(self.adapter, "_run", return_value=""):
            with self.assertRaises(ProviderConfigurationError):
                self.adapter.validate(self.connection)
        with patch("opencode_runtime.executable", return_value=None):
            with self.assertRaises(ProviderConfigurationError):
                self.adapter.discover_models(self.connection)

    def test_generation_requires_selected_model_completion_and_no_tools(self):
        with (
            patch("opencode_provider._runtime_identity", return_value=("fixture",)),
            patch.object(
                self.adapter, "_run", side_effect=[self.free_catalog, "Hello."]
            ) as run,
        ):
            self.assertEqual(
                self.adapter.rewrite(self.request, self.connection).text, "Hello."
            )
        self.assertEqual(run.call_args.args[0], ["acp"])
        self.assertEqual(run.call_args.kwargs["model"], self.request.model)
        with (
            patch(
                "opencode_provider._runtime_identity", return_value=("other-runtime",)
            ),
            patch.object(
                self.adapter, "_run", return_value="opencode/different-free"
            ) as run,
        ):
            with self.assertRaises(ProviderConfigurationError):
                self.adapter.rewrite(self.request, self.connection)
            self.assertEqual(run.call_count, 1)

    def test_rewrite_reuses_only_recent_free_catalog_for_the_same_runtime(self):
        catalog = self.free_catalog
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "opencode"
            executable.write_bytes(b"version one")
            adapter = OpenCodeAdapter(executable=executable)
            clock = Mock(return_value=100)
            phases = []
            catalog_output = catalog
            refusal = None

            def run(args, *rest, **options):
                phases.append(args[0])
                if args[0] == "api":
                    return catalog_output
                with options["authorize_prompt"]():
                    if refusal is not None:
                        raise refusal
                    return "Hello."

            with (
                patch.object(adapter, "_run", side_effect=run),
                patch("opencode_provider.time.monotonic", clock),
            ):
                # Connecting or opening the explicit picker refreshes the catalog.
                adapter.validate(self.connection)
                for _ in range(2):
                    adapter.rewrite(self.request, self.connection)
                self.assertEqual(phases, ["api", "acp", "acp"])

                clock.return_value += 120
                adapter.rewrite(self.request, self.connection)
                self.assertEqual(phases[-2:], ["api", "acp"])

                executable.write_bytes(b"replacement runtime on disk")
                adapter.rewrite(self.request, self.connection)
                self.assertEqual(phases[-2:], ["api", "acp"])

                refusal = ProviderResponseError("opencode", "Model unavailable")
                prior_calls = len(phases)
                with self.assertRaises(ProviderResponseError):
                    adapter.rewrite(self.request, self.connection)
                self.assertEqual(phases[prior_calls:], ["acp"])

                catalog_output = catalog.replace('"output": 0', '"output": 1')
                with self.assertRaises(ProviderConfigurationError):
                    adapter.rewrite(self.request, self.connection)
                self.assertEqual(phases[-1], "api")

                catalog_output = catalog
                adapter.validate(self.connection)
                approvals = []
                repriced = catalog.replace('"output": 0', '"output": 1')

                def rewrite_then_reprice(args, *rest, **options):
                    if args[0] == "api":
                        return repriced
                    adapter.discover_models(self.connection)
                    with options["authorize_prompt"]():
                        approvals.append("prompt sent")
                    return "Hello."

                adapter._run.side_effect = rewrite_then_reprice
                with self.assertRaises(ProviderConfigurationError):
                    adapter.rewrite(self.request, self.connection)
                self.assertEqual(approvals, [])

                overlap = False

                def superseded_lookup(args, *rest, **options):
                    nonlocal overlap
                    if args[0] == "acp":
                        self.fail("A superseded catalog must not authorize ACP")
                    if overlap:
                        return repriced
                    overlap = True
                    adapter.discover_models(self.connection)
                    return catalog

                adapter._run.side_effect = superseded_lookup
                with self.assertRaises(ProviderConfigurationError):
                    adapter.rewrite(self.request, self.connection)
                self.assertTrue(overlap)

    def test_pending_refresh_preserves_recent_completed_check(self):
        ready = threading.Event()
        release = threading.Event()

        def run(args, *rest, **options):
            if args[0] == "api":
                ready.set()
                self.assertTrue(release.wait(timeout=3))
                return self.free_catalog
            with options["authorize_prompt"]():
                return "Hello."

        adapter = self.adapter
        with (
            patch("opencode_provider._runtime_identity", return_value=("fixture",)),
            patch.object(adapter, "_run", return_value=self.free_catalog) as fake,
            ThreadPoolExecutor(max_workers=1) as worker,
        ):
            adapter.discover_models(self.connection)
            fake.side_effect = run
            refreshing = worker.submit(adapter.discover_models, self.connection)
            try:
                self.assertTrue(ready.wait(timeout=3))
                self.assertEqual(
                    adapter.rewrite(self.request, self.connection).text, "Hello."
                )
            finally:
                release.set()
            self.assertEqual(
                refreshing.result(timeout=3).text_models, (self.request.model,)
            )

    def test_supported_version_probe_is_reused_until_binary_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "opencode"
            executable.write_bytes(b"version two")
            adapter = OpenCodeAdapter(executable=executable)
            process = Mock(pid=12345, returncode=0)
            process.poll.return_value = 0
            with (
                patch(
                    "opencode_provider.subprocess.Popen", return_value=process
                ) as launch,
                patch("opencode_provider.os.killpg", create=True),
                patch("opencode_provider._windows_job", return_value=Mock()),
                patch(
                    "opencode_provider.subprocess.run",
                    return_value=Mock(stdout=b"opencode v2.3.0", returncode=0),
                ) as version,
            ):
                adapter.discover_models(self.connection)
                adapter.discover_models(self.connection)
                version.assert_called_once()
                self.assertEqual(launch.call_count, 2)
                executable.write_bytes(b"unsupported replacement")
                version.return_value.stdout = b"opencode v1.19.5"
                with self.assertRaises(ProviderConfigurationError):
                    adapter.discover_models(self.connection)
                self.assertEqual(version.call_count, 2)
                self.assertEqual(launch.call_count, 2)

    def test_cancel_terminates_private_process_and_never_inherits_credentials(self):
        token = CancellationToken()
        token.cancel()
        process = Mock(pid=12345, returncode=None)
        process.poll.return_value = None
        with (
            patch.dict(
                "os.environ",
                {
                    "OPENAI_API_KEY": "forbidden",
                    "OPENCODE_CONFIG_CONTENT": "forbidden",
                    "SYSTEMROOT": "windows-runtime-root",
                },
            ),
            patch("opencode_provider.subprocess.Popen", return_value=process) as launch,
            patch("opencode_provider.os.killpg", create=True) as kill,
            patch("opencode_provider._windows_job", return_value=Mock()) as isolate,
            patch(
                "opencode_provider.subprocess.run",
                return_value=Mock(stdout=b"2.0.0", returncode=0),
            ),
        ):
            adapter = OpenCodeAdapter(executable="/fake/opencode")
            with self.assertRaises(ProviderCancelledError):
                adapter._run(["models"], cancel_token=token)
            kwargs = launch.call_args.kwargs
            self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
            self.assertEqual(kwargs["env"]["SYSTEMROOT"], "windows-runtime-root")
            config = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
            self.assertEqual(
                config["permissions"],
                [{"action": "*", "resource": "*", "effect": "deny"}],
            )
            self.assertIn("--standalone", launch.call_args.args[0])
            (isolate.return_value if os.name == "nt" else kill).assert_called_once()
            process.wait.assert_called_once()

    def test_catalog_failure_does_not_claim_a_free_generation_was_refused(self):
        process = Mock(pid=12345, returncode=1)
        process.poll.return_value = 1
        with (
            patch(
                "opencode_provider.subprocess.run",
                return_value=Mock(stdout=b"opencode v2.3.0", returncode=0),
            ),
            patch("opencode_provider.subprocess.Popen", return_value=process),
            patch("opencode_provider.os.killpg", create=True),
            patch("opencode_provider._windows_job", return_value=Mock()),
        ):
            with self.assertRaisesRegex(
                ProviderConfigurationError, "Could not load OpenCode"
            ):
                OpenCodeAdapter(executable="/fake/opencode").discover_models(
                    self.connection
                )

    def test_v1_is_rejected_before_catalog_or_generation(self):
        with (
            patch(
                "opencode_provider.subprocess.run",
                return_value=Mock(stdout=b"1.19.5", returncode=0),
            ),
            patch("opencode_provider.subprocess.Popen") as launch,
        ):
            with self.assertRaises(ProviderConfigurationError):
                OpenCodeAdapter(executable="/fake/opencode")._run(["models"])
        launch.assert_not_called()

    def test_windows_version_and_catalog_run_without_visible_console(self):
        windows = Mock(wraps=os)
        windows.name = "nt"
        windows.environ = dict(os.environ)
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with (
            patch("opencode_provider.os", windows),
            patch(
                "opencode_provider.subprocess.CREATE_NO_WINDOW", 0x08000000, create=True
            ),
            patch(
                "opencode_provider.subprocess.CREATE_NEW_PROCESS_GROUP",
                0x00000200,
                create=True,
            ),
            patch(
                "opencode_provider.subprocess.run",
                return_value=Mock(stdout=b"opencode v2.3.0", returncode=0),
            ) as version,
            patch("opencode_provider.subprocess.Popen", return_value=process) as launch,
            patch("opencode_provider._windows_job", return_value=Mock()) as isolate,
        ):
            OpenCodeAdapter(executable="/fake/opencode")._run(["models"])
        self.assertTrue(version.call_args.kwargs.get("creationflags", 0) & 0x08000000)
        self.assertTrue(launch.call_args.kwargs["creationflags"] & 0x08000000)
        self.assertTrue(launch.call_args.kwargs["creationflags"] & 0x00000004)
        isolate.assert_called_once_with(process)
        isolate.return_value.assert_called_once()

    def acp_peer(self, scenario="success", *, token=None, timeout=2):
        """Run the production transport against a bounded fake ACP process."""
        peer = r"""import json, sys, time
scenario = sys.argv[1]
record = open(sys.argv[2], "w", encoding="utf-8")
def send(message):
    print(json.dumps({"jsonrpc": "2.0", **message}), flush=True)
for line in sys.stdin:
    message = json.loads(line)
    record.write(json.dumps(message) + "\n"); record.flush()
    method = message.get("method")
    identity = message.get("id")
    if method == "initialize":
        send({"id": identity, "result": {"protocolVersion": 1}})
    elif method == "session/new":
        send({"id": identity, "result": {"sessionId": "private-session"}})
    elif method == "session/set_mode":
        send({"id": identity, "result": {}})
    elif method == "session/set_config_option":
        model = "opencode/other-free" if scenario == "wrong-model" else message["params"]["value"]
        options = [{"name": "Test model", "value": "opencode/other-free" if scenario == "unlisted-model" else model}]
        if scenario == "grouped-models":
            options = [{"group": "free", "name": "Free models", "options": options}]
        send({"id": identity, "result": {"configOptions": [{"id": "model", "currentValue": model, "options": options}]}})
    elif method == "session/prompt":
        if scenario == "timeout":
            time.sleep(30)
        if scenario == "eof":
            sys.exit(0)
        if scenario == "output":
            print("x" * (4 * 1024 * 1024 + 1), flush=True)
            continue
        if scenario == "stderr":
            sys.stderr.write("x" * (1024 * 1024 + 1)); sys.stderr.flush()
            continue
        if scenario == "permission":
            for request_id, operation in enumerate([
                "session/request_permission", "session/request_permission",
                "fs/read_text_file", "fs/write_text_file", "terminal/create",
            ], 100):
                send({"id": request_id, "method": operation, "params": {"sessionId": "foreign", "path": sys.argv[2] + ".forbidden"}})
            # Wait for every cancellation/unsupported reply before completing.
            for _ in range(5):
                reply = json.loads(sys.stdin.readline())
                record.write(json.dumps(reply) + "\n"); record.flush()
        if scenario == "error":
            send({"method": "session/update", "params": {"sessionId": "private-session", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Must not publish"}}}})
            send({"id": identity, "error": {"code": -32603, "message": "private-input secret-key", "data": {"errorName": "provider.free-limit"}}})
            continue
        send({"method": "session/update", "params": {"sessionId": "private-session", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "OK"}}}})
        if scenario == "tool":
            send({"method": "session/update", "params": {"sessionId": "private-session", "update": {"sessionUpdate": "tool_call_update", "status": "completed"}}})
        if scenario == "incomplete":
            sys.exit(0)
        send({"id": identity, "result": {"stopReason": "cancelled" if scenario == "stopped" else "end_turn"}})
"""
        real_popen = subprocess.Popen
        with tempfile.TemporaryDirectory(prefix="clarify-acp-test-") as directory:
            record = Path(directory) / "messages"
            launched = []

            def launch(args, **kwargs):
                self.assertEqual(args[1:], ["acp", "--log-level", "error"])
                self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
                config = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
                self.assertEqual(
                    config["permission"], {"*": "deny", "bash": "ask", "read": "ask"}
                )
                self.assertFalse(
                    any(p["action"] == "tool.use" for p in config["policies"])
                )
                self.assertEqual(
                    config["agents"]["clarify"]["permissions"],
                    [
                        {"action": "*", "resource": "*", "effect": "deny"},
                        {"action": "shell", "resource": "*", "effect": "ask"},
                        {"action": "read", "resource": "*", "effect": "ask"},
                    ],
                )
                child = real_popen(
                    [sys.executable, "-u", "-c", peer, scenario, str(record)], **kwargs
                )
                launched.append((child, Path(kwargs["cwd"]).parent))
                return child

            try:
                with (
                    patch(
                        "opencode_provider.subprocess.run",
                        return_value=Mock(stdout=b"2.3.0", returncode=0),
                    ),
                    patch("opencode_provider.subprocess.Popen", side_effect=launch),
                ):
                    text = OpenCodeAdapter(executable="fake", timeout=timeout)._run(
                        ["acp"],
                        "Public test",
                        token,
                        model="opencode/example-free",
                    )
                messages = [
                    json.loads(line) for line in record.read_text().splitlines()
                ]
                self.assertFalse(Path(str(record) + ".forbidden").exists())
                return text, messages
            finally:
                for child, root in launched:
                    self.assertIsNotNone(child.poll())
                    self.assertFalse(root.exists())
                self.assertFalse(
                    any(t.name == "clarify-acp-writer" for t in threading.enumerate())
                )

    def test_acp_pins_model_and_accepts_only_completed_text(self):
        text, messages = self.acp_peer()
        self.assertEqual(text, "OK")
        calls = [message for message in messages if "method" in message]
        self.assertEqual(
            [m["method"] for m in calls],
            [
                "initialize",
                "session/new",
                "session/set_mode",
                "session/set_config_option",
                "session/prompt",
            ],
        )
        self.assertEqual(calls[0]["params"]["clientCapabilities"], {})
        self.assertEqual(calls[1]["params"]["mcpServers"], [])
        self.assertEqual(calls[2]["params"]["modeId"], "clarify")
        self.assertEqual(
            calls[3]["params"],
            {
                "sessionId": "private-session",
                "configId": "model",
                "value": "opencode/example-free",
            },
        )
        self.assertEqual(self.acp_peer("grouped-models")[0], "OK")
        for scenario in (
            "stopped",
            "incomplete",
            "tool",
            "wrong-model",
            "unlisted-model",
        ):
            with (
                self.subTest(scenario=scenario),
                self.assertRaises(ProviderResponseError),
            ):
                self.acp_peer(scenario)

    def test_acp_cancels_every_permission_and_rejects_client_operations(self):
        text, messages = self.acp_peer("permission")
        self.assertEqual(text, "OK")
        replies = [m for m in messages if m.get("id", 0) >= 100]
        self.assertEqual(
            [r["result"] for r in replies[:2]],
            [
                {"outcome": {"outcome": "cancelled"}},
                {"outcome": {"outcome": "cancelled"}},
            ],
        )
        self.assertEqual([r["error"]["code"] for r in replies[2:]], [-32601] * 3)

    def test_acp_service_error_never_returns_text_or_diagnostics(self):
        with self.assertRaises(ProviderResponseError) as error:
            self.acp_peer("error")
        self.assertIn("free usage limit", str(error.exception))
        self.assertNotIn("private-input", str(error.exception))
        self.assertNotIn("secret-key", str(error.exception))

    def test_acp_cancel_timeout_eof_and_output_bounds_stop_owned_resources(self):
        token = CancellationToken()
        token.cancel()
        with self.assertRaises(ProviderCancelledError):
            self.acp_peer(token=token)
        original_send = TextSession._send

        def cancel_in_flight(client, message, authorization=None):
            original_send(client, message, authorization)
            if message.get("method") == "session/prompt":
                active_token.cancel()

        active_token = CancellationToken()
        with (
            patch.object(TextSession, "_send", cancel_in_flight),
            self.assertRaises(ProviderCancelledError),
        ):
            self.acp_peer("timeout", token=active_token)
        with self.assertRaises(ProviderTimeoutError):
            self.acp_peer("timeout", timeout=0.15)
        for scenario in ("eof", "output", "stderr"):
            with (
                self.subTest(scenario=scenario),
                self.assertRaises(ProviderResponseError),
            ):
                self.acp_peer(scenario)


class ManagedRuntimeTests(unittest.TestCase):
    def test_reuses_verified_windows_install_outside_scoped_runtime_without_download(
        self,
    ):
        import hashlib
        from pathlib import Path
        import tempfile
        import opencode_runtime as runtime

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            home = base / "user"
            scoped_local = base / "isolated-local"
            external = home / "AppData/Local/Programs/OpenCode/bin/opencode.exe"
            external.parent.mkdir(parents=True)
            external.write_bytes(b"verified binary")
            digest = hashlib.sha256(external.read_bytes()).hexdigest()
            with (
                patch.object(runtime.sys, "platform", "win32"),
                patch.object(runtime, "supported", return_value=True),
                patch.object(
                    runtime, "runtime_root", return_value=scoped_local / "runtime"
                ),
                patch.object(runtime.Path, "home", return_value=home),
                patch.dict(os.environ, {"LOCALAPPDATA": str(scoped_local), "PATH": ""}),
                patch.object(runtime, "_WINDOWS_INSTALL_SHA256", digest),
                patch.object(runtime.urllib.request, "urlopen") as download,
            ):
                self.assertTrue(OpenCodeAdapter().available())
                self.assertIsNone(runtime.executable())
                external.write_bytes(b"unverified binary")
                self.assertFalse(OpenCodeAdapter().available())
                with patch.object(
                    runtime, "_verified_windows_install", return_value=external
                ):
                    with self.assertRaisesRegex(
                        ProviderConfigurationError, "Could not reuse"
                    ):
                        runtime.install()
                self.assertIsNone(runtime.executable())
                external.write_bytes(b"verified binary")
                adopted = scoped_local / "2.3.2" / "opencode.exe"
                self.assertEqual(runtime.install(), str(adopted))
                self.assertEqual(adopted.read_bytes(), b"verified binary")
                external.unlink()
                self.assertEqual(runtime.executable(), str(adopted))
                download.assert_not_called()

    def test_install_verifies_archive_before_publishing_and_retains_notice(self):
        import base64
        import hashlib
        import io
        from pathlib import Path
        import tarfile
        import tempfile
        import opencode_runtime as runtime

        archive = io.BytesIO()
        member = "package/bin/" + ("opencode.exe" if os.name == "nt" else "opencode")
        with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
            info = tarfile.TarInfo(member)
            info.size = 6
            bundle.addfile(info, io.BytesIO(b"binary"))
        data = archive.getvalue()
        spec = {
            "url": "https://registry.npmjs.org/example.tgz",
            "member": member,
            "integrity": "sha512-"
            + base64.b64encode(hashlib.sha512(data).digest()).decode(),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            with (
                patch.object(runtime, "runtime_root", return_value=root),
                patch.object(runtime, "supported", return_value=True),
                patch.dict(runtime.MANIFEST, {runtime.sys.platform: spec}),
            ):
                response = io.BytesIO(data)
                response.geturl = lambda: spec["url"]
                with patch.object(
                    runtime.urllib.request, "urlopen", return_value=response
                ):
                    installed = runtime.install()
                self.assertEqual(Path(installed).read_bytes(), b"binary")
                self.assertIn("MIT License", (root / "LICENSE.txt").read_text())
                Path(installed).unlink()
                response = io.BytesIO(b"corrupt")
                response.geturl = lambda: spec["url"]
                with patch.object(
                    runtime.urllib.request, "urlopen", return_value=response
                ):
                    with self.assertRaises(ProviderConfigurationError):
                        runtime.install()
                self.assertIsNone(runtime.executable())

    def test_free_refusal_terminates_without_echoing_diagnostics(self):
        adapter = OpenCodeAdapter(executable="/fake/opencode")
        process = Mock(pid=12345, returncode=None)
        process.poll.return_value = None

        def launch(*args, **kwargs):
            kwargs["stderr"].write(b"Free usage limit reached private-input secret-key")
            kwargs["stderr"].flush()
            return process

        with (
            patch(
                "opencode_provider.subprocess.run",
                return_value=Mock(stdout=b"opencode v2.3.0", returncode=0),
            ),
            patch("opencode_provider.subprocess.Popen", side_effect=launch),
            patch("opencode_provider.os.killpg", create=True) as kill,
            patch("opencode_provider._windows_job", return_value=Mock()) as isolate,
        ):
            with self.assertRaises(ProviderResponseError) as error:
                adapter._run(["run"])
            self.assertIn("free usage limit", str(error.exception))
            self.assertNotIn("private-input", str(error.exception))
            self.assertNotIn("secret-key", str(error.exception))
            (isolate.return_value if os.name == "nt" else kill).assert_called_once()
            process.wait.assert_called_once()
