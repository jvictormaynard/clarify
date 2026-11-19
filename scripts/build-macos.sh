#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ $(uname -s) != Darwin ]]; then
    echo 'Build Clarify for macOS on a Mac.' >&2
    exit 1
fi

repo=$PWD
python="$repo/.venv/bin/python"
arch=x64
if [[ $(uname -m) == arm64 ]]; then arch=arm64; fi

npm --prefix desktop ci --no-audit --no-fund
npm --prefix desktop run build:electron

shell_app="$repo/desktop/electron-dist/Clarify Desktop-darwin-$arch/Clarify Desktop.app"
output="$repo/dist/macos"
work="$repo/build/macos"
mkdir -p "$work"
app="$output/Clarify.app"

"$python" -m PyInstaller --noconfirm --clean --onedir --windowed \
    --name Clarify --osx-bundle-identifier com.clarify.desktop \
    --icon "$repo/assets/branding/clarify.ico" \
    --distpath "$output" --workpath "$work" --specpath "$work" \
    --additional-hooks-dir "$repo/scripts/pyinstaller-hooks" \
    --paths "$repo" --paths "$repo/clarify/desktop" \
    --exclude-module _distutils_hack --exclude-module chardet --exclude-module defusedxml \
    --exclude-module lark --exclude-module lxml --exclude-module packaging \
    --exclude-module setuptools --exclude-module tomli --exclude-module typing_extensions \
    --exclude-module wheel \
    --add-data "$repo/clarify/desktop/qml:qml" \
    --add-data "$repo/assets:assets" \
    --add-data "$repo/shared:shared" \
    --add-data "$repo/distribution:distribution" \
    --add-data "$repo/local_asr_manifest.json:." \
    --add-data "$repo/local_asr_manifests:local_asr_manifests" \
    --add-data "$repo/licenses:licenses" \
    "$repo/clarify/desktop/qml_app.py"

contents="$app/Contents"
# The cross-platform sounddevice wheel also contains Windows-only audio DLLs.
for folder in Frameworks Resources; do
    find "$contents/$folder/_sounddevice_data/portaudio-binaries" -name '*.dll' -exec rm {} +
done
mkdir -p "$contents/Helpers"
ditto "$shell_app" "$contents/Helpers/Clarify Desktop.app"
plist="$contents/Info.plist"
version=$("$python" -c 'from version import __version__; print(__version__)')
/usr/libexec/PlistBuddy -c 'Add :LSUIElement bool true' \
    -c 'Add :LSMinimumSystemVersion string 13.0' \
    -c 'Add :NSMicrophoneUsageDescription string Clarify uses your microphone when you record.' \
    -c "Set :CFBundleShortVersionString $version" "$plist"
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"
printf '%s\n' "$app"
