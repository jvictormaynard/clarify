# Internal iOS QA preflight

This workflow has separate dispatch modes for reviewed PR 179 code.
`validate` calls MAIN's reusable CI and records the exact source/base/trusted
composition. `archive` consumes that completed validation and produces an
unsigned Device Release archive without secrets. A later `sign-export-proof`
dispatch uses a new trusted runner for an experimental export. Its receipt
always has `delivery_eligible=false`. `preflight` retains the legacy read-only
checks. `upload` and `availability` use the gates below; this implementation
does not make a build available by itself.
No workflow dispatch is authorized by this local implementation.

The stable workflow and `scripts/release_delivery.py` remain unchanged. The
feature composition retains the stable workflow from MAIN. The old candidate
route is not used.

## Trust and source checks

Run `.github/workflows/ios-qa.yml` through manual maintainer dispatch on
`refs/heads/main`. The workflow checks out `github.workflow_sha` under `trusted/`.
The verifier requires that SHA to equal the workflow SHA, checkout HEAD, dispatch
SHA and current main. The initial actor and rerun actor must have `maintain` or
`admin` permission. Branch and tag dispatches cannot produce a preflight result.

For `validate`, supply `source_sha`, `base_sha` and `trusted_sha` as 40 lowercase
hexadecimal characters. Base and trusted must equal current main and
`github.workflow_sha`; source must be the current ready PR HEAD and contain that
base. Validation reads app identity and the null relay configuration as data.
It does not select or reserve a version/build or require a publication tag.
The fresh job's GitHub runtime and dispatch event inputs are authoritative.
The legacy `candidate` input is unused in this mode.

For `preflight`, candidate metadata is a JSON input, with exact fields and duplicate-field
rejection. It is never imported or executed. The verifier reads source files as
data through the GitHub API. Models, prompts, endpoints, commands, helper paths,
arbitrary repositories and artifact paths are not accepted inputs.

The candidate must be the current HEAD of the canonical repository's open,
ready, unmerged and conflict-free PR 179. It must contain exact current main.
Its PR CI must identify that HEAD and that base. Main must also have successful
CI for its exact SHA, from a main push or a manual full validation on main.
Both need mobile checks and all mandatory native steps. Other source
checks come from the main checkout's component policy. Missing, failed, skipped,
cancelled, timed-out and unknown required results block the decision. PR edits
to workflow/action files or CI policy also block it. A base change requires
recomposition and new CI; an old green run cannot authorize the new composition.

## Candidate data and reservation

The exact top-level fields are:

| Field | Required value |
| --- | --- |
| `schema` | Integer `1` |
| `pr` | Integer `179` |
| `source_sha` | Exact 40-character current PR HEAD |
| `base_sha` | Exact 40-character current main and trusted workflow SHA |
| `app_id` | Existing application `6820869157` |
| `bundle_id` | `com.jvictormaynard.clarify` |
| `version` | Stable `X.Y.Z`, equal to the candidate app configuration |
| `build` | Decimal string, equal to the candidate app configuration |
| `tag` | Existing `ios/pr-179/vX.Y.Z-buildN`, resolving to exact source |
| `relay_host` | JSON `null` |
| `reservation` | Object with the four fields below |

The exact reservation fields are `highest_build`, `pending_builds_checked`,
`checked_at` and `report_url`. `highest_build` is a positive decimal string below
`build` for a new upload; `pending_builds_checked` must be `true`. A confirmed
upload from the same source can use current evidence that already includes its
build, because availability recovery does not reserve or upload it again.
The UTC timestamp must use
`YYYY-MM-DDTHH:MM:SSZ` and be at most 24 hours old, with no future time. The report
must link to a canonical issue, PR or Actions run. The outer metadata binds that
report to one app/version/build, source and current base.

The Apple coordinator must inspect existing builds, pending uploads and all
reservations before supplying this attestation. This preflight does not query
Apple and cannot independently prove that the attestation is complete. It
does not reserve an identity, increment a build, create metadata files or write
tags. No next version or build is selected by this change.

## Upload history and recovery

The concurrency group is `clarify-ios-testflight`, shared with stable delivery,
with `cancel-in-progress: false`. The history check reads repository-wide runs
across SHAs, refs, events and attempts, including earlier attempts of the current
run. It does not filter history by the candidate SHA or by the current names of
Apple workflows. Only a completed skipped
upload job or an explicitly skipped upload step establishes no upload. Missing
jobs, missing steps and ambiguous attempts block the decision, even when their
declared identity differs. A confirmed upload for another SHA cannot reuse this
candidate's app/version/build.

