"""Small Python suite tree for runner boundary tests."""

from pathlib import Path

from scripts.test_suites import SUITES


def suite_tree(directory):
    root = Path(directory).resolve()
    tests = root / "tests"
    tests.mkdir()
    (tests / "__init__.py").touch()
    for suite in SUITES:
        package = tests / suite.name
        package.mkdir()
        (package / "__init__.py").touch()
        (package / "test_probe.py").write_text(
            "import unittest\n"
            "class Probe(unittest.TestCase):\n"
            "    def test_pass(self): pass\n",
            encoding="utf-8",
        )
    return root
