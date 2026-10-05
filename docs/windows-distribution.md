# Windows distribution and update security

This document defines the target installer, signing, update, recovery, and
incident contract. The repository contains no private key or reusable signing
credential. Portable updates use the Ed25519 contract below from v0.5.0.
The sponsored Authenticode MSI channel remains fail-closed until its separate
prerequisites in [Rollout gates](#rollout-gates) are complete.

## No-cost community release

While sponsored signing is unavailable, the repository may publish a
community portable release. It contains the unsigned portable EXE, its
SHA-256 file, the runtime SBOM, the portable ZIP, the verified SoX source
archive, the Qt/PySide source ZIP, and GitHub build provenance. The portable ZIP
includes Settings, Qt, and cryptography/OpenSSL license notices. From v0.5.0,
the release also contains `Clarify-portable-update.json` and its detached
Ed25519 signature, `Clarify-portable-update.json.sig`. It does not contain the
MSI or the Authenticode CAB manifest.

The community EXE is not a trusted Authenticode publisher. Windows SmartScreen
may show a warning, so the user must verify the published SHA-256 before the
first launch. A metadata signature authenticates the exact portable executable
for later in-app updates; it does not add an Authenticode publisher signature.
The MSI contract below remains the target for a future sponsored release.

## Authenticated portable updates

The packaged `distribution/portable-update-policy.json` pins the Ed25519 public
key, canonical repository, stable channel, and 256 MiB download limit. The
private key is the `CLARIFY_UPDATE_SIGNING_KEY` secret in the GitHub
`portable-updates` environment. Only `v*` tags can use this environment. The
community workflow requires the tag's exact commit to belong to canonical
`main`, checks that the packaged version matches the tag, and refuses a signing
key that differs from the packaged pin. Release publication still requires
green PR and main tests/packaging before tagging. No paid signing service is
used by this portable channel.

The app checks GitHub's latest stable release 30 seconds after startup and
every six hours. Requests use bounded HTTPS reads and a fixed GitHub host
allowlist; provider credentials and `.netrc` are not read. Authenticate raw
manifest bytes before parsing strict identity, source commit, version, URL,
size, and SHA-256 fields. Refuse prereleases, downgrades, duplicate fields,
unexpected URLs, changed signatures, and missing metadata. Interrupted or
oversized downloads never reach the installation transaction.

`automatic_updates` is off by default and changes only when Settings are saved.
With it off, show a red dot on the home pill's Settings button and **Install
update X.Y.Z** in the quick menu. With it on, download in the background. Both
paths wait for idle workflows, closed Settings, no unsaved drafts/results,
and no active audio/model/provider work. The native Settings child must have
ended; a hidden WebView can still own unsaved form fields. Close it using its
normal confirmation flow before restart. Block new UI/hotkey input only while
the helper is being armed and the app exits. A failed preparation leaves the
current app running. The installation folder must be writable by the user;
the updater never requests elevation and refuses MSI-owned paths.

The helper is a copy of the current installed executable. It binds the target
to the parent's image path, SHA-256, retained process handle, and creation time;
then acknowledges preparation before the app quits. After graceful exit, it
rechecks signed metadata and binary bytes, stages on the installation volume,
atomically keeps the old executable and installs the new one, and launches an
independent PyInstaller process with `--hidden`. A receipt from the first Qt
event-loop tick after QML and single-instance startup confirms success. On
failed startup, stop only the new child, restore the old executable, and restart
it. Keep a failed-version marker to prevent repeated automatic restart attempts;
manual retry remains available. Keep the most recent verified backup. If
Windows prevents restoration, preserve that backup for manual recovery.

Profiles, DPAPI keys, downloaded models, statistics, and shortcuts are outside
this transaction. Cache attempts older than 24 hours are removed only when
their paths and contents match the updater's owned file set. Verify the
embedded key and crypto notices during packaging, add OpenSSL to the release
SBOM, and attest both metadata assets with the EXE and ZIP.

`python scripts/test_portable_update.py` builds isolated Windows fixtures with
a generated test key. It tests actual one-file process exit, file replacement,
restart receipt, failed-startup rollback, and tamper rejection. It does not
read user profiles, start microphones, register hotkeys, or touch an existing
Clarify installation. CI and the community release run this acceptance gate.

For planned key rotation, first ship an update that trusts both old and new
pins while signing with the old key, then switch signing, then remove the old
pin in a later release. The initial schema supports one pin; implement and test
the overlap before rotation. Do not overwrite the secret/pin independently.
If the signing key is lost or compromised, stop publication, remove the
affected release from the stable channel, and publish a reviewed replacement
requiring one manual download. Do not bypass signature verification.

## Signing mechanism and ownership

Clarify uses [Azure Artifact Signing](https://azure.microsoft.com/en-us/products/artifact-signing)
(formerly Trusted Signing) with its public-trust certificate profile:

- For the future signed track, the project owner, João Victor Maynard Mota,
  will own the Azure subscription, verified publisher identity, Artifact
  Signing account, and certificate profile after sponsored provisioning.
- The release job authenticates through GitHub OIDC and a federated Microsoft
  Entra identity restricted to the protected `release-signing` environment.
  There is no client secret or exportable certificate private key in GitHub.
- The federated identity receives only the **Artifact Signing Certificate
  Profile Signer** role for the selected profile. The GitHub environment must
  require owner approval and tag release jobs must originate from protected
  `main` history.
- Azure protects the managed private key in FIPS 140-2 Level 3 HSMs. Release
  runners submit digests; the private key is not downloaded.
- The executable, MSI, and release-manifest CAB are signed with SHA-256 and an
  RFC 3161 timestamp from `http://timestamp.acs.microsoft.com`. Microsoft notes
  that Artifact Signing certificates are short lived, so timestamping is
  required for signatures to remain valid after certificate expiry.

As of 2026-08-02, Microsoft lists the Basic plan at USD 9.99/month for 5,000
signatures and USD 0.005 for each additional signature. The Premium plan is
USD 99.99/month for 100,000 signatures with the same overage. The owner must
check the [current official pricing](https://azure.microsoft.com/en-us/products/artifact-signing#pricing)
before provisioning because prices and regional availability can change.

Required protected GitHub configuration:

| Kind | Name | Purpose |
| --- | --- | --- |
| Secret | `AZURE_CLIENT_ID` | Federated application/client identity |
| Secret | `AZURE_TENANT_ID` | Microsoft Entra tenant |
| Secret | `AZURE_SUBSCRIPTION_ID` | Azure subscription |
| Variable | `AZURE_ARTIFACT_SIGNING_ENDPOINT` | Regional signing endpoint |
| Variable | `AZURE_ARTIFACT_SIGNING_ACCOUNT` | Artifact Signing account |
| Variable | `AZURE_ARTIFACT_SIGNING_PROFILE` | Public-trust certificate profile |

`distribution/update-policy.json` pins the legal publisher common name embedded
in the packaged app. After Azure identity validation, compare the actual signer
common name with this file. A mismatch must block release; never weaken the
check to accept an arbitrary trusted certificate.

## Installer behavior

`scripts/build-installer.ps1` uses pinned WiX Toolset 6.0.2 to build a per-user
MSI. If the project is used to generate revenue, the owner must review WiX's
[Open Source Maintenance Fee](https://github.com/wixtoolset/wix/releases/tag/v6.0.2)
terms.

| Operation | Defined behavior |
| --- | --- |
| Install | Installs the signed executable and notices under `%LOCALAPPDATA%\Programs\Clarify`; creates per-user Desktop and Start Menu shortcuts. |
| Upgrade | Windows Installer performs a major upgrade transaction. `%APPDATA%\Clarify` is outside the MSI and is never copied, migrated, or removed. |
| Repair | `msiexec /fa Clarify-windows-x64.msi` repairs program files and shortcuts without modifying user data. |
| Autostart | The installer does not enable autostart. The existing in-app setting owns the HKCU Run value. Upgrade preserves it; uninstall removes a stale Clarify Run value. |
| Failed upgrade | Windows Installer rolls the package transaction back. The previous installed product and all user data remain available. |
| Manual rollback | A user may run an older, still-trusted Clarify MSI. The MSI permits this explicit rollback, while the in-app update checker refuses every downgrade. |
| Uninstall | Removes installed program files, shortcuts, install metadata, and the autostart entry. Settings, usage statistics, and credentials remain in `%APPDATA%\Clarify` for recovery or reinstall. |
| Portable | The signed portable EXE and ZIP remain supported and do not participate in MSI registration. The in-app MSI updater requires the current executable path to match the MSI-owned HKCU install registration, so portable builds fail closed. Manual checksum/signature verification remains documented. |

Do not run an installer while recording or processing text. The update UI
closes Clarify after starting the visible Windows Installer flow.

## Authenticated release manifest

The update checker is available only to positively identified MSI installations
and is manual: **Settings → Check for updates**. It performs no idle polling and
no forced update. A frozen portable executable is not sufficient evidence of an
MSI installation and cannot launch `msiexec` through this flow.

1. Download `Clarify-release-manifest.cab` from the fixed
   `releases/latest/download` URL into a sibling `.part` file.
2. Require a valid Windows Authenticode chain and the publisher common name
   pinned inside the signed application.
3. Extract only `release-manifest.json` from the authenticated CAB.
4. Require the exact schema, stable channel, strict SemVer, matching `vX.Y.Z`
   tag, expected MSI name, canonical GitHub release URL, publisher, size, and
   lowercase SHA-256.
5. Refuse an older version and treat the installed version as no update.
6. Download the MSI atomically. Interruption, excess bytes, size mismatch, or
   checksum mismatch removes the `.part` file and leaves no runnable update.
7. Require a valid Authenticode signature from the same pinned publisher. The
   PowerShell inspection reports the primary signer and timestamp signer,
   thumbprint, status, and protocol. It reads the embedded PKCS#7 signer
   unauthenticated attributes with Windows CryptoAPI
   (`CryptQueryObject`/`CryptMsgGetParam`) and requires exactly one
   RFC3161 `id-aa-signatureTimeStampToken` attribute
   (`1.2.840.113549.1.9.16.2.14`). Legacy PKCS#9/Authenticode
   countersignatures (`1.2.840.113549.1.9.6` and
   `1.3.6.1.4.1.311.3.2.1`), malformed attributes, and missing tokens are
   rejected. The updater separately runs the documented Windows SignTool
   command `verify /pa /all /tw` and accepts only exit code 0, so its
   signature and TSA-chain validation is independent of the structural OID
   check; warnings (including `/tw`'s missing-timestamp warning), a missing
   tool, or any other non-zero result fail closed. SignTool stdout is never
   parsed because Microsoft does not specify a stable timestamp-table format.
8. Offer the verified version to the user. Nothing executes without an
   explicit confirmation.
9. Recheck size, checksum, signature, and publisher immediately before calling
   visible `msiexec` UI.

The manifest CAB exists only in a unique staging directory and is deleted after
signature verification, extraction, and strict parsing. The MSI is atomically
published to its versioned cache path only after size, checksum, publisher,
primary signature, and timestamp signer/certificate/status verification. Any
failure removes that attempt's staging directory without touching a previously
verified MSI. A failed launch can be retried by checking again; user
configuration is not part of the cache.
The existing GitHub release page, EXE, ZIP, and checksum path remain available
when the updater cannot reach or validate the manifest.

## CI and release gates

Pull-request CI builds an unsigned smoke-test executable and two MSI versions,
then exercises clean install, upgrade, repair, explicit rollback, uninstall,
shortcut cleanup, autostart cleanup, and `%APPDATA%` preservation on an
ephemeral Windows runner. The baseline build embeds a test-only version identity
so its executable digest differs from the current payload; every install,
upgrade, repair, and rollback transition must produce the expected SHA-256, and
uninstall must remove it. It also creates and parses the release manifest and
CAB. These automated checks do not substitute for signed-artifact or real-user
manual acceptance.

The community tag workflow is separate from the signed workflow and does not
use Azure credentials. It publishes only the portable assets described above.

`scripts/test-installer.ps1` is intentionally destructive and must never be run
on a developer workstation or a shared Clarify installation. It fails
closed unless `CI` and `GITHUB_ACTIONS` are true, the runner identifies itself
as a GitHub-hosted Windows runner, the repository matches `GITHUB_WORKSPACE`,
the profile roots have their expected hosted-runner layout, and every targeted
Clarify path and registry value is initially absent. Use only a disposable
VM for the separate manual lifecycle procedure. This script itself is restricted
to the hosted runner; do not bypass its guards.

The signed release workflow must fail unless it can:

1. run Azure OIDC login and Artifact Signing actions only from reviewed,
   immutable full commit SHAs, never mutable tags;
2. match `version.py` to the tag;
3. sign and verify the EXE before embedding it in the MSI;
4. sign and verify the MSI before hashing it into the manifest;
5. sign and verify the manifest CAB;
6. match every signer to `distribution/update-policy.json` and independently
   verify an RFC 3161 token and trusted TSA chain with Windows SignTool;
7. generate separate SHA-256 files without modifying signed bytes;
8. create GitHub build-provenance attestations for EXE, MSI, CAB, and ZIP;
9. publish portable and installer assets from that same workflow run.

Never replace a published binary in place. Fixes require a new green commit,
annotated tag, signatures, manifest, attestations, and release.

## Rotation and emergency revocation

Planned rotation:

1. Create a new public-trust certificate profile under the same verified legal
   publisher.
2. Grant the federated release identity signer access to the new profile only.
3. Update the protected profile variable and run a non-publishing workflow
   dispatch.
4. Verify all three signatures, timestamp chains, publisher common name, and
   manifest identity.
5. Remove signer access from the old profile after a successful release. Keep
   old timestamped releases immutable.

Suspected compromise or wrongful signing:

1. Disable the GitHub federated credential and remove the profile signer role.
2. Revoke/disable the affected certificate profile in Azure and preserve Azure
   signing history, GitHub logs, workflow IDs, digests, and timestamps.
3. Disable the `release-signing` environment and private-report the incident.
4. Remove the compromised release or its manifest CAB so new update checks
   fail closed. Do not silently replace assets under the same tag.
5. Publish a security advisory identifying affected versions and instruct users
   to uninstall or roll back to a named trusted release as appropriate.
6. Rotate the profile/federation, patch on a new commit, and publish a new tag
   only after full CI, signature, provenance, and manual verification.

## Manual release acceptance

Before calling the distribution path production-ready, use a clean supported
Windows 10/11 account and record evidence for:

- publisher display and `Get-AuthenticodeSignature` on EXE, MSI, and CAB;
- clean install and both shortcuts;
- launch and provider configuration;
- upgrade with settings and credentials preserved;
- repair with settings and credentials preserved;
- interrupted download and failed upgrade recovery;
- explicit rollback to the previous signed MSI;
- uninstall cleanup with user data preserved;
- portable EXE/ZIP and checksum verification;
- SmartScreen behavior for the verified publisher.

## Rollout gates

Do not close issue #22 or enable/publish the update path until all of these are
true:

- secret storage issue #14 is merged and credential preservation is tested;
- provenance/locking issues #21 and #29 are merged and integrated;
- Azure identity validation, protected environment, OIDC federation, signer
  role, profile variables, and exact legal publisher pin are configured;
- a tagged release publishes trusted signatures and attestations;
- the manual acceptance matrix above is complete with evidence.