A stable result, including a skipped upload, is interpreted only when its
workflow and all fixed signing, verification, availability and release helpers
match the trusted implementation. An older push uploader with a different
implementation blocks the decision and requires an Apple-side audit.

A confirmed same-source upload produces `availability-required`. This result
does not build, upload or run an availability helper. Availability requires a
separate operator decision. A previous QA implementation that differs from this
trusted preflight has no accepted receipt reader and blocks the decision.
An unknown workflow path, including one with no iOS name, also blocks it.
Other workflows need an explicit non-Apple classification in trusted main.
Their historical definitions and local reusable workflows/actions must match
trusted main before they can be classified as having no Apple upload. A keyword
search of a current file does not establish its earlier behavior.

GitHub pagination and attempt limits fail closed. Deleted or expired history
cannot be reconstructed by this gate. The trusted reconciliation contract for
missing history and different legacy implementations is still open; an Apple
audit report alone is not yet an accepted bypass. Preflight results must not
authorize an upload until that contract exists. Workflow history is not an
Apple reservation ledger or proof of IPA source.

## Packaging blocker

The published stable interfaces do not provide the required separate-source
contract:

- `mobile/scripts/verify-ios-ipa.py` reads `app.json` and a license relative to
  its working directory. It checks signatures, app and extension identities and
  an IPA hash, but its receipt does not bind the IPA to an exact source SHA.
- `mobile/scripts/publish-testflight.cjs` reads `app.json` and `eas.json` beside
  its own script. It also writes fixed stable release notes. Calling it from
  trusted main would select main's identity. Calling the candidate's copy would
  execute candidate code with Apple credentials.
- `mobile/scripts/ios-signing.rb` updates the generated project relative to its
  working directory. A signed archive can execute candidate Xcode build phases
  while the signing keychain is unlocked. A separate path alone does not isolate
  those phases from signing material.

Apple delivery remains blocked until the coordinators approve and validate the
archive, pre-key signing and history reconciliation contracts. A future implementation needs an immutable candidate checkout
outside `trusted/`, isolated packaging, a trusted signing boundary, the existing
signature and bundle checks, and a sanitized receipt that binds the exact IPA
hash, app plus both extensions, version/build, candidate SHA and trusted SHA.
Reject unexpected paths. All orchestration, signing, verification, upload and
availability code must execute from immutable trusted main paths.

The local helper proposal adds `--qa-context` to the IPA verifier and internal
availability helper. The flag selects a strict, fixed-path context. Without the
flag, the proposal preserves stable success output and failure messages. In QA,
the Python verifier returns a fixed failure message and exit code 1; archive
entry names and malformed plist values are not printed in tracebacks. Strict
argument checks apply only in QA. Without the flag, Python keeps the original
configuration-before-IPA order and ignores extra arguments; Node also ignores
extra arguments. Its
receipts keep `workflowArtifactProvenanceVerified=false`: matching declared
hashes does not prove that an artifact was built from the declared source.
The helper proposal still requires independent review and native acceptance.

## Trusted validation contract

The coordinator approved model A for the internal PR179 preview:
`trust_model="reviewed-source-internal-qa-v1"`. The source must be reviewed code
from this repository. MAIN defines policy, recipes and required controls.
The receipt records authenticated metadata, hashes and observed execution
results. It does not attest assertions independently of deliberately hostile
product code in the same process. Checkouts, user IDs and pre/post hashes must
not be described as providing that property.

This scope decision permits implementation and review. It does not authorize
CI dispatch, publication, a PR179 merge, build-number reservation or installation.
It preserves every credential, archive, signing, history and native gate.

The CI owner and QA owner agreed on a separate trusted validation path and its
control inventory. This local preparation connects the reviewed adapter to the
MAIN caller, final verifier and artifact consumer. Integration into trusted MAIN
and the focused final review remain separate. This channel has not been observed
end to end. No API probe or CI dispatch was performed for this delta. The export
proof has no upload or availability authority.

The caller is `.github/workflows/ios-qa.yml`, with job ID `validation` and name
`Trusted validation`. The separate final job has ID `finalize_validation` and
name `Finalize trusted validation`. Only this final job may produce
`validation.json` in `clarify-qa-validation-${run_id}-${run_attempt}`. The caller's
workflow ID, path and blob identify the workflow in the manifest. The reusable
CI workflow is a separate authenticated control.

