# Frontend source notices

`source-components.json` records copied source and assets outside the npm
dependency graph. Each entry pins its source revision, package URL, license text,
source URL and SHA-256 digest. The inventory verifies these notices and includes
them in the packaged Settings notices and SBOM.

Installed npm packages must supply their license texts. Electron contributes
its native runtime notices. Missing text or a changed source-notice checksum
fails the build. These notices preserve each component's terms; the project's
MIT license does not replace them.
