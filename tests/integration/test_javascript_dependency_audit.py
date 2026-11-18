"""Exceptions cannot hide unrelated advisories, versions, errors or cycles."""

from copy import deepcopy
from datetime import datetime, timezone
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from scripts import javascript_dependency_audit as audit

from scripts.javascript_dependency_audit import evaluate

URL = "https://github.com/advisories/GHSA-fc5q-39xc-vjpf"
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


class JavaScriptAuditTests(unittest.TestCase):
    def setUp(self):
        self.report = {
            "auditReportVersion": 2,
            "vulnerabilities": {
                "picomatch": {
                    "severity": "high",
                    "nodes": ["node_modules/picomatch"],
                    "via": [{"url": URL, "severity": "high"}],
                },
                "tool": {"severity": "high", "via": ["picomatch", "cycle"]},
                "cycle": {"severity": "high", "via": ["tool"]},
            },
        }
        self.lock = {"packages": {"node_modules/picomatch": {"version": "4.0.7"}}}
        self.policy = {
            "policy_version": 1,
            "javascript_exceptions": {
                URL: {
                    "package": "picomatch",
                    "versions": {"desktop": ["4.0.7"]},
                    "expires_utc": "2026-12-01T00:00:00Z",
                    "rationale": "Reviewed",
                    "approved_by": "Maintainer",
                }
            },
        }

    def check(self, report=None, component="desktop", now=NOW):
        return evaluate(
            self.report if report is None else report,
            self.lock,
            self.policy,
            component,
            now,
        )

    def test_only_approved_advisory_and_its_cyclic_parents_are_allowed(self):
        self.assertEqual(self.check(), ([], [URL]))
        for name in ("picomatch", "cycle"):
            report = deepcopy(self.report)
            report["vulnerabilities"][name]["via"].append(
                {"url": "https://example.test/new", "severity": "critical"}
            )
            self.assertIn(name, self.check(report)[0])

    def test_scope_version_and_expiry_fail_closed(self):
        self.assertIn("picomatch", self.check(component="ci")[0])
        self.assertIn(
            "picomatch", self.check(now=datetime(2026, 12, 1, tzinfo=timezone.utc))[0]
        )
        for version in ("4.0.8", None):
            self.lock["packages"]["node_modules/picomatch"]["version"] = version
            self.assertIn("picomatch", self.check()[0])

    def test_malformed_missing_and_rootless_reports_fail_closed(self):
        for changes in (
            {"error": {}},
            {"auditReportVersion": 3},
            {"vulnerabilities": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.check({**self.report, **changes})
        self.report["vulnerabilities"].pop("picomatch")
        with self.assertRaises(ValueError):
            self.check()
        self.report["vulnerabilities"]["tool"]["via"] = ["cycle"]
        self.assertEqual(self.check()[0], ["cycle", "tool"])

    def test_moderates_remain_below_existing_gate(self):
        report = {
            "auditReportVersion": 2,
            "vulnerabilities": {
                "other": {
                    "severity": "moderate",
                    "via": [
                        {"url": "https://example.test/moderate", "severity": "moderate"}
                    ],
                }
            },
        }
        self.assertEqual(self.check(report), ([], []))

    def test_command_keeps_registry_errors_and_bad_reports_fatal(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "desktop").mkdir()
            npm = root / "npm.cmd"
            cli = root / "node_modules/npm/bin/npm-cli.js"
            cli.parent.mkdir(parents=True)
            cli.write_text("// fake CLI")
            (root / "desktop" / "package-lock.json").write_text(json.dumps(self.lock))
            (root / "dependency-audit.json").write_text(json.dumps(self.policy))
            cases = [
                (1, self.report, 0),
                (2, self.report, 2),
                (0, {}, 1),
                (1, {"auditReportVersion": 2, "vulnerabilities": {}}, 1),
            ]
            for status, report, expected in cases:
                with (
                    self.subTest(status=status, report=report),
                    patch.object(audit, "ROOT", root),
                    patch.object(audit.sys, "platform", "win32"),
                    patch.object(
                        audit.shutil,
                        "which",
                        side_effect=lambda name: (
                            str(npm) if name == "npm" else "node.exe"
                        ),
                    ),
                    patch.object(
                        audit.subprocess,
                        "run",
                        return_value=Mock(
                            returncode=status, stdout=json.dumps(report), stderr=""
                        ),
                    ) as process,
                    patch.object(
                        audit.sys, "argv", ["audit", "--component", "desktop"]
                    ),
                    patch.object(audit, "datetime", wraps=datetime) as clock,
                    patch("builtins.print"),
                ):
                    clock.now.return_value = NOW
                    self.assertEqual(audit.main(), expected)
                    self.assertEqual(
                        process.call_args.args[0][:2], ["node.exe", str(cli)]
                    )

    def test_windows_uses_node_cli_and_rejects_missing_cli(self):
        with TemporaryDirectory() as directory:
            npm = Path(directory) / "npm.cmd"
            cli = Path(directory) / "node_modules/npm/bin/npm-cli.js"
            with (
                patch.object(audit.sys, "platform", "win32"),
                patch.object(
                    audit.shutil,
                    "which",
                    side_effect=lambda name: str(npm) if name == "npm" else "node.exe",
                ),
            ):
                with self.assertRaisesRegex(ValueError, "npm CLI"):
                    audit._npm_command()
                cli.parent.mkdir(parents=True)
                cli.write_text("// fake CLI")
                self.assertEqual(audit._npm_command(), ["node.exe", str(cli)])