The adapter accepts `source_sha`, `base_sha`, `trusted_sha` and `trusted_qa`.
The three SHAs use 40 lowercase hexadecimal characters. QA requires the complete
tuple, an authenticated main origin, observed source/tree bindings, mobile and
native tests, unsigned compilation and disabled caches. Calls without QA inputs
retain the normal validation recipes.

The fixed check-key universe is:

```text
selection, repository, python_linux, python_windows, settings,
package_windows, installer_windows, server, mobile, ios_native,
ios_build, ios_aggregate, audit_python_linux, audit_python_windows,
audit_settings, ci_required
```

The final job must recompute the exact selected set from authenticated trusted
policy, including QA minimums and `selection`, `repository` and `ci_required`,
before interpreting a skipped result. The manifest contains that selected set
only. An unselected executor has no fabricated execution record. A selected job
that is absent, failed, skipped, cancelled, timed out or unknown blocks success.
The adapter's `CHECKS` constant supplies the agreed fixed job names and required
step names from the trusted checkout.

The validation manifest must bind repository/PR, source SHA/tree, base SHA/tree,
trusted SHA, caller workflow ID/path/blob, run/attempt and each actual required
job/step result. Schema 1 requires the exact `trust_model` value above. A missing
or different value blocks consumption. The final job uses trusted policy and GitHub API evidence;
candidate reports cannot approve a check. A dispatch run whose API `head_sha`
is main is expected. Its source inputs, checkout bindings and executor facts
must also match the candidate. A source or base change requires new validation.

The manifest builder accepts only the agreed plan shape, exact boolean
component flags, native minimums, canonical selected keys and Git blob IDs for
controls. It records successful selected jobs and their required ordered steps
from the exact-attempt API response. It omits unselected execution records and
any claim that the final job has already succeeded. The caller must still
authenticate the run, workflow, checkout and API response. This builder and the
artifact-record codec have no publication authority.

The caller authenticates the maintainer, current MAIN, ready PR, source identity
and Git objects before starting `Trusted validation`. It calls the local
`ci.yml` with `trusted_qa: true` and all three SHAs. The final uses a new Ubuntu
runner and checks out only `github.workflow_sha`. Source objects remain Git data
for MAIN's `build_plan`; no candidate checkout, imports, dependencies, plugins,
build phases, logs or reports execute in that final runner. MAIN's tracked control
files must match their trusted Git blobs. The verifier authenticates the observed
`referenced_workflows` graph against the approved local reusable paths and trusted
SHA before interpreting omitted or skipped jobs. Candidate CI files do not need
byte equality with MAIN because that code does not control this execution.

The final recalculates `CHECKS`, selected keys, source/base trees and both digests.
It compares the reusable outputs with those local results and builds the manifest
from exact-attempt API jobs and steps. Missing, duplicate, reordered or unsuccessful
required steps block it. It does not download candidate logs or artifacts.
Canonical JSON uses ASCII escaping, sorted keys, separators `(',', ':')`,
`allow_nan=False` and UTF-8 bytes without a trailing newline.

The artifact cannot declare its own final job successful before that job ends.
A later consumer must authenticate the artifact producer and require API
success for the exact final job, run and attempt. `validation.json` is separate
from the post-sign `context.json` and from Apple upload/availability receipts.

The final uploads once, with a pinned action and `overwrite:false`, in the step
`Upload trusted validation manifest`. The following step is named
`Record trusted validation artifact`. It reads only the upload action outputs
and emits one line with prefix `CLARIFY_QA_VALIDATION_ARTIFACT ` and an object
whose exact keys are `artifact_id`, `artifact_name`, `artifact_digest`, `run_id`
and `run_attempt`. The digest uses `sha256:` followed by 64 lowercase hex digits;
the emitter checks the upload output before converting it to this form.

The transport is MAIN's literal `trusted-final-job-log-v1`. The consumer finds
exactly one job named `Finalize trusted validation` through
`/actions/runs/{run_id}/attempts/{attempt}/jobs`. It requires the exact run/attempt,
trusted head SHA, completed/successful run and final job. The unique upload and
record steps must both be completed/successful, in that order. `step.number`
provides identity and order only. There is no step endpoint or index conversion.

