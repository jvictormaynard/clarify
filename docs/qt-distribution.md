# Qt source and replacement information

Clarify uses unmodified PySide6-Essentials and Shiboken6 6.11.2 wheels and the
Qt 6.11.2 shared libraries supplied in those wheels. The selected Qt runtime
modules are Qt Base (Core, GUI, Widgets, Network, OpenGL), Qt Declarative
(QML and Quick, controls, dialogs, layouts, effects and shapes), and Qt SVG.
Clarify's MIT license does not replace the licenses of these libraries.

The release supplies `Clarify-qt-sources.zip` alongside the executable. It
contains the complete upstream source archives for those modules, PySide and
Shiboken, plus Qt Shader Tools and Qt Tools for rebuilding. The original build
scripts, third-party sources and notices remain in those archives. These
additional sources do not mean their tools are linked into Clarify.

`scripts/qt_sources.json` pins each archive to the upstream SHA-256 published
with Qt 6.11.2. `Clarify-qt-NOTICES.txt` collects the upstream license texts,
copyright notices and attribution records, conservatively including components
not linked into the application. It is included in the portable package and
release ZIP. The source ZIP is a separate download; no Qt source download occurs
when an end user starts Clarify.

## Inspect, modify and rebuild

You may inspect, modify and rebuild the Qt/PySide libraries under their applicable
licenses. Clarify imposes no restriction on reverse engineering for debugging
your changes to those libraries. The LGPL and GPL texts are included in the
source and notices files. This document does not add a license restriction.

1. Download the Clarify source for the same release tag and the Qt source ZIP.
2. Read `CONTRIBUTING.md` for the Windows Python, Node, Rust and MSVC build tools.
3. Extract the Qt archives into a separate development directory. Build Qt Base,
   then Shader Tools, Declarative, SVG and any required tools against that Qt
   installation. Keep the Qt libraries shared rather than static.
4. Build PySide/Shiboken from the supplied pyside-setup archive against your Qt
   installation. Use the source archive's build instructions and the official
   [Qt build guide](https://doc.qt.io/qt-6/build-sources.html) and
   [Qt for Python build guide](https://doc.qt.io/qtforpython-6/building_from_source/index.html).
5. Install your rebuilt wheels in an isolated Python environment with Clarify's
   other requirements. Run `python clarify/desktop/qml_app.py` from the Clarify
   source root. This source mode is the direct way to test a replacement.
6. To create a replacement portable EXE, build Settings as documented, put your
   wheels in the build environment and run `scripts/build.ps1`. Its normal setup
   uses the pinned versions; keep version 6.11.2 for a same-version modified
   build, or explicitly update the version constraints, locks and source
   manifest when developing against a different version. Re-run the tests.

The portable EXE expands its bundled shared libraries into a temporary directory
at startup. Do not edit that temporary directory as a persistent replacement:
use source mode or rebuild the portable package. No signing key is required to
run your own build. An unsigned replacement may trigger Windows SmartScreen.

This is an engineering distribution record, not a legal certification or a
claim that a custom Qt build reproduces upstream wheel bytes. Review any new
module or third-party component before changing the published bundle.
