# Account and ride-credit integration

This integrates the credit prototype from `tawseela-app` commit `c2d8b1a` into
this repository's verified account system. It does not modify the Render service
or combine existing database files.

## App API contracts retained

- `GET /api/v1/users/profile` returns `credit_balance` and `escrow_balance`.
- `GET /api/v1/rides?destination=...&women_only=true` filters female drivers.
- `GET /api/v1/rides/booked` includes the user's own offered rides and bookings.
- `POST /api/v1/{ride_id}/book` holds one seat's integer price in escrow.
- `POST /api/v1/rides/{ride_id}/complete` releases all backed bookings, pays the
  driver, and retains `floor(total_credits * 10 / 100)` as platform commission.
- `POST /api/v1/rides/new-ride` requires a verified driver; prices are positive
  whole credits (at most 1,000,000 per seat).

All these routes require a signed, unexpired access token and an active account.
Ride operations additionally require a verified account. The old prototype's raw-user-ID/unsigned-token shortcut is not used.
Request bodies cannot choose the acting user or the booking price.

## Transactions and audit

SQLite `BEGIN IMMEDIATE` acquires the write lock before reading the balances,
booking state, or remaining seats. Debit, escrow, seat, booking, and audit writes
commit together. Completion moves all balances and marks the ride complete in
the same transaction. Failed mutations roll back; repeats return 409 rather
than moving credits twice. There is one escrow and one release audit record
per passenger per ride. The platform commission is recorded separately.

Concurrency tests cover competing passengers for a final seat, duplicate
bookings, and simultaneous completion. Tests also cover invalid/revoked tokens,
wrong drivers, insufficient funds, partial-settlement rollback, integer prices,
search response shape, and additive schema migration.

This implementation is deliberately SQLite-specific. It requires persistent
storage. Do not point DATABASE_URL at a PostgreSQL server without implementing
and testing the equivalent locking and migrations.

## Database setup and migration

For a fresh staging database, startup creates the tables with zero balances.
Never reuse the bundled upstream database or photographs for a new service.

For an existing database created by this repo's *account backend*:

1. Stop writes, make a recoverable backup, and test on a copy first.
2. Configure its DATABASE_URL and other server settings.
3. Run `python -m scripts.migrate_credits` (also available inside the container).
4. Restart the server and verify the accounts and profiles on staging.

The additive migration preserves existing accounts and bookings. Old bookings
are marked `legacy`, with zero escrow; they cannot be settled as credit bookings.
Do not invent credits to complete them. Reconcile them explicitly before release.
Startup refuses a schema that needs this migration instead of failing later
while handling user requests.

The *currently deployed Render prototype* has a different schema, including
users without password hashes and bookings without account-backend IDs. This
migration refuses that schema. A separate export, identity reconciliation, and
balance migration must be designed after confirming whether it has real data.
Do not change Render's repository/branch or database in place yet.

## Product decisions still needed

New accounts get zero credits. There is no public mint/top-up endpoint or
automatic signup grant. The product owner must decide how the initial supply
is allocated. Tests seed their own isolated database; those grants do not exist
in production. Driver onboarding/approval also remains an operator decision;
signup does not grant driver privileges.

Cancellation/refunds and per-user unread receipts are not implemented. Stripe
payment UI in the mobile project must be reconciled with the closed-loop model;
this server does not pretend to accept real-money payments.

## Next staging checks

Provide persistent hosting, Redis and SMTP, then exercise signup, email
verification, login, profile, search, booking and completion on a real device.
Confirm token revocation with real Redis, email delivery, and restart persistence.
Automated tests mock email delivery and Redis lookups. They do not constitute
mobile end-to-end or store-release verification.