The consumer downloads only `/actions/jobs/{job_id}/logs` for that authenticated
final job. It decodes strict UTF-8, with a total 1 MiB limit and no truncation,
ANSI normalization or expansion. Only the codec's documented leading UTC timestamp
is removed. It requires exactly one record prefix. Missing, duplicate, malformed,
masked, unavailable or ambiguous log data blocks consumption. There is no fallback.

The consumer cross-checks all five record fields with the artifact API, including
the trusted `workflow_run.head_sha`, name, ID, digest and `expired:false`. It
requires the downloaded ZIP's SHA-256 to match. The ZIP must contain exactly one
regular `validation.json`, smaller than 256 KiB, with no links, escapes, duplicate
entries, extra entries, encryption or compression bomb. It then compares canonical
manifest bytes with independently recomputed MAIN policy and API observations.

Jobs API step metadata does not supply upload outputs, and artifact metadata
alone does not identify the producing job. The trusted upload/record recipe and
observed upload outputs supply that link after upload. Only the MAIN recorder
emits the record prefix; the shell command does not echo it. The record receives
only the pinned uploader's ID/digest outputs, not `needs` data or a candidate
report. The manifest does not claim the final job has already succeeded. Binary
downloads allow at most three HTTPS redirects, forward no redirect credentials
and print no signed URLs. A 404 or any unavailable response blocks consumption.

Candidate execution, dependencies, plugins, tests, builds and unsigned archive
creation run without signing or provider secrets. Signing/export/verification
and publication use a new trusted runner. Before installing keys, that runner
must validate the archive and producer, source/base/version/build, three bundles,
hashes, normalized paths, links and size limits. It executes no candidate code,
dependency install, plugin or build phase after keys enter. Observed consistency
under model A does not replace this boundary or global history reconciliation.

The CI owner closes the executor control inventory; root closes caller, final,
verifier and helper inputs. Their agreed union has 260 destinations. Its observed
base blobs are reference data. Runtime authority requires the actual blobs from
the approved immutable `trusted_sha`. Unknown inputs, links, escapes, collisions
and native inputs without reconciliation block materialization. The agreed
scope permits eight initial hunks and only the necessary opt-in changes from
the fourteen potential paths; existing interfaces can be reused.

The native recipe uses 24 contract sources and 30 UIKit fixture outputs. Seven
literal command-call adaptations apply only to copies of two MAIN test files.
Each has an exact content, function and occurrence guard. Reversing all seven
must reproduce the original bytes. Canonical tests, assertions, guards and
timeouts remain unchanged.

Immediately before any future upload, repeat the exact PR/main/tag, reservation,
CI and cross-workflow history checks. A successful preflight is not a reusable
upload authorization. Availability must target only the existing `Clarify
Interno` internal group. App Store submission, external beta, tester invitations,
provider deployment and hosting changes are outside this workflow.

Empty history blocks preflight and requires audited reconciliation. Nonempty
history alone does not establish completeness or account for deleted runs.
The durable global reconciliation contract remains open; the local empty-history
guard does not close that gate.

## Device archive dispatch

The adapter's `ios_build` check compiles Debug for `generic/platform=iOS Simulator`
with signing disabled. It remains unchanged. The separate `archive` job, named
`Unsigned Device Release archive`, produces the Device Release archive without
signing credentials, provider secrets or App Store Connect API keys.

For `archive`, supply the three exact composition SHAs plus `validation_run_id`
and `validation_run_attempt`. Supply `candidate` with exactly the identity fields
in the table above except `reservation`. The tag must already resolve to the
exact current source. The version and build must match that source's `app.json`.
The Apple coordinator owns the reservation and tag. This mode does not select,
increment or reserve an identity, edit `app.json`, require old publication CI,
or interpret upload history. It consumes the authenticated current-composition
validation manifest and its exact-attempt API results instead.

The producer uses MAIN's existing `trusted_ci.Job`, component `ios_build`, for
authentication, source/MAIN materialization, mobile dependencies, trusted Expo
prebuild and Pods. It runs a separate fixed `xcodebuild archive` command with
Release, `iphoneos`, `generic/platform=iOS`, `ARCHS=arm64` and
`CODE_SIGNING_ALLOWED=NO`. Source and control checks run after execution, including
failure. Candidate stdout stays in inert log files and never enters the Actions
command channel. `pack` runs only after both post-execution checks pass.

