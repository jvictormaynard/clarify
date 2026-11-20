#!/usr/bin/env bash
set -euo pipefail

if [[ $(uname -s) != Darwin || $(uname -m) != arm64 ]]; then
    echo 'Package the macOS release on an Apple Silicon Mac.' >&2
    exit 1
fi

cd "$(dirname "$0")/.."
repo=$PWD
python="$repo/.venv/bin/python"
output=${1:?Output directory is required}
qt_notices=${2:?Path to verified Qt notices is required}
app="$repo/dist/macos/Clarify.app"
electron="$repo/desktop/electron-dist/Clarify Desktop-darwin-arm64"
asset=Clarify-macos-arm64.zip
mkdir -p "$output"
output=$(cd "$output" && pwd)
[[ ! -e "$output/$asset" && ! -e "$output/$asset.sha256" ]]

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/package" "$work/extracted" "$work/profile"
package="$work/package"
codesign --verify --deep --strict "$app"
ditto "$app" "$package/Clarify.app"
cp LICENSE THIRD_PARTY_NOTICES.md "$package/"
cp "$qt_notices" "$package/Clarify-qt-NOTICES.txt"

"$python" -m cyclonedx_py requirements requirements-lock-runtime-macos.txt \
    --output-reproducible --of JSON -o "$package/Clarify-macos.sbom.json"
"$python" scripts/settings_inventory.py --desktop desktop --output-dir "$work" \
    --electron-macos-shell "$electron"
"$python" scripts/settings_inventory.py --merge-bom "$package/Clarify-macos.sbom.json" \
    --settings-bom "$work/Clarify-settings.sbom.json"
cp "$work/Clarify-settings-NOTICES.txt" "$package/"
"$python" scripts/portable_crypto_inventory.py --output-dir "$package" \
    --bom "$package/Clarify-macos.sbom.json"

"$python" scripts/macos_dependency_inventory.py --output-dir "$package" \
    --bom "$package/Clarify-macos.sbom.json"
ditto -c -k --norsrc --noextattr "$package" "$work/$asset"
ditto -x -k "$work/$asset" "$work/extracted"
executable="$work/extracted/Clarify.app/Contents/MacOS/Clarify"
shell="$work/extracted/Clarify.app/Contents/Helpers/Clarify Desktop.app/Contents/MacOS/Clarify Desktop"
codesign --verify --deep --strict "$work/extracted/Clarify.app"
[[ $(lipo -archs "$executable") == arm64 && $(lipo -archs "$shell") == arm64 ]]
env -i PATH=/usr/bin:/bin HOME="$work/profile" CLARIFY_DATA_DIR="$work/profile" \
    CLARIFY_SKIP_DOTENV=1 CLARIFY_IMPORT_SMOKE_TEST=1 QT_QPA_PLATFORM=offscreen "$executable"
(cd "$work" && shasum -a 256 "$asset" > "$asset.sha256")
mv "$work/$asset" "$work/$asset.sha256" "$output/"
