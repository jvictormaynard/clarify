# Stripe financial transparency

Verified against official Stripe API documentation on 2026-10-25.

## Verified provider facts

- The [balance API](https://docs.stripe.com/api/balance) separates available and
  pending payments balances. Stripe can pay funds out to a bank account. A Stripe
  balance therefore does not describe all money held by the project.
- The [balance transaction list](https://docs.stripe.com/api/balance_transactions/list)
  is paginated. `starting_after` advances the cursor and `has_more` indicates
  whether additional transactions remain. One response cannot establish complete
  history unless pagination has finished.
- [Restricted API keys](https://docs.stripe.com/keys) can limit the permissions
  granted to a server integration. Server API keys are private. A publishable key
  does not grant access to private account balances.

## Integration decisions

The public application reads a normalized server snapshot. It never reads the
Stripe dashboard or receives an API key. The snapshot contains financial amounts,
currencies, dates and neutral movement categories. It excludes donor identity,
payment identifiers, raw provider descriptions and bank details.

Keep project treasury categories and Stripe source balances separate. Do not sum
currencies without a recorded conversion. Treat payouts as transfers and handle
fees, refunds and pending funds explicitly. Test-mode data cannot represent
received real contributions.

Use manual confirmed receipts and operating provisions for allocation in the
first version. A read-only Stripe synchronization supplies public source evidence
without importing a second receipt into the quota ledger. Operators reconcile
receipts, payouts and expenses using the documented management commands.

The user cancelled initial registration until a business account can be opened.
Do not create an account under the user's personal tax identity. No account,
payment link, received contribution or production synchronization has been
verified. Keep the connection disabled while the manual project ledger operates.
