# Server delivery on Railway

The native server delivery path connects Railway to the GitHub repository's
`main` branch and builds with `server/Dockerfile`. GitHub Actions validates the
source. With Wait for CI enabled, Railway waits for the workflow results before
building and deploying. This path needs no Railway token in GitHub Actions and
publishes no container image from CI.

## Current state and activation gates

The read-only inspection on 2026-10-25 found this service:

| Resource | Name | ID |
| --- | --- | --- |
| Project | Clarify | `017a60f3-4ca9-45c5-9cb2-8cab27c68b1d` |
| Environment | production | `4115c073-07cd-4314-a014-aaf420abf149` |
| Service | clarify-api | `310906a4-a88b-4b9e-9867-55b9294755ed` |

The merge preflight on the same date found source repository
`jvictormaynard/clarify`, branch `codex/release-v0.11.0`, with source `commitSha`
`9c2cbf4f9f543bd9cd02dbe730686837387bfbc0`. The configured builder is
`DOCKERFILE`, the Dockerfile path is `server/Dockerfile`, and the deployment
probe is `/health` with a 60-second timeout and port 8080. There are no staged
changes. Preserve that source until activation of the main-based flow is
authorized. The source connection alone does not prove that autodeploy is enabled.

An earlier inspection found branch `main`, source
`b0e095f0336e74779d5004f4b88016df1bfe2121` and
`config.source.checkSuites=false`. The latest serialized config does not expose
`checkSuites`. Neither observation confirms that Wait for CI is enabled now.
Verify that setting and the separate autodeploy control before activation.

The latest deployment with status `SUCCESS` is
`1317f2e5-037d-4bf6-bcde-907eea9b8943`, created at
`2026-10-25T08:12:42.513Z`. This record does not prove that current `main` has
passed CI or is deployed. No live setting changes are part of this source change.

Before activation:

- Merge and verify the CI wiring on `main`. The CI workflow must run on
  `push` to `main` and call `server-validation.yml` when the component
  classifier reports a server change. Server validation must also run for PRs.
- Confirm that Wait for CI is enabled in the service settings. Read back
  `config.source.checkSuites=true`, or verify the control directly if the API
  omits it. This remains an open gate until confirmed. Confirm the separate
  autodeploy control as well.
- Check desktop and iOS compatibility with the usage response from PR #158,
  including `schema_version: 2`, percentage quotas, and reset dates. Record the
  supported client versions and upgrade plan before changing the live server.
- Rehearse the first funding migrations on an isolated database. Review
  `0004_weekly_funding` through `0006_funding_cost_review`, including preservation
  of historical costs and commitments. Include `0004_social_attempt` and
  `0007_merge_weekly_funding_social_auth` from the current migration graph.
  Check the [social authentication configuration](../server/SOCIAL_AUTH.md)
  before enabling those providers. Confirm a restorable backup and the
  compatibility of both old and new code with the resulting schema.
