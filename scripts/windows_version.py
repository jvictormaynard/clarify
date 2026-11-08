"""Generate and verify the Windows PE version from the canonical version.py."""

import argparse
import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def version_parts(version: str) -> tuple[int, int, int, int]:
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Windows packaging requires a stable X.Y.Z version")
    major, minor, patch = map(int, version.split("."))
    if max(major, minor, patch) > 65535:
        raise ValueError("Windows version components must fit in 16 bits")
    return major, minor, patch, 0


def read_version(source: Path) -> str:
    # Accept the module docstring and one literal assignment. Never import or
    # execute a source file supplied to a packaging gate.
    try:
        statements = ast.parse(source.read_text(encoding="utf-8-sig")).body
    except SyntaxError as error:
        raise ValueError("Cannot parse version.py") from error
    if statements and isinstance(statements[0], ast.Expr):
        value = statements[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            statements = statements[1:]
    if len(statements) == 1 and isinstance(statements[0], ast.Assign):
        assignment = statements[0]
        if (
            len(assignment.targets) == 1
            and isinstance(assignment.targets[0], ast.Name)
            and assignment.targets[0].id == "__version__"
            and isinstance(assignment.value, ast.Constant)
            and isinstance(assignment.value.value, str)
        ):
            version = assignment.value.value
            version_parts(version)
            return version
    raise ValueError("version.py must contain one literal __version__ assignment")


def version_strings(version: str) -> dict[str, str]:
    numeric = ".".join(map(str, version_parts(version)))
    return {
        "CompanyName": "Joao Victor Maynard Mota",
        "FileDescription": "Clarify",
        "FileVersion": numeric,
        "InternalName": "Clarify",
        "LegalCopyright": "Copyright (c) 2026 João Victor Maynard Mota",
        "OriginalFilename": "Clarify.exe",
        "ProductName": "Clarify",
        "ProductVersion": numeric,
    }


def render_version_info(version: str) -> str:
    parts = version_parts(version)
    strings = "\n".join(
        f"        StringStruct({key!r}, {value!r}),"
        for key, value in version_strings(version).items()
    )
    return (
        "# UTF-8\nVSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r},\n"
        "                    mask=0x3f, flags=0, OS=0x40004,\n"
        "                    fileType=1, subtype=0, date=(0, 0)),\n"
        "  kids=[\n    StringFileInfo([StringTable('040904B0', [\n"
        f"{strings}\n"
        "    ])]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])]),\n"
        "  ]\n)\n"
    )


def verify_pe_version(executable: Path, version: str) -> None:
    # pefile is already a pinned PyInstaller build dependency on Windows.
    import pefile

    major, minor, patch, revision = version_parts(version)
    expected = ((major << 16) | minor, (patch << 16) | revision)
    try:
        with pefile.PE(str(executable), fast_load=True) as pe:
            pe.parse_data_directories(
                directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
            )
            resources = getattr(pe, "DIRECTORY_ENTRY_RESOURCE", None)
            if resources is None or not any(
                entry.id == pefile.RESOURCE_TYPE["RT_VERSION"]
                for entry in resources.entries
            ):
                raise ValueError("The executable has no RT_VERSION resource")
            fixed = getattr(pe, "VS_FIXEDFILEINFO", [])
            if len(fixed) != 1 or fixed[0].Signature != 0xFEEF04BD:
                raise ValueError("The executable has no valid VS_FIXEDFILEINFO")
            for name in ("FileVersion", "ProductVersion"):
                actual = (
                    getattr(fixed[0], name + "MS"),
                    getattr(fixed[0], name + "LS"),
                )
                if actual != expected:
                    raise ValueError(f"PE {name} differs from version.py")
            tables = [
                table
                for group in getattr(pe, "FileInfo", [])
                for item in group
                if item.Key == b"StringFileInfo"
                for table in item.StringTable
            ]
            if len(tables) != 1:
                raise ValueError("The executable must have one version string table")
            for key, value in version_strings(version).items():
                if tables[0].entries.get(key.encode("utf-8")) != value.encode("utf-8"):
                    raise ValueError(f"PE version string {key} differs from the build")
    except pefile.PEFormatError as error:
        raise ValueError("Cannot read the executable's PE version") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version-source", type=Path, default=ROOT / "version.py")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--check-pe", type=Path)
    args = parser.parse_args()
    try:
        version = read_version(args.version_source)
        if args.output is not None:
            args.output.write_text(
                render_version_info(version), encoding="utf-8", newline="\n"
            )
        else:
            verify_pe_version(args.check_pe, version)
            print(f"Windows PE version matches version.py: {version}.0")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Windows version verification failed: {error}\n")


if __name__ == "__main__":
    main()
