# License archive supplements

Some published npm and Cargo archives declare a license but omit its text.
`manifest.json` maps exact package URLs and versions to upstream license texts,
with source URLs and SHA-256 digests. The inventory fails on an unknown missing
license or changed text; dependency updates do not silently inherit a supplement.

Cargo source commits come from each archive's `.cargo_vcs_info.json`. The
standard MPL 2.0 text for `selectors` comes from Mozilla; generated notices also
link to the exact unmodified crate source, which retains its source notices.

`source-components.json` records copied source outside the npm/Cargo dependency
graph. Each entry pins its source revision, package URL, license text, source
URL, and SHA-256 digest. The inventory includes these components in the SBOM
and verifies and appends their notices to the packaged Settings notices.

These files supplement the package license texts, not the project's MIT license.
The build copies them verbatim into `Clarify-settings-NOTICES.txt` with provenance.