Each archive-related runner uses MAIN's fixed
`DEVELOPER_DIR=/Applications/Xcode_26.6.app/Contents/Developer`. Before key
installation, it observes `/usr/bin/xcodebuild -version`, including `Build version`,
and `/usr/bin/xcrun --sdk iphoneos --show-sdk-version`. The policy uses those
observations. It does not invent an Xcode build or SDK version.

The transport contains `unsigned.xcarchive.zip` and `archive-envelope.json` inside
the GitHub artifact `clarify-ios-qa-unsigned-<source_sha>`. Preserve the archive's metadata,
single app, two extensions, frameworks, resources and produced dSYMs. Do not
reconstruct an archive from selected files or invent signing metadata.

The data policy rejects links and special nodes. Its limits are
50,000 entries, 512 MiB per file, 2 GiB total expanded size and ZIP size, depth
32 and 1,024 UTF-8 bytes per path. Reject path changes, Unicode/case collisions,
file/directory conflicts and encrypted entries. These limits still need a real
archive compatibility check. No candidate project, workspace, Pods or build
scripts belong in the signing runner's execution path.

The `archive-envelope.json` binds the source/base/trusted composition,
workflow and producer run/attempt, controls, fixed Release/iphoneos recipe,
archive hash and canonical file-manifest hash, three bundle bindings and the
MAIN entitlement-policy hash. It is data to compare with trusted policy and
API facts. It cannot authorize itself. The artifact's external digest, inner
archive hash and final IPA hash are separate values.

The pre-key inspector must distinguish ARM64 iOS device binaries from ARM64
Simulator and Catalyst binaries. An unsigned executable does not prove signed
entitlements. Record absent embedded entitlements as `null`; keep the intended
MAIN signing policy separate and inspect the effective entitlements in the
signed IPA. Do not copy the profile's full entitlement dictionary into the app.

