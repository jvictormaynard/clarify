# Client release automation

Code changes on `main` run validation. They do not request a client release.
Desktop publication and TestFlight upload require a separate release-preparation
PR, a maintainer review and merge, and successful CI for that exact merge commit.
A maintainer can review and merge their own preparation PR. The repository does
not require a second person's approval.

## Activation

Promotion is disabled unless the repository variable
`CLARIFY_RELEASE_PROMOTION_ENABLED` is exactly `true`. An unset or false value
leaves the promotion job inactive. Installing these workflows does not select a
version, create a release intent, or publish a client.

Preparation requires the repository secret `CLARIFY_RELEASE_PREPARATION_TOKEN`.
Use a GitHub App installation token or fine-grained token restricted to
`jvictormaynard/clarify`, with Contents and Pull requests write access and Metadata
read access. The token must be able to create a branch and PR whose events start
normal CI. Preparation fails before writes when the token is absent. There is no
fallback to `GITHUB_TOKEN`. Keep this token out of dispatch inputs and reports.
A GitHub App installation token must be refreshed before use; this workflow does
not create or refresh installation tokens.

The promotion workflow uses `GITHUB_TOKEN` with Contents and Actions write access
and Pull requests read access. Repository Actions policy and tag rules must allow
this token to create the release tags and dispatch workflows. Restrict release
tag changes and deletion to the release maintainer. The scripts never move tags.
Desktop publication still uses the protected `portable-updates` environment and
its existing `CLARIFY_UPDATE_SIGNING_KEY`. Environment policy must permit the
reviewed `v*` tags. The key must match the packaged Ed25519 public key.

Before reusing `codex/ios-testflight`, bring its workflow forward to this guarded
version through an authorized Git change. Its older remote workflow can still
upload on branch pushes: GitHub evaluates a push workflow from the pushed ref,
so changing only main does not disable that old branch workflow. Do not push
mobile source there until it has the guarded workflow.

The TestFlight workflow keeps its existing Apple signing and App Store Connect
secrets. All signed upload, Apple processing and internal-group availability
work stays in the serialized `clarify-ios-testflight` workflow group. App Store
submission and public distribution require a separate decision and procedure.
The signed desktop `release.yml` remains blocked and manual-only.

## Prepare a desktop release

1. Complete the intended code changes through ordinary PRs. Wait for main CI.
2. Build and test Windows from the exact current main SHA. Record the executable
   hash, tested source SHA and applicable manual acceptance results in a canonical
   GitHub issue, PR comment or Actions report. Passing CI alone is insufficient.
3. Open **Actions → Release Preparation → Run workflow** on `main`. Select
   `desktop`, enter a future stable `X.Y.Z`, leave `build` empty, and describe the
   scope and validation limits in `notes`. Supply this `evidence` JSON, replacing
   every placeholder with actual evidence:

   ```json
   {
     "tested_sha": "<40-character current main SHA>",
     "windows_accepted": true,
     "report_url": "https://github.com/jvictormaynard/clarify/issues/123#issuecomment-456"
   }
   ```

4. Review the draft PR on `release-preparation/vX.Y.Z`. It changes only
   `version.py`, root `package.json`, `CHANGELOG.md` and
   `.github/release-intent.json`. Preparation moves the current Unreleased entries
   into the new dated changelog section and updates comparison links. Check these
   entries and release notes before marking the PR ready.
5. Run the existing release preflight and applicable local checks. Complete PR
   checks. Review the intent and acceptance evidence, then merge. This merge is
   the maintainer's publication authorization when promotion is enabled.

No source change can occur between the accepted base and release merge except
these release metadata files. If main advances with other changes, repeat the
acceptance or preparation work as applicable. Do not edit the evidence to refer
to source that was not tested.

### Public desktop release notes

Community Release reads the version's dated `CHANGELOG.md` section from the
release tag. It publishes these changes first, followed by a link to the tagged
changelog and the Windows portable distribution notices. Missing, duplicate,
undated or empty sections stop publication before the build. Review this section in the
release-preparation PR; the intent's `notes` field records scope and validation
for the maintainer and does not replace the public changelog section.

To inspect the generated text without publishing:

```bash
python scripts/release_delivery.py notes --tag vX.Y.Z --output release-notes.md
```

Run this command in a checkout that has the release tag. It reads the tagged
file even when the working changelog contains later changes. For an existing
release with only distribution notices, add its own tagged changelog section
and keep its original notices. Change the description only; preserve the tag
and published assets.

## Prepare a TestFlight build

Before selecting a build number, inspect App Store Connect for this app's
existing builds, processing uploads, pending submissions and other reservations.
The existing `status_only` mode helps read Apple state; its recent-build list is
not a complete reservation check. Record the complete check in a canonical
GitHub report. Choose an unused build greater than both the highest reservation
and the checked-in build. There is no automatic increment or Apple reservation
API call in preparation.

Run **Release Preparation** on `main`, select `mobile`, and supply a stable
`version`, the selected decimal `build`, release `notes`, and evidence in this
form:

```json
{
  "build": "<selected unused build>",
  "highest_build": "<highest existing or reserved build>",
  "pending_builds_checked": true,
  "checked_at": "<UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format>",
  "report_url": "https://github.com/jvictormaynard/clarify/issues/123#issuecomment-456"
}
```

