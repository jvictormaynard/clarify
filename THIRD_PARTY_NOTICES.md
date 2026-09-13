# Third-party notices

Clarify includes or depends on third-party software. Each component remains
under its own license; the project MIT license does not replace those terms.

## Bundled in the Windows executable

| Component | Purpose | License information |
| --- | --- | --- |
| SoX 14.4.2 and its bundled codecs | Audio conversion | GPL-2.0-or-later; vendored text at `extra/sox-14.4.2/LICENSE.GPL.txt` |
| Python | Runtime | Python Software Foundation License |
| PySide6 / Qt | Desktop engine and QML pill | PySide6 metadata: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only; Qt module and distribution terms must be reviewed for the release |
| React / React DOM | Settings interface | MIT; Meta Platforms, Inc. and affiliates |
| Radix UI | Settings controls | MIT; WorkOS |
| cmdk | Searchable Settings pickers | MIT; Paco Coursey |
| Lucide | Settings icons | ISC, with Feather portions under MIT; see the package LICENSE |
| Tauri | Native Settings child window | MIT OR Apache-2.0; transitive crate terms also apply |
| Pillow | Image rendering | HPND |
| Requests | HTTP client | Apache-2.0 |
| sounddevice | Audio capture | MIT |
| PyInstaller bootloader | Portable packaging | GPL-2.0-or-later with a special exception for bundled applications |

PyInstaller is a build dependency. Its bootloader becomes part of the portable
executable under PyInstaller's documented exception.

The SoX runtime is invoked as a separate process and is not linked into the
Clarify source. Every tagged release provides `sox-14.4.2-source.tar.gz`
next to the Windows binary. The release workflow downloads the archive from the
[official SoX 14.4.2 files](https://sourceforge.net/projects/sox/files/sox/14.4.2/)
and requires this SHA-256 before publication:

```text
b45f598643ffbd8e363ff24d61166ccec4836fea6d3888881b8df53e3bb55f6c
```

The upstream Windows README names the codec and runtime projects used in that
distribution and is preserved at `extra/sox-14.4.2/README.win32.txt` and inside
the portable package.

## Optional local-ASR assets (not bundled)

The Local Whisper provider can download the following assets after explicit
user action in Settings. The runtime and weights are not bundled in the portable
executable. Their manifests and notices are bundled.

| Component | Purpose | Version/model | License |
| --- | --- | --- | --- |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp/tree/v1.9.1) | Local transcription sidecar, CPU or compatible NVIDIA GPU | v1.9.1 Windows x64 | MIT, copyright the ggml authors |
| [Whisper ggml small model](https://huggingface.co/ggerganov/whisper.cpp/blob/80da2d8bfee42b0e836fc3a9890373e5defc00a6/ggml-small.bin) | Multilingual local ASR weights converted for whisper.cpp | `ggml-small` | MIT per the upstream model card; derived from [OpenAI Whisper](https://github.com/openai/whisper) |

Exact URLs, sizes, SHA-256 digests, and extracted runtime file hashes are in
`local_asr_manifest.json` and `local_asr_manifests/`, including the Base, Small,
and Medium profiles. Their copyright and license notices must remain in
distributed Clarify documentation. The complete notices are preserved in
`licenses/whisper.cpp-MIT.txt` and `licenses/openai-whisper-MIT.txt`; the
maintainer harness copies them beside an isolated installation. The upstream
warning not to run the example HTTP server with administrative privileges
applies; Clarify binds it only to loopback.

## Flag assets

The extracted flag-icons SVGs are covered by the upstream MIT notice retained
at `licenses/flag-icons-MIT.txt` (Panayiotis Lipiridis). No flag-icons runtime
dependency is required.

## Settings dependency inventory

The table above is a component overview. `scripts/settings_inventory.py` also
collects the license texts of installed npm production dependencies and the
locked Cargo graph for Windows. Each Settings build produces
`Clarify-settings-NOTICES.txt` and `Clarify-settings.sbom.json`. Both files are
embedded beside the Settings child in the portable executable; the notices are
also included in the release ZIP. The release SBOM merges Settings with the
existing Python and SoX inventory.

The Settings SBOM records the child executable SHA-256, lockfile hashes, and
pinned Rust toolchain. Cargo build-only crates are included with excluded scope
for attribution; this source graph is not proof of binary linkage. Each crate
includes a link to its exact-version source archive.

Where upstream packages omit license texts, reviewed supplements are retained
in `desktop/licenses/`, with version-specific mappings, source URLs, and SHA-256
checks. A missing or changed supplement fails the build. See
[supplement provenance](desktop/licenses/README.md).

Qt 6.11.1 and PySide/Shiboken source archives are supplied separately as
`Clarify-qt-sources.zip`, with pinned upstream hashes. `Clarify-qt-NOTICES.txt`
contains their license and third-party attribution texts and is included in the
executable and release ZIP. See [source and replacement instructions](docs/qt-distribution.md).
This inventory is engineering evidence, not legal certification; see
[Release readiness](docs/release-readiness.md).
The [publication review](docs/release-review-2026-09-13.md) records why the
default Qt plugin collection is restricted before distribution approval.

## Provider marks

The OpenAI, Gemini, and Groq marks under `assets/providers/` identify compatible
API providers. The names and marks remain the property of their respective
owners. Their presence does not imply endorsement or affiliation.

## Legacy prototype

The removed Electron prototype is retained in Git history, not in the current
checkout or build. If it is revived, its npm dependency licenses must be
reviewed and documented before distribution.

Maintainers should update this file whenever a distributed dependency or
third-party asset changes.

## Optional NVIDIA CUDA runtime

Local GPU setup downloads the pinned CUDA runtime and cuBLAS package. Their
license is retained in `licenses/NVIDIA-CUDA-runtime.txt`; NVIDIA terms apply.
The runtime packages and model weights are downloaded only during explicit local
model installation and are not bundled in the portable executable.
