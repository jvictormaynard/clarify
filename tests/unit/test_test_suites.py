"""Prove complete ownership and stable selection without application imports."""

from tempfile import TemporaryDirectory
import unittest

from scripts.test_suites import (
    CollectionError,
    EXTENDED_QT_SCALES,
    inventory,
    modules_for,
    parse_qt_scales,
    parse_shard,
    selected_suites,
    shard_cases,
    unique_cases,
)
from tests.support.suite_tree import suite_tree


class SuiteOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.root = suite_tree(self.enterContext(TemporaryDirectory()))

    def test_new_tests_are_collected_by_directory_without_a_name_allowlist(self):
        path = self.root / "tests/unit/test_future_behavior.py"
        path.touch()
        files = inventory(self.root)
        self.assertIn(
            "tests.unit.test_future_behavior",
            modules_for(files, selected_suites(["unit"])),
        )
        self.assertEqual(sum(len(paths) for paths in files.values()), 8)

    def test_unclassified_files_fail_even_when_another_suite_is_selected(self):
        for relative in (
            "test_unknown.py",
            "support/test_hidden.py",
            "future/test_new.py",
            "future_behavior.py",
            "contract/helper.py",
        ):
            with self.subTest(path=relative):
                path = self.root / "tests" / relative
                path.parent.mkdir(exist_ok=True)
                path.touch()
                with self.assertRaisesRegex(CollectionError, "Unclassified"):
                    inventory(self.root)
                path.unlink()

    def test_nested_tests_require_a_package_instead_of_disappearing(self):
        package = self.root / "tests/contract/nested"
        package.mkdir()
        (package / "test_nested.py").touch()
        with self.assertRaisesRegex(CollectionError, "not a package"):
            inventory(self.root)
        (package / "__init__.py").touch()
        self.assertIn(
            "tests/contract/nested/test_nested.py", inventory(self.root)["contract"]
        )

    def test_selection_is_unique_and_native_guards_keep_cross_platform_seams(self):
        self.assertEqual(
            [suite.name for suite in selected_suites(["unit", "unit", "contract"])],
            ["unit", "contract"],
        )
        self.assertEqual(len(selected_suites()), 7)
        self.assertIn("windows", [suite.name for suite in selected_suites()])
        with self.assertRaisesRegex(CollectionError, "Unknown"):
            selected_suites(["misspelled"])

    def test_duplicate_test_identities_fail_collection(self):
        case = unittest.FunctionTestCase(lambda: None, description="same identity")
        with self.assertRaisesRegex(CollectionError, "Duplicate"):
            unique_cases(unittest.TestSuite([case, case]))

    def test_shards_are_complete_disjoint_and_independent_of_input_order(self):
        cases = [
            unittest.FunctionTestCase(lambda: None, description=str(index))
            for index in range(17)
        ]
        # FunctionTestCase.id() uses the function name; assign distinct identities.
        for index, case in enumerate(cases):
            case.id = lambda index=index: f"case.{index:02}"
        shards = [shard_cases(cases, (number, 4)) for number in range(1, 5)]
        identities = [case.id() for shard in shards for case in shard]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(set(identities), {case.id() for case in cases})
        self.assertEqual(
            shard_cases(cases, (2, 4)), shard_cases(list(reversed(cases)), (2, 4))
        )
        self.assertEqual(parse_shard("2/4"), (2, 4))
        for value in ("0/2", "3/2", "1/0", "1", "a/b", "1/2/3"):
            with self.subTest(value=value), self.assertRaises(CollectionError):
                parse_shard(value)

    def test_extended_scales_remain_complete_and_reduced_input_is_explicit(self):
        self.assertEqual(parse_qt_scales("extended"), EXTENDED_QT_SCALES)
        self.assertEqual(parse_qt_scales("standard"), ("1", "2"))
        self.assertEqual(parse_qt_scales("1,1.5"), ("1", "1.5"))
        for value in ("", "0", "-1", "nan", "inf", "1,1.0", "bad"):
            with self.subTest(value=value), self.assertRaises(CollectionError):
                parse_qt_scales(value)

    def test_missing_or_empty_suite_is_a_collection_error(self):
        (self.root / "tests/unit/test_probe.py").unlink()
        with self.assertRaisesRegex(CollectionError, "no test files"):
            inventory(self.root)
