"""Directory ownership and deterministic collection for the Python suites.

This module uses only the standard library. Inventory does not import tests or
application code. The runner installs the temporary profile before collection.
"""

from dataclasses import dataclass
from fnmatch import fnmatchcase
import math
from pathlib import Path
import unittest


class CollectionError(ValueError):
    """The requested collection cannot prove complete, unique ownership."""


@dataclass(frozen=True)
class Suite:
    name: str
    responsibility: str
    native_platform: str | None = None


SUITES = (
    Suite("unit", "Domain values, decisions, and state with controlled doubles."),
    Suite("contract", "Public boundaries with fake transport, clocks, and devices."),
    Suite("integration", "Persistence, subprocesses, and local service composition."),
    Suite("qt", "Qt controllers, signals, event loops, QML, and UI subprocesses."),
    # Mocked Windows seams run on every OS. Individual native cases retain
    # their unittest platform guards, as they did before the suite split.
    Suite("windows", "Windows API seams and native Windows checks.", "win32"),
    Suite("compatibility", "Legacy app adapters and retained prototype contracts."),
    Suite("policy", "Repository, CI, packaging, and publication policies."),
)
SUITE_BY_NAME = {suite.name: suite for suite in SUITES}
EXTENDED_QT_SCALES = ("1", "1.25", "1.5", "2")
STANDARD_QT_SCALES = ("1", "2")


def inventory(root):
    """Fail on test files outside a suite or below a non-package directory."""
    root = Path(root).resolve()
    directory = root / "tests"
    files = {suite.name: [] for suite in SUITES}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise CollectionError(f"Linked test path has no unique owner: {path}")
        if path.suffix != ".py" or not path.is_file() or path.name == "__init__.py":
            continue
        test_file = fnmatchcase(path.name, "test*.py")
        if relative.parts[0] == "support" and not test_file:
            continue
        if relative.as_posix() in {
            "web_settings_fixture.py",
            "portable_update_fixture.py",
        }:
            # Active browser/native RPC and frozen-update entrypoints.
            continue
        if not test_file or len(relative.parts) < 2 or relative.parts[0] not in files:
            raise CollectionError(
                f"Unclassified test file: tests/{relative.as_posix()}"
            )
        if not path.stem.isidentifier():
            raise CollectionError(f"Invalid test module: {path}")
        parent = path.parent
        while parent != root:
            if parent.is_symlink() or not (parent / "__init__.py").is_file():
                raise CollectionError(f"Test directory is not a package: {parent}")
            parent = parent.parent
        files[relative.parts[0]].append(path.relative_to(root).as_posix())
    for name, paths in files.items():
        if not paths:
            raise CollectionError(f"Suite has no test files: {name}")
    return files


def selected_suites(names=None):
    if names:
        unknown = set(names) - SUITE_BY_NAME.keys()
        if unknown:
            raise CollectionError("Unknown suites: " + ", ".join(sorted(unknown)))
        requested = set(names)
        return tuple(suite for suite in SUITES if suite.name in requested)
    return SUITES


def modules_for(files, suites):
    return [
        path[:-3].replace("/", ".") for suite in suites for path in files[suite.name]
    ]


def test_cases(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_cases(test)
        else:
            yield test


def unique_cases(suite):
    cases = list(test_cases(suite))
    seen = set()
    for test in cases:
        identity = test.id()
        if identity in seen:
            raise CollectionError(f"Duplicate test identity: {identity}")
        seen.add(identity)
    return cases


def parse_shard(value):
    try:
        number, count = (int(part) for part in value.split("/"))
    except (ValueError, TypeError):
        raise CollectionError("Shard must be N/M, with 1 <= N <= M") from None
    if not 1 <= number <= count:
        raise CollectionError("Shard must be N/M, with 1 <= N <= M")
    return number, count


def shard_cases(cases, shard):
    """Partition sorted identities; each test belongs to exactly one shard."""
    number, count = shard
    return sorted(cases, key=lambda test: test.id())[number - 1 :: count]


def parse_qt_scales(value):
    if value == "standard":
        return STANDARD_QT_SCALES
    if value == "extended":
        return EXTENDED_QT_SCALES
    values = value.split(",")
    try:
        numbers = [float(scale) for scale in values]
    except ValueError:
        raise CollectionError(
            "Qt scales must be standard, extended, or comma-separated numbers"
        ) from None
    if (
        not numbers
        or any(not math.isfinite(scale) or not 0 < scale <= 8 for scale in numbers)
        or len(set(numbers)) != len(numbers)
    ):
        raise CollectionError(
            "Qt scales must be unique finite numbers greater than 0 and at most 8"
        )
    return tuple(format(scale, "g") for scale in numbers)
