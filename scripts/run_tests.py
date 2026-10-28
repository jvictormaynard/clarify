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


def main(arguments=None):
    sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
    arguments = list(sys.argv[1:] if arguments is None else arguments)
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
        with patch.dict(os.environ, environment, clear=True):
            try:
                result = unittest.main(
                    module=None, argv=[sys.argv[0], *arguments], exit=False
                )
            finally:
                # Windows cannot remove a profile with an open file handler.
                logging.shutdown()
    return int(not result.result.wasSuccessful())


if __name__ == "__main__":
    raise SystemExit(main())
