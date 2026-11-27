# Recurring subscriptions — integration and activation

The account backend now supplies the Flutter subscription endpoints. Membership payments are separate from earned ride credits: none of these routes changes available credits, escrow or the platform credit ledger.

## Configuration (disabled by default)

Use a Stripe **test-mode** monthly recurring Price for EGP 150 (15000 minor units), licensed usage, interval count 1. Configure server secrets outside Git:

- `BILLING_ENABLED=true`
- `STRIPE_SECRET_KEY`: test secret key
- `STRIPE_WEBHOOK_SECRET`: endpoint signing secret
- `STRIPE_MONTHLY_PRICE_ID`: the recurring Price ID
- `BILLING_ALLOW_LIVE=false` (default)
- `REQUIRE_SUBSCRIPTION=false` during isolated integration testing; `true` enables the server-side membership gate for offering and booking new rides.

The mobile `.env` needs the matching client-safe `STRIPE_PUBLISHABLE_KEY` and deployed `API_URL`. Never put secret keys or webhook secrets in the app.

The existing 150 EGP amount is retained from the app. The server validates the configured Price against that amount, currency and monthly interval. Client requests cannot choose the account, price or amount. Discounts, trials, prorations and other plans are not supported by this version.

Requests pin Stripe API `2024-06-20`. Configure a snapshot webhook endpoint with the same version at `POST /api/v1/payments/webhook`. Subscribe to `customer.subscription.created`, `.updated`, `.deleted`, `invoice.paid`, `invoice.payment_failed`, `charge.refunded`, `charge.dispute.created`, and `charge.dispute.closed`. No bearer token is required on this exact POST path: raw-body signature verification is required instead. A failed provider refresh returns non-2xx so delivery can retry.

## API and behavior

- `POST /api/v1/payments/subscription-intent`: creates/reuses an incomplete recurring subscription and returns its first invoice PaymentIntent secret for the existing native PaymentSheet. An already-active member does not receive another checkout.
- `GET /api/v1/payments/subscription`: retrieves current Stripe state and returns `active`, `status`, `paid_until`, `cancel_at_period_end` and plan details.
- `POST /api/v1/payments/subscription/cancel`: schedules cancellation at the end of a paid period; incomplete subscriptions are canceled immediately. No ride-credit refund or grant occurs.

Only active subscriptions with a paid latest invoice and an unexpired billing period grant membership. Failed payments, expired periods, full refunds and disputes do not grant access. Partial refunds do not automatically revoke access. The server refreshes provider state instead of trusting event ordering or a client success callback. Webhook IDs are deduplicated. Dispute resolution may require operator review.

When enabled, membership enforcement applies to new ride offers/bookings only. Existing bookings can still be canceled and rides completed without renewing. Accounts, profiles, messages and billing management remain accessible subject to their existing authentication rules.

New additive tables `memberships` and `billing_events` are created during normal startup after existing schema checks. Take a verified backup before deploying any database change. Keep the existing ride-lifecycle migration requirement for older databases.

Checkout idempotency keys are committed before external creation calls. Ambiguous attempts older than 23 hours fail closed for operator reconciliation, rather than risking a second subscription after Stripe's key retention window. Inspect provider records and reconcile the local membership before retrying; do not delete the row blindly. Keep billing credentials configured while subscriptions exist so cancellation/status/webhooks remain available.

## Validation and release limits

Tests use disposable SQLite databases, synthetic signed events and a mocked Stripe transport. They verify ownership, repeated checkout, ambiguous retries, expired retry windows, disabled/live-mode guards, cancellation, renewal-state refresh, event replay/order, refund/dispute revocation, and unchanged ride credits. They do not establish successful external payments.

Before enabling live payments: confirm payment-processor eligibility for the business, agree the membership offering and price, confirm the appropriate store billing route for that offering, configure real hosted webhooks, and run test-mode payment authentication, renewal failure, cancellation and restart persistence through actual devices. Set `BILLING_ALLOW_LIVE=true` only after those checks. This integration is not an App Store/Google Play billing approval or an in-app-purchase implementation.

The initial SQLite implementation serializes billing refreshes with bounded provider calls under a write lock. It is suitable for controlled single-instance staging, not a claim of production scale; load testing and moving provider synchronization out of long write transactions remain release work.

References: https://docs.stripe.com/api/subscriptions/create?api-version=2024-06-20 ; https://docs.stripe.com/webhooks ; https://docs.stripe.com/api/idempotent_requests
