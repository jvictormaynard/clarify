"""Run unittest with an isolated profile before discovery imports application code.

Set CLARIFY_TEST_DURATIONS_JSON to an output path to record durations. Set
CLARIFY_TEST_DURATIONS_UNIT to test (default) or file.
Use --suite NAME (repeatable), --list-suites --json, --list --json, and
--shard N/M. With no arguments, collect all suites for the current platform.
Other unittest arguments pass through for focused and synthetic fixture tests.
Reports contain identifiers and results, never test output.
File durations sum test durations; discovery and class/module fixtures are excluded.
"""

import argparse
from contextlib import contextmanager
from fnmatch import fnmatchcase
import json
import os
import logging
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def isolated_environment():
    """Give tests and local checks a disposable profile without provider keys."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GEMINI_", "OPENAI_", "GROQ_", "REFINEMENT_"))
        and not re.search(r"(?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY)$", name, re.I)
    }
    with TemporaryDirectory(prefix="clarify-test-profile-") as directory:
        environment.update(
            {
                name: directory
                for name in (
                    "APPDATA",
                    "LOCALAPPDATA",
                    "USERPROFILE",
                    "HOME",
                    "XDG_DATA_HOME",
                )
            }
        )
        environment["CLARIFY_DATA_DIR"] = str(Path(directory) / "Clarify")
        environment["CLARIFY_SKIP_DOTENV"] = "1"
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        environment["QT_QUICK_CONTROLS_STYLE"] = "Basic"
        with patch.dict(os.environ, environment, clear=True):
            yield Path(directory)


class DurationResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self._started = None
        self._status = "passed"

    def startTest(self, test):
        self._started = time.perf_counter()
        self._status = "passed"
        super().startTest(test)

    def addFailure(self, test, err):
        if self._status != "error":
            self._status = "failed"
        super().addFailure(test, err)

    def addError(self, test, err):
        self._status = "error"
        super().addError(test, err)

    def addSkip(self, test, reason):
        if self._status == "passed":
            self._status = "skipped"
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, err):
        self._status = "expected_failure"
        super().addExpectedFailure(test, err)

    def addUnexpectedSuccess(self, test):
        self._status = "unexpected_success"
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            status = "failed" if issubclass(err[0], test.failureException) else "error"
            if self._status != "error":
                self._status = status
        super().addSubTest(test, subtest, err)

    def stopTest(self, test):
        module = test.__class__.__module__
        filename = getattr(sys.modules.get(module), "__file__", None)
        self.records.append(
            {
                "id": test.id(),
                "file": str(Path(filename).resolve()) if filename else module,
                "duration_seconds": time.perf_counter() - self._started,
                "status": self._status,
            }
        )
        self._started = None
        super().stopTest(test)


class DurationRunner(unittest.TextTestRunner):
    resultclass = DurationResult


def duration_report(result, unit):
    records = result.records
    if unit == "file":
        files = {}
        for record in records:
            entry = files.setdefault(
                record["file"],
                {
                    "file": record["file"],
                    "tests": 0,
                    "duration_seconds": 0,
                    "statuses": {},
                },
            )
            entry["tests"] += 1
            entry["duration_seconds"] += record["duration_seconds"]
            statuses = entry["statuses"]
            statuses[record["status"]] = statuses.get(record["status"], 0) + 1
        records = list(files.values())
    return {
        "schema": 1,
        "unit": unit,
        "successful": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "summary": {
            "failed": len(result.failures),
            "error": len(result.errors),
            "skipped": len(result.skipped),
            "expected_failure": len(result.expectedFailures),
            "unexpected_success": len(result.unexpectedSuccesses),
        },
        "records": records,
    }


class SuiteProgram(unittest.TestProgram):
    """Use unittest parsing, filtering, fixtures, and result handling unchanged."""

    def __init__(
        self,
        *args,
        list_only=False,
        json_output=False,
        shard=None,
        owned_files=None,
        selected=None,
        **kwargs,
    ):
        self.list_only = list_only
        self.json_output = json_output
        self.shard = shard
        self.owned_files = owned_files
        self.selected = selected
        super().__init__(*args, **kwargs)

    def _do_discovery(self, argv, Loader=None):
        # unittest chooses cwd discovery for an empty command even when
        # defaultTest is supplied. Use owned modules for that command.
        if not argv:
            self.testNames = list(self.defaultTest)
            self.createTests()
            return
        self.start, self.pattern, self.top = ".", "test*.py", None
        self._discovery_parser.parse_args(argv, self)
        directory = Path(self.start).resolve()
        if directory == ROOT or directory.is_relative_to(ROOT / "tests"):
            # Directory ownership also applies to explicit repository discovery.
            # Keep external synthetic fixture discovery on unittest's own path.
            self.testNames = [
                module
                for module in self.defaultTest
                if (ROOT / (module.replace(".", "/") + ".py")).is_relative_to(directory)
                and fnmatchcase(module.rsplit(".", 1)[-1] + ".py", self.pattern)
            ]
            if not self.testNames:
                from scripts.test_suites import CollectionError

                raise CollectionError(
                    "No owned test modules match the discovery request"
                )
            self.createTests()
            return
        self.createTests(from_discovery=True, Loader=Loader)

    def runTests(self):
        from scripts.test_suites import CollectionError, shard_cases, unique_cases

        if (self.list_only or self.shard) and self.testLoader.errors:
            raise CollectionError("\n".join(self.testLoader.errors))
        cases = unique_cases(self.test)
        rows = []
        allowed = {
            path: suite for suite, paths in self.owned_files.items() for path in paths
        }
        for test in cases:
            module = sys.modules.get(type(test).__module__)
            filename = getattr(module, "__file__", None)
            path = Path(filename).resolve() if filename else None
            relative = (
                path.relative_to(ROOT).as_posix()
                if path and path.is_relative_to(ROOT)
                else None
            )
            owner = allowed.get(relative)
            import_failure = isinstance(test, unittest.loader._FailedTest)
            if (
                self.selected is not None
                and owner not in self.selected
                and not import_failure
            ):
                raise CollectionError(f"Test is outside selected suites: {test.id()}")
            method = getattr(type(test), test._testMethodName, None)
            rows.append(
                {
                    "id": test.id(),
                    "suite": owner,
                    "file": relative or filename,
                    "skipped": bool(
                        getattr(type(test), "__unittest_skip__", False)
                        or getattr(method, "__unittest_skip__", False)
                    ),
                }
            )
        if self.shard:
            cases = shard_cases(cases, self.shard)
            identities = {test.id() for test in cases}
            rows = sorted(
                (row for row in rows if row["id"] in identities),
                key=lambda row: row["id"],
            )
            self.test = unittest.TestSuite(cases)
        if self.list_only:
            if self.json_output:
                print(
                    json.dumps(
                        {"schema": 1, "count": len(rows), "tests": rows}, indent=2
                    )
                )
            else:
                for row in rows:
                    print(row["id"])
            self.result = unittest.TestResult()
            return
        super().runTests()


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    parser = argparse.ArgumentParser(
        description="Run Python suites in an isolated profile.",
        epilog="Other arguments pass to unittest, including -v, -q, -k, -f, -b, and discover.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--suite", action="append", help="Suite name; repeat to combine suites"
    )
    listing = parser.add_mutually_exclusive_group()
    listing.add_argument(
        "--list-suites",
        action="store_true",
        help="List ownership without importing tests",
    )
    listing.add_argument(
        "--list", action="store_true", help="Collect and list test identities"
    )
    parser.add_argument(
        "--json", action="store_true", help="Write machine-readable listing output"
    )
    parser.add_argument("--shard", help="Run partition N/M of sorted test identities")
    parser.add_argument(
        "--qt-scales",
        default="extended",
        help="extended (default), standard, or comma-separated scales",
    )
    args, unittest_args = parser.parse_known_args(arguments)
    report_path = os.environ.get("CLARIFY_TEST_DURATIONS_JSON")
    unit = os.environ.get("CLARIFY_TEST_DURATIONS_UNIT", "test")
    if report_path and unit not in {"test", "file"}:
        parser.error("CLARIFY_TEST_DURATIONS_UNIT must be test or file")
    if args.json and not (args.list or args.list_suites):
        parser.error("--json requires --list or --list-suites")
    with (
        isolated_environment(),
        patch.object(sys, "path", [str(ROOT), *sys.path]),
    ):
        from scripts.test_suites import (
            CollectionError,
            SUITES,
            inventory,
            modules_for,
            parse_qt_scales,
            parse_shard,
            selected_suites,
        )

        # Nested runner invocations must not overwrite the outer report.
        os.environ.pop("CLARIFY_TEST_DURATIONS_JSON", None)
        os.environ.pop("CLARIFY_TEST_DURATIONS_UNIT", None)
        try:
            files = inventory(ROOT)
            suites = selected_suites(args.suite)
            shard = parse_shard(args.shard) if args.shard else None
            os.environ["CLARIFY_TEST_QT_SCALES"] = ",".join(
                parse_qt_scales(args.qt_scales)
            )
            if args.list_suites:
                rows = [
                    {
                        "name": suite.name,
                        "directory": "tests/" + suite.name,
                        "responsibility": suite.responsibility,
                        "native_platform": suite.native_platform,
                        "files": files[suite.name],
                    }
                    for suite in SUITES
                ]
                if args.json:
                    print(json.dumps({"schema": 1, "suites": rows}, indent=2))
                else:
                    for row in rows:
                        print(row["name"] + ": " + row["responsibility"])
                return 0
            options = (
                {"testRunner": DurationRunner} if report_path and not args.list else {}
            )
            program = SuiteProgram(
                module=None,
                argv=[sys.argv[0], *unittest_args],
                exit=False,
                testLoader=unittest.TestLoader(),
                defaultTest=modules_for(files, suites),
                list_only=args.list,
                json_output=args.json,
                shard=shard,
                owned_files=files,
                selected={suite.name for suite in suites} if args.suite else None,
                **options,
            )
        except CollectionError as error:
            parser.error(str(error))
        finally:
            # Windows cannot remove a profile with an open file handler.
            logging.shutdown()
    if report_path and not args.list:
        destination = Path(report_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(duration_report(program.result, unit), indent=2) + "\n",
            encoding="utf-8",
        )
    if not args.list and program.result.testsRun == 0 and not program.result.skipped:
        # Match unittest on the pinned Python 3.12 runtime.
        return 5 if program.result.wasSuccessful() else 1
    return int(not program.result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
