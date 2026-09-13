"""Collect only the QML modules used by Clarify's pill and compatibility UI."""

import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info


policy_path = Path(__file__).resolve().parents[1] / "qt_package_policy.py"
spec = importlib.util.spec_from_file_location("clarify_qt_package_policy", policy_path)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
# Developer profilers are not needed by the release and can pull in Quick 3D.
binaries = [entry for entry in binaries if "qmltooling" not in entry[1]]
qml_binaries, qml_datas = pyside6_library_info.collect_qtqml_files()
binaries += [
    entry for entry in qml_binaries if policy.allowed_qml_destination(entry[1])
]
datas += [entry for entry in qml_datas if policy.allowed_qml_destination(entry[1])]
