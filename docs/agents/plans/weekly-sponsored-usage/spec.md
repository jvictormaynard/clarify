# Weekly sponsored usage and public finances

## Accepted product rules

Clarify is a nonprofit project. Contributions fund its operating costs and the
hosted processing offered to users. The initial intended contribution is USD 10
per month. An intention or an environment spending cap is not a received payment.

- Reserve operating costs before distributing processing funds. Include unpaid
  costs for the financed period. Payments already reflected in cash are counted
  once. Protect money committed to existing quotas.
- Release the funded monthly processing budget gradually through weekly periods.
  Keep the monthly spending boundary; a weekly reset does not create new money.
- Allocate 80 percent of a period's processing budget to equal individual quotas
  and 20 percent to accounts entering during the period.
- Eligible accounts have a verified email and have used or requested access in
  the previous 28 days. Unverified and inactive accounts receive no regular share.
- Reset all accounts on Monday at 00:00 UTC. Clients display that instant in the
  user's local time zone.
- Keep an allocated quota fixed until its expiry. New accounts receive a
  time-proportional entry quota bounded by the remaining entry reserve. If funds
  are unavailable, sponsored access waits for a later distribution.
- Personal quota does not roll over. Real unspent money remains in the project.
  Future contributions never cover an automatically created deficit.
- Show personal usage as a percentage and show the next reset. Keep the underlying
  cost, audio duration, token count and raw quota out of the account usage UI.
- Account for transcription duration and text-model input/output costs internally.
  Preserve once-only operation accounting, reservations, failure handling and
  concurrency bounds. Small quotas must permit affordable operations.
- Share the account quota across desktop and iPhone. Personal-key and local
  desktop processing retain their existing boundaries.

## Contracts and ownership

The server owns financial entries, operating provisions, period allocation,
admission and settlement. Historical operations and settled monthly spending
survive the transition. Deployment never books a fictional opening contribution.

The account usage contract is version 2:

```json
{
  "schema_version": 2,
  "period_start": "2026-10-26T00:00:00Z",
  "reset_at": "2026-11-02T00:00:00Z",
  "used_percent": 25,
  "remaining_percent": 75,
  "reserved_percent": 0,
  "allocation_status": "available",
  "hosted_available": true
}
```

Dates and values above illustrate the shape. Allocation status distinguishes
`available`, `waiting`, `unfunded` and `inactive`. Empty, unsupported and malformed
snapshots must not display invented spendable credit. Clients retain stale-result
rejection and account-scoped caches.

`funding.public_summary(page=1, page_size=50)` supplies money strings, aggregate
budget categories and a bounded movement page with its total record count.
`funding.record_contribution()` records a confirmed manual
receipt with an idempotent source/reference pair. Private operator commands
record funding and operating costs for the initial version.

New receipts remain pending until the operator confirms that known operating
costs are recorded. `distribute_funding --confirm-operating-costs` approves pending
receipts and distributes under one treasury lock. Automatic distribution cannot
approve them. Pending receipts block a new period, without changing an existing
grant. Each receipt stores its net processing basis and original monthly release
schedule. New receipts do not reweight old operating costs. Paying a provision
does not deduct its cost twice. Operating changes consume pending receipts oldest
first, then approved receipts newest first; unused provisions restore the newest
available headroom first. Processing spend is deducted once from released funds.

## Public transparency and Stripe

The new public page reports project financial movements and the source of each
balance. Operating provisions, provider costs, committed quotas and spendable
funds are separate categories. A Stripe payout is a transfer, not an operating
expense. Stripe funds and money held outside Stripe are not silently added twice.

Read-only Stripe synchronization records available and pending balances by
currency, normalized movements, and the last successful synchronization. It
handles pagination, test mode, unavailable credentials and stale data explicitly.
It does not publish contributor identity, payment identifiers, raw descriptions,
credentials, bank data, or the private dashboard. Failed synchronization retains
the last successful snapshot and reports its age.

Manual funding entries remain the source of allocations in this version. Stripe
snapshots provide public source evidence; importing them does not grant credit a
second time. The page distinguishes the Stripe balance from the project budget.
Public HTML and JSON share rate limits. Each response reads a coherent database
snapshot without taking the treasury write lock.
A configured Stripe Payment Link can accept voluntary support. An absent link
does not render a working payment button or a fictitious account.

The user cancelled Stripe registration until a business account can be opened.
Do not create an account under the user's personal tax identity. Keep Stripe
unconfigured and payment links disabled. The public ledger works without Stripe;
a future business account can supply read-only evidence after configuration.

## Public language

Lead with what Clarify helps the user do. Explain voluntary support after the
benefit. Describe the project as nonprofit without claiming registered-charity
status, tax deductibility or financial returns for contributors.

Use personal percentages and an expiry date in the account screen. Explain a
smaller allowance when funding or the number of eligible accounts changes. Keep
the current granted allowance stable. Exhaustion messages state the reason and
next distribution; they do not pressure the user into donating.

Public finance copy states whether amounts are confirmed, pending, provisioned
or committed. It identifies Stripe as one source of evidence. A public movement
does not identify its contributor. Support links remain optional and have clear
destinations. Apply Humanizer to every language and retain factual qualifications.

## Validation and delivery

Use isolated clocks, profiles, PostgreSQL databases and fake Stripe/provider HTTP.
Verify period boundaries, active eligibility, concurrent allocations, operating
reserves, exhaustion, late settlement, idempotency, entry proration, mixed
currencies, refunds, privacy and snapshot failures. Validate desktop loading and
quota states, local reset display, mobile contracts and locale generation.

Run the complete server and root Python suites, relevant Settings checks and
mobile checks on the integrated candidate. Use two fresh read-only reviewers for
the financial and credential boundaries. Native Windows and iOS acceptance remain
separate gates. No commit, PR, merge, deployment or release is implied by local
implementation. Record any pending external account step precisely.
