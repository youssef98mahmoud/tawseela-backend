# Ride lifecycle upgrade

Members earn ride credits by carrying passengers, then spend credits when riding with another member. Subscription charges are separate; this change does not sell credits or implement subscription billing.

Changes include verified members offering rides without a role change, repeat use of a vehicle, timezone-aware future departures, and atomic cancellation refunds. A passenger cancels their own booking; the driver cancels all bookings. Cancellation is available before departure. Completed rides cannot be refunded through this endpoint. A canceled booking cannot currently be rebooked on the same ride.

## Existing SQLite database

Stop application writes and take a verified database backup before upgrading. Run with the same database configuration as the account backend:

```sh
python -m scripts.migrate_ride_lifecycle
```

The migration removes the vehicle-plate uniqueness constraint while preserving rides and bookings, applies missing additive credit columns, and creates the refund ledger. It refuses the incompatible standalone ledger prototype schema. Test the migration on a copy first; restore the backup on failure. New empty databases need no manual migration. The application deliberately refuses an old unique-plate schema rather than silently modifying production data at startup.

## Validation and outstanding release work

Run `python -m pytest -q`. Tests use disposable databases and mocked email, never production balances. Coverage includes refund conservation and duplicate protection, cancellation racing with settlement, repeated use of one car, token-purpose separation, invalid signup validation, and upload limits.

This is not production launch approval. Subscription billing and entitlements, persistent hosting, account deletion, abuse reporting and moderation, store signing/build requirements, and physical-device testing still need verification or implementation. New members start with zero credits, so an explicit initial-credit policy is required before the first exchange can occur. The existing 10% credit commission is unchanged and does not generate subscription revenue. Password reset tokens are purpose-bound and invalid after password change, but reset-link browser UX, concurrent reset handling and session revocation remain follow-up work.
