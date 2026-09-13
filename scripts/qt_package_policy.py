"""Bound the Qt payload to Clarify's QML imports, not the whole Qt SDK.

This is a packaging boundary, not a license-compliance certification.
"""

from pathlib import PurePosixPath


QUICK_MODULES = frozenset(
    {
        "Controls",
        "Dialogs",
        "Effects",
        "Layouts",
        "NativeStyle",
        "Shapes",
        "Templates",
        "Window",
    }
)


def allowed_qml_destination(destination: str) -> bool:
    path = destination.replace("\\", "/")
    if "/qml/" not in path:
        return False
    parts = path.split("/qml/", 1)[1].split("/")
    if parts[0] == "QtQml":
        return len(parts) == 1 or parts[1] in {"Models", "WorkerScript"}
    return parts[0] == "QtQuick" and (len(parts) == 1 or parts[1] in QUICK_MODULES)


def unexpected_qt_payload(names) -> list[str]:
    """Reject accidentally restored optional Qt modules in the final archive."""
    unexpected = []
    for name in names:
        path = name.replace("\\", "/")
        if not path.startswith("PySide6/"):
            continue
        if "/qml/" in path:
            if not allowed_qml_destination(str(PurePosixPath(path).parent)):
                unexpected.append(name)
        # Check DLLs too: Python bindings or non-QML plugins can pull them in.
        stem = PurePosixPath(path).stem.lower()
        if stem.startswith(
            (
                "qt6graphs",
                "qt6charts",
                "qt6datavisualization",
                "qt6quick3d",
                "qt6quicktimeline",
                "qt6virtualkeyboard",
                "qt6webengine",
                "qt6webview",
                "qt6scxml",
                "qt63d",
                "qt6lottie",
            )
        ):
            unexpected.append(name)
    return sorted(set(unexpected))
