"""Inputs for isolated Qt subprocess checks. No Qt import or runtime setup."""

import os

from scripts.test_suites import parse_qt_scales


def qt_scales():
    return parse_qt_scales(os.environ.get("CLARIFY_TEST_QT_SCALES", "extended"))
