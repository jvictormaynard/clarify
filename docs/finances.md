# Sponsored usage and public finances

Clarify uses confirmed contributions to pay operating costs and hosted processing.
The project has no profit goal. This does not imply registered charity status,
tax deductibility, or a financial return for contributors.

## Weekly allocation

Record received money and reserve operating costs before distributing credits.
Paying a reserved bill consumes the provision; it does not deduct the same cost
again. Existing user quotas remain protected.

New receipts wait for an operator to confirm that operating costs are recorded.
Automatic distribution cannot approve them. A pending receipt prevents a new
weekly distribution, while existing grants remain usable until expiry.

Each contribution releases its processing share over one calendar month. The
current week's slice is available in advance. A weekly reset does not create
money or authorize spending against future contributions. The configured monthly
provider cap is an additional spending limit, not a receipt.

Each receipt retains its own net processing basis and original release schedule.
Operating provisions and uncovered expenses reduce pending receipts first, oldest
first, then approved receipts newest first. Paying a provision does not change
that basis again. Releasing an unused provision restores the newest receipt's
available headroom first. Adding a receipt cannot move old costs onto new money
or accelerate its release. Processing settlements reduce available cash, without
deducting from the receipt's basis a second time.

Of the processing funds released for a week, 80 percent supports equal quotas for
eligible accounts and 20 percent is reserved for accounts entering during that
week. An eligible account has a verified primary email and has requested hosted
access or used it within the preceding 28 days. A new allowance is proportional
to the time left in the week and cannot exceed the entry reserve. An account
waits when that reserve is empty.

All quotas expire on Monday at 00:00 UTC. Clients show the reset in the device's
local time zone. A granted quota stays fixed until expiry. Personal quotas do not
roll over; actual unspent money stays in the treasury.

The account screen shows percentages. The server measures transcription and text
processing costs internally. Personal provider keys and local desktop processing
keep their existing behavior.

## Record confirmed funds and costs

Use the server's private operator environment and its database. These commands
change financial records. Do not run examples against production. Replace the
amounts, references and timestamps with confirmed records before use.

```sh
python server/manage.py record_finance contribution 10.00 \
  --reference receipt-001 --occurred-at 2026-10-25T00:00:00Z
python server/manage.py record_finance reserve 2.00 \
  --reference hosting-provision-001 --occurred-at 2026-10-25T00:00:00Z
python server/manage.py record_finance expense 2.00 \
  --reference hosting-payment-001 --occurred-at 2026-10-25T00:00:00Z
python server/manage.py distribute_funding --confirm-operating-costs
```

The USD 10 above is an example. Installation never books the maintainer's intended
monthly contribution. Record it only after the money is available to the project.
Use `release` to return an unused operating provision. Expenses consume existing
provisions first. An expense or provision that would spend committed user funds
is rejected.

The pair of source and reference identifies a financial record. Repeating the
same record has no further effect. Reusing it with different details fails.
References remain private. Run distribution after recording funds and operating
provisions. Use `--confirm-operating-costs` only after checking all pending
receipts and recording their known operating costs. Confirmation and distribution
run under the same treasury lock. At the common weekly reset, run
`distribute_funding` without that flag. The service also performs lazy distribution
during account maintenance; it never confirms pending receipts.

## Public page

`/transparency/` serves the public page in Portuguese, English and Spanish.
`/v1/public/finances` returns its public JSON data. Neither requires an account.
The private administrator host does not serve these routes.

The page separates confirmed receipts, paid operating costs, operating provisions,
processing costs, committed quotas, the entry reserve and available funds. These
categories have different meanings; do not add all the displayed cards together.
Public records contain amounts, dates and neutral labels. They exclude names,
email addresses, payment identifiers, operator references and bank details.
Uncertain processing costs carry an explicit estimate label. Imported historical
costs have no invented payment date. History queries load at most 50 records per
public page; the JSON response includes the total and next/previous page numbers.
HTML and JSON reads share public request limits. They use one read-only database
snapshot per response and do not acquire the treasury write lock.

## Future Stripe connection

Stripe registration is deferred until the project can use a business account.
Keep all `CLARIFY_STRIPE_*` values blank or disabled. The public project ledger
works without Stripe. No payment button appears without a verified live link.

When a business account is ready, configure a restricted live key with read
access to balance and balance transactions in the server's private secret store.
Set `CLARIFY_STRIPE_READ_KEY`, then run:

```sh
python server/manage.py sync_stripe_finance
```

The command only reads Stripe. It persists normalized amounts, currencies and
movement categories. It does not create credits, funding receipts or payments.
Test keys and general secret keys cannot publish live financial data. Never put
keys in client builds, public files, screenshots or Git.

Schedule this command through the operator's scheduler if the connection is
enabled. The page reports the last successful sync and marks data older than
24 hours or a failed sync as stale. Each sync reads up to 10,000 movements and
reports incomplete history if Stripe has more. Pagination serves 50 rows per page.

Stripe available and pending balances remain separate by currency. The page does
not convert them or add them to project cash. Payouts are transfers out of Stripe,
not operating expenses. Record a confirmed project receipt once through the
financial ledger; a Stripe sync never records it a second time.

An optional live Payment Link must use `https://buy.stripe.com/`. Verify its
destination and business account before setting `CLARIFY_STRIPE_PAYMENT_LINK`
and `CLARIFY_STRIPE_PAYMENT_LINK_VERIFIED=1`. The page also requires a successful
live sync before showing the link. Support is voluntary and does not change an
individual quota during its current period.
