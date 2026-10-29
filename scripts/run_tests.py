"""Run unittest with an isolated profile before discovery imports application code."""

import os
import logging
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class ProductTestLoader(unittest.TestLoader):
    def loadTestsFromModule(self, module, *, pattern=None):
        # Repository owns these platform-independent policies on every CI run.
        covered = {"test_delivery_policy", "test_release_delivery"}
        if sys.platform != "win32" or os.environ.get("CLARIFY_CI_QA_POLICY") == "false":
            # Keep Windows filesystem/PowerShell cases when QA changes or its
            # selection is uncertain. Repository already covers the POSIX cases.
            covered |= {
                "test_trusted_ci",
                "test_testflight_qa",
                "test_qa_device_archive",
            }
        if module.__name__.removeprefix("tests.") in covered:
            return self.suiteClass()
        return super().loadTestsFromModule(module, pattern=pattern)


def main(arguments=None):
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    ci_product_tests = "--ci-product-tests" in arguments
    if ci_product_tests:
        arguments.remove("--ci-product-tests")
    if not arguments:
        arguments = ["discover", "-s", str(ROOT / "tests"), "-v"]
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
        # Match the product style before discovery creates the first QML engine.
        environment["QT_QUICK_CONTROLS_STYLE"] = "Basic"
        with patch.dict(os.environ, environment, clear=True):
            try:
                result = unittest.main(
                    module=None,
                    argv=[sys.argv[0], *arguments],
                    exit=False,
                    testLoader=ProductTestLoader()
                    if ci_product_tests
                    else unittest.TestLoader(),
                )
            finally:
                # Windows cannot remove a profile with an open file handler.
                logging.shutdown()
    return int(not result.result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