The check must be at most 24 hours old at preparation. The build input must match
the evidence. Keep the chosen build reserved while the PR is open; if Apple state
or another reservation changes, check it again before merge. Preparation does
not query Apple or prove that a number remains free. Reviewers must verify the
linked reservation evidence and pending state before authorizing upload.

The draft branch is `release-preparation/ios/vX.Y.Z-buildN`. It changes only
`mobile/app.json` and `.github/release-intent.json`. The mobile version can stay
the same; its build must increase. App and extension versions still derive from
the same Expo configuration and must pass signed IPA verification.

After review, green PR CI and merge, successful main CI permits promotion to an
immutable `ios/vX.Y.Z-buildN` tag. Promotion explicitly dispatches the existing
iOS workflow on that tag, with the exact source SHA and `tests_only=false`.
Main pushes do not upload. The guarded delivery-branch workflow also has no push
upload trigger; the older remote branch needs the update described above.
Manual tests-only, opening
height diagnostic, status and availability modes remain available. A signed
manual upload must also use a reviewed mobile tag and its exact source SHA.
The `codex/ios-testflight` branch can still be selected for manual validation
and status work. Do not use a mutable branch for signed upload.

## Intent and promotion checks

`scripts/release_delivery.py` validates the declarative JSON intent. Its exact
fields are `schema` (integer `1`), `component`, `version`, `base_sha`, `notes` and
`evidence`. Unknown or duplicate fields fail. Each component has the exact
required evidence fields shown above. Version prefixes, prerelease versions,
leading zeros, invalid builds, foreign report URLs and metadata drift fail.
Do not add an intent for the current versions merely to install automation.

`Release Promotion` is a separate `workflow_run` workflow. It reads GitHub API
state, without downloading PR or CI artifacts. It requires:

- the canonical `jvictormaynard/clarify` repository and a successful completed
  `push` CI run on `main`;
- workflow name `CI`, exact path `.github/workflows/ci.yml`, the event's exact
  source SHA and freshness against main, checked again before tag creation;
- one dedicated merged preparation PR tied to that exact commit, a canonical
  source branch, its expected title and a maintainer merge;
- metadata-only changes from the accepted base, matching packaged versions and
  the component's release evidence;
- successful `CI required` for either platform; desktop additionally requires
  `Tests (ubuntu-latest)`, `Tests (windows-latest)` and
  `Package Windows executable`; mobile requires `Mobile checks` and
  `iOS validation / Native tests and unsigned build`, without Desktop jobs.

An ordinary code or documentation merge with an old intent is inactive. An
existing tag must resolve to the exact source. A completed desktop release is
left unchanged; an incomplete release fails for operator inspection. An existing
publication run prevents another automatic dispatch. No release asset is replaced.

Desktop promotion and publication reject a version when an equal or newer stable
desktop release is already published. Recovery of an older accepted tag is still
possible after main advances if no published version supersedes it. Community
Release serializes all versions and uses GitHub's `queue: max` to retain up to
100 pending runs. TestFlight uses the same queue setting in its serialized group.
An overflow run is cancelled and requires inspection before a manual retry.
See GitHub's [concurrency rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

The publication workflows repeat source, tag, PR and CI checks before using
release credentials. Desktop build, signed Ed25519 metadata and provenance use
the same immutable SHA. Later main commits cannot change the selected source.
Verify downloaded assets, hashes, signatures and attestations after publication
under the [desktop contract](../.agents/skills/clarify-release/references/release-contract.md).
For iOS, verify the IPA, upload, Apple processing and intended internal group's
availability separately. A successful upload does not establish availability.

## Recovery and GitHub events

A tag created with `GITHUB_TOKEN` does not start a tag-push workflow. Promotion
therefore calls `workflow_dispatch` on the exact tag. Human-pushed desktop tags
use the same gated Community Release workflow and concurrency group. Preparation
uses the separate token because `GITHUB_TOKEN` PR events can be suppressed or
require a maintainer to approve their CI runs. See GitHub's
[workflow triggering rules](https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/triggering-a-workflow).

If dispatch fails after tag creation, rerun promotion while its source is still
current main, or manually dispatch the publication workflow on that existing tag
with its exact SHA. Never recreate or move the tag. Existing publication runs are
not automatically retried. Inspect and rerun the original failed run. After an
iOS upload succeeds, use `status_only` or `availability_only` with the original
source; do not repeat the upload to repair Apple processing or group availability.
An earlier successful iOS publication run makes a duplicate tag dispatch inactive.
The gate also reads earlier attempts of the same run. A confirmed successful
upload resumes only Apple processing and group availability. A failed, cancelled
or unknown upload result is ambiguous and blocks another upload; inspect Apple
and use `status_only` or `availability_only` to finish the existing build. This
check runs again inside the upload job because GitHub can rerun a failed job
without repeating its successful prerequisite gate.
A completed dispatch whose gate failed can be replaced when the upload job was
skipped in every attempt. Missing or uncertain job history still blocks another
upload. A skipped signing gate proves that a tests-only, status or availability
run cannot upload, even while that run is active. Earlier attempts must also
prove that they did not upload. The check includes every other run, including a
newer run that completed before an older run was retried. A first attempt still queued behind the active
serialized workflow cannot have uploaded; a queued retry can have upload history
and still blocks another upload. Promotion uses a separate concurrency group for
each source SHA, so an older CI completion cannot replace the current source's
pending promotion.