- Approve the first funding rollout under the
  [funding operations procedure](finances.md#record-confirmed-funds-and-costs).
  Record actual receipts and operating costs before confirming distribution.
  A migration, a monthly spending cap, or a green build does not fund a quota.
- Complete the staging acceptance and backup/restore gates in the
  [server guide](../server/README.md#release-gates). Passing CI does not establish
  manual Windows acceptance, live email delivery, or device acceptance.

## CI contract

[`server-validation.yml`](../.github/workflows/server-validation.yml) is a
reusable workflow with no inputs or secrets. Its default checkout uses the
caller's triggering source: the PR test commit for PR CI and the pushed commit
for `main` CI. It does not check out a fixed recovery commit or the latest
branch tip during a run.

The workflow installs Python 3.12 and the hashed `server/requirements.txt`,
checks for missing migrations, runs server tests against disposable PostgreSQL
16, and checks shared prompt synchronization. It builds the repository's
Dockerfile from that checkout, then starts the image against the isolated
database. The smoke check requires a successful `/health` response with
`status: ok` and no pending migrations. `/health` executes `SELECT 1` against
the database. Test providers, email, and audio remain isolated from production.

The `CI` workflow owns the final result. For pushes to `main`, its concurrency
group includes the unique `github.run_id` and uses `cancel-in-progress: false`.
Separate pushes do not share a group, so a newer push cannot cancel an active
run or replace a pending run through GitHub concurrency. Manual cancellation
remains possible. Verify the selected SHA's completed CI run.

[Wait for CI](https://docs.railway.com/deployments/github-autodeploys#wait-for-ci)
uses GitHub Actions workflow conclusions, not individual job conclusions or
checks from other GitHub apps:

- A failed workflow skips the deployment.
- Skipped and neutral workflows do not block it.
- A cancelled workflow blocks only when no other workflow on that commit passed.
  Another workflow's success can allow deployment despite that cancellation.
- Workflows that do not finish within two hours cause Railway to skip deployment.

Keep required server checks inside the CI result and inspect cancellations.
Wait for CI does not prove that a conditionally skipped job ran. A classification
error or manual cancellation needs investigation before
accepting the corresponding deployment.

## Service settings

Apply these settings only during an authorized activation. Open project
`Clarify`, environment `production`, service `clarify-api`. Check names and IDs
against the table before applying any change. Preserve private variables and
unrelated settings; do not copy their values into logs or review notes.

1. In Settings, under Source, select repository `jvictormaynard/clarify` and
   branch `main`. Use **Enable** if automatic deployments are disabled. Check
   that a project member has contributor access and that the Railway GitHub App
   has repository access and its required permissions.
2. Enable **Wait for CI**. Read the setting back and confirm `checkSuites=true`.
3. Keep **Root Directory** at the repository root (`/`). Under Build, keep the
   Dockerfile builder and **Dockerfile Path** `server/Dockerfile`. The Dockerfile
   copies files outside `server/`; a root of `/server` breaks its build context.
4. Set **Watch Paths** to the following gitignore-style patterns, one per line.
   Patterns use the repository root, even when Root Directory is set.

   ```gitignore
   /server/**
   /shared/**
   /dictionary_snippets.py
   /.dockerignore
   /.github/workflows/ci.yml
   /.github/workflows/server-validation.yml
   /workflow_provider.py
   /mobile/scripts/sync-prompts.py
   /mobile/modules/clarify-core/ios/RewritePrompt.swift
   !**/*.md
   !**/*.rst
   ```

   The first four rules cover the Dockerfile's COPY inputs and build exclusions.
   The workflow and prompt rules also trigger validation-related changes.
   The last two rules exclude Markdown and reStructuredText, as the CI server
   classifier does. Changes confined to documentation do not trigger a
   deployment. Keep this list and the CI server classifier consistent
   when adding runtime or validation inputs. Changes to the separate pinned
   recovery-image workflow do not need a native deployment.
5. Under Deploy, keep **Healthcheck Path** `/health` and **Healthcheck Timeout**
   60 seconds. Keep the service's target port at 8080. Keep the Dockerfile's
   default start command, `python server/start.py`; a Gunicorn-only override
   bypasses migrations. Keep `healthcheck.railway.app` and the explicit service
   domains in `ALLOWED_HOSTS` as described in the server guide.
6. Review all staged changes before applying them. Read back Source, branch,
   autodeploy, Wait for CI, root, builder, Dockerfile path, watch paths, probe,
   port, and start command. Record the UTC time without private variable values.

Use the existing Railway settings. Do not add `railway.json` or `railway.toml`:
[Config as Code is deprecated](https://docs.railway.com/config-as-code), with
a hard cutoff of 2026-12-01. This path needs no new SDK or deployment controller.

## Verify a deployment

1. Record the intended full `main` commit SHA and its successful CI run URL.
   Confirm that server validation ran when server inputs changed. A green PR
   result does not replace CI for the merged `main` commit.
2. In Railway's Deployments tab, record the deployment ID and source commit SHA.
   Require an exact match to the selected green `main` SHA. Check the actual
   deployment record, not only Source's configured `commitSha`.
3. Check build logs for `server/Dockerfile`. Check startup logs for migration
   errors and Gunicorn startup. Verify that no start-command override
   bypassed `server/start.py`.
4. Confirm Railway's successful deployment probe and request `/health` from the
   service's HTTPS URL. Require HTTP 200 and `status: ok`. This includes a real
   database query. In the private operator environment, run
   `python server/manage.py migrate --check` and record its exit status.
5. Record the deployment status, health result, database migration check, and UTC
   verification time with the SHA and CI URL. Complete the relevant staging
   interaction checks before opening registration or funded processing.

Railway's [healthcheck](https://docs.railway.com/deployments/healthchecks) runs
during deployment. Railway does not continuously probe this endpoint after the
deployment becomes active. Later health failures need separate monitoring.

## Ordering, missed pushes, and recovery

Railway owns its build queue and
[singleton rollout](https://docs.railway.com/deployments/reference#singleton-deploys).
A new healthy deployment replaces the previous deployment, with a short overlap.
The old process can still serve requests while the new process migrates.
`server/start.py` serializes migration and cache-table creation with PostgreSQL
advisory lock `384136731`, then starts Gunicorn. That lock protects migration
execution, not build order, traffic, or every database operation.

Neither this workflow nor the documented native controls promise exactly one
deployment per commit or a FIFO rollout of every push. Use compatible additive
migrations while old and new processes can overlap. A healthy replacement and
a serialized migration do not prove client or old-server compatibility.

[Watch Paths](https://docs.railway.com/builds/build-configuration#configure-watch-paths)
filters changed file paths; it does not produce a server-only checkout. An
accepted deployment builds the complete selected source commit, which can include
earlier merged changes. The docs do not specify a guaranteed replay or comparison
baseline after every failed or skipped push. Do not assume a later documentation
push retries an earlier failed server deployment. Empty commits also do not
trigger deployments when watch paths are configured.

For a missing deployment, use **Show Skipped**, inspect CI conclusions and watch
paths, and check GitHub/Railway service status. Fix the cause first. For an
authorized retry of current `main`, confirm its exact SHA and green CI, then use
**Deploy Latest Commit** in Railway's Command Palette. Recheck the resulting
source SHA. **Redeploy** uses the selected old deployment's source and settings;
it does not select current `main`. These manual actions require the same evidence;
do not assume they reapply every autodeploy control.

To stop automatic delivery, click **Disable** in the service's Source settings
and read back the state. Inspect the Deployments tab and use **Abort deployment**
for unwanted work already in progress. Disabling future triggers does not prove
that an existing deployment stopped. Preserve the current healthy service and
database while investigating.

For rollback, first disable autodeploy and stop unwanted pending work. Select a
previous successful deployment and use **Rollback** only after checking schema
compatibility. Railway restores that deployment's image and custom variables
within its retention limits. It does not reverse PostgreSQL migrations or
financial records. A failed healthcheck can leave schema changes in place even
when traffic stays on the old image. Prefer a forward fix when old code cannot
use the migrated database; database restore needs a separate recovery plan.
Repeat the SHA, health, and database checks after recovery.

The manual **Shared account** `publish_server_image` path remains a separate
recovery tool pinned to `ced75d817decd55e7ed6f350e34e008b59f9cb26`. Its registry
image is not the native GitHub delivery path. Do not change that pin or switch
the Railway source as part of routine CI activation.