The archive inspector checks a bounded thin ARM64 primary executable and
one device-iOS `LC_BUILD_VERSION` declaration. It rejects Simulator, Catalyst,
legacy or conflicting platform metadata, a signature command and malformed
load-command sizes. The constants follow Apple's
[`mach-o/loader.h`](https://github.com/apple-oss-distributions/xnu/blob/main/EXTERNAL_HEADERS/mach-o/loader.h).
The archive module also checks the complete file manifest, bundle identities,
frameworks, resources and dSYMs. These checks establish data consistency under
model A. They do not prove native export compatibility or workflow provenance.

The producer uploads once with the pinned artifact action and `overwrite:false`.
It passes only the uploader ID/digest through `needs` to a separate MAIN-only
runner, `Finalize trusted Device archive`. That runner repeats current-composition
authentication and checks the exact producer run/attempt, successful producer
steps and API artifact ID/name/digest/size/trusted head. It does not download or
execute the archive. Only then does it emit one five-field record with prefix
`CLARIFY_QA_ARCHIVE_ARTIFACT `. Its fields are `artifact_id`, `artifact_name`,
`artifact_digest`, `run_id` and `run_attempt`.

## Experimental export proof

Run `sign-export-proof` only in a later dispatch after the entire archive run has
completed successfully. Reuse the exact candidate/composition/validation inputs
and supply `producer_run_id`, `producer_run_attempt` and `archive_artifact_id`.
The current run cannot be its own producer. Recompute the expected policy from
current MAIN and current ready PR data. A changed source or MAIN requires new
validation and a new archive.

`ArchiveGitHub` implements the archive module's `ArchiveAPI`. It binds MAIN
commit/tree observations to the trusted checkout, resolves raw Git blob bytes
and caches them by trusted SHA/path. The archive inventory includes the actual
MAIN adapter, caller, archive module, release and signing helpers, transitive
controls, dependency manifests/locks and npm configuration. Claimed hashes or
payload flags cannot replace those bytes. API JSON and pagination are bounded.
Artifact downloads stream to a new file with a 2 GiB limit. Redirects require
HTTPS and receive no token after the first request.

The trusted workflow YAML is parsed with Node 22 and the `yaml` package from
MAIN's `desktop/package-lock.json`. `npm ci --ignore-scripts` runs in
`trusted/desktop` before credential installation. The parser rejects duplicate
keys, tags, aliases, anchors, multiple documents and oversized/deep data. It
receives no signing secrets in its subprocess environment.

The consumer uses only `trusted-final-job-log-v1`. It authenticates the whole
successful producer run, distinct successful producer/final jobs and required
steps, then reads only the trusted final job log. Missing, duplicate or ambiguous
records block it. It cross-checks the five fields against the API and downloaded
outer ZIP digest. There is no step endpoint, probe, candidate log or fallback.

The caller invokes the existing `qa_device_archive.sign_export`. That function
authenticates, downloads, inspects and freezes the complete archive before it
calls MAIN's unchanged `ios-signing.py install`. It then tries only the fixed
`xcodebuild -exportArchive` route. Cleanup runs after partial installation,
export failure and success. The signer executes no candidate checkout, project,
dependency, plugin, Pods or build phase. It receives only the existing certificate
and three-profile secret variables. It receives no App Store Connect API key.

The caller retains only `archive-receipt.json` as an Actions artifact and removes
the private successful workspace, including its IPA. The receipt remains
experimental, with `delivery_eligible=false` and
`workflowArtifactProvenanceVerified=false`. No IPA is uploaded to Apple.

The signing/export route remains unvalidated. Apple documents local
[`xcodebuild -exportArchive`](https://developer.apple.com/library/archive/technotes/tn2339/_index.html),
but that documentation does not establish export of this wholly unsigned
archive. Apple also states that CLI re-signing is unsupported on iOS in its
[signature-format guide](https://developer.apple.com/documentation/xcode/using-the-latest-code-signature-format).
That warning does not establish whether initial signing/export of this archive
will work. Manual `codesign --sign` and re-signing fallbacks are not permitted.

No fallback may rebuild the candidate after keys are installed, run its build
phases, obtain new credentials, use `allowProvisioningUpdates` or change archive
metadata to force export.

## Internal preview publication

The publication route is restricted to PR 179, version `0.12.0` build `41`.
After the native proof run succeeds, `upload` requires the same source, base,
trusted MAIN, immutable tag, validation run and unsigned archive. Supply
`proof_run_id`, `proof_run_attempt` and `proof_artifact_id`. The proof job records
its receipt artifact through the existing trusted job-log channel. Its receipt
binds the tuple and records observed export; its two provenance/eligibility
flags remain false.

Also supply `inventory_run_id` and `inventory_run_attempt` for a fresh complete
GET-only Apple report from the audited control. The gate authenticates that
producer and the preserved baseline, then reconciles repository runs after the
baseline. Unknown implementations, missing history, another active publisher or
an upload without an authenticated receipt block publication. The baseline is
a limited build-41 reservation audit; it does not assert that deleted historical
uploads have independent provenance.

A fresh MAIN-only runner authenticates the gates, inspects the archive before
keys, exports, and runs the unchanged IPA verifier with `--qa-context`. It checks
the gates again immediately before one `altool` call. A local receipt is created
exclusively before that call. An existing receipt prevents another call;
failure, cancellation or an unknown outcome never authorizes a resend. The
workflow retains context, verification and upload receipts, without the IPA or
credentials, then removes private staging. Authentication failure before this
receipt remains a blocked operation.

Use the separate `availability` mode with `publication_run_id`,
`publication_run_attempt` and `publication_artifact_id`. It authenticates the
original MAIN job, recorder, artifact and context, then calls the unchanged R6
helper for the exact identity and existing `Clarify Interno` group. It can recover
confirmed or uncertain uploads. It never signs, exports or uploads an IPA.
There are no invitations, external beta or App Store submission operations.

The Apple coordinator owns dispatch, the final fresh Apple read and delivery.
Native export, upload, processing and group availability still need actual
execution. Neither the hashes nor these receipts provide independent assertion
attestation under model A.

## Cost and validation limits

The candidate's `shared/computer_connect.json` must retain a null relay host.
There is no new monthly relay cost, selected free-quota service or provisioned
infrastructure. WAN access and end-to-end remote availability are not delivered.

Run the focused fake-API tests with:

```powershell
python -m unittest discover -s tests -p test_testflight_qa.py -v
```

Also run `tests/test_qa_device_archive.py` for archive inspection, pre-key failure,
freeze, fixed export and cleanup with temporary fixtures and command stubs.
The glue tests check runtime modes, exact producer/validation identities,
recorder/API cross-checks, bounded transport and strict YAML parsing.
These tests prove local decisions and effect boundaries with synthetic data.
They do not prove Apple API state, a native archive, signing, an IPA,
upload, internal-group availability or physical-device behavior. This change was
prepared on Windows without an Apple toolchain. Those native gates remain open.
