# Main validation and delivery

`CI` runs on pull requests and pushes to `main`. Its Linux and Windows unit
checks and Windows packaging check retain their required names. The workflow
also selects server and iOS validation from the complete change range.

`scripts/delivery_policy.py` compares a push with its `before` commit. For a pull
request, it compares the tested merge with the pull request's base commit. It
counts both paths of a rename. A new branch or a manual CI run validates every
component. A missing or invalid change boundary fails CI.

Server files and Docker inputs select PostgreSQL tests, migration checks, and
container startup checks. Mobile files select native tests and an unsigned
simulator build. Shared contracts, canonical prompts, and locale generation
select all consumers. Markdown, reStructuredText, and files under `docs/` do not
select additional component checks. Desktop unit checks and packaging still run
on every CI event to preserve the existing required checks.

The iOS validation workflow has read-only repository permissions. It receives no
signing secrets and has no upload step. TestFlight publication uses the separate
release flow. The old `Shared account` workflow retains its manual recovery image
and legacy branch trigger; `CI` now owns pull request validation.

Each push to `main` gets a distinct CI concurrency group. A newer push cannot
cancel that commit's running or pending CI through this group. Other branches
retain cancellation of obsolete CI runs. This is needed because Railway's
`Wait for CI` can ignore a cancelled workflow when another workflow on the same
commit succeeded.

Server delivery uses the [native Railway setup](server-delivery.md). Client
publication uses [release preparation and promotion](release-automation.md).
These checks do not enable a production deployment or publish a release by
themselves. Existing manual Windows acceptance requirements still apply.
