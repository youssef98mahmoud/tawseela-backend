# Tawseela server preparation

This branch repairs startup and adds isolated tests. It is not a live deployment
or a complete production-readiness assessment.

## What is verified

`python -m pytest -q` uses a fresh temporary SQLite database. Email sending and
Redis blacklist lookup are mocked; no real mail is sent and upstream user data
is never opened. Tests exercise startup, signup, generated verification links,
chat membership, sender impersonation rejection, and message response shapes.
The Actions workflow also builds the container image.

## Hosting requirements

Use a long-running Python 3.12/container host with HTTPS, persistent storage,
a private Redis service, and an SMTP provider. Set every setting in
`.env.example` through the host's environment settings, never in git.

- `DATABASE_URL`: use `sqlite+aiosqlite:////srv/data/tawseela.sqlite3` for an initial
  single-instance deployment with a persistent disk mounted at `/srv/data`.
  Start empty. Do not deploy the bundled upstream `db.sqlite3`.
- Persist profile uploads at `/srv/app/media/dps`; preserve `default.png` when
  initializing this volume. Do not deploy upstream profile photographs.
- Generate separate random `SECRET_KEY` and `JWT_SECRET` values, at least 32
  random bytes each. `JWT_ALGORITHM=HS256`.
- `ACCESS_TOKEN_EXPIRY` is seconds; `REFRESH_TOKEN_EXPIRY` is days. Set
  `JTI_EXPIRY` in seconds at least as long as the refresh-token lifetime.
- Configure private `REDIS_HOST`, `REDIS_PORT`, and `REDIS_PASSWORD` if needed.
  Current Redis code does not support TLS-only endpoints; adapt it before using
  a provider requiring TLS. Do not expose Redis publicly without protection.
- Set `DOMAIN` to this server's public HTTPS origin, without a trailing slash.
- Supply the SMTP sender and credentials in `MAIL_*`; select STARTTLS or implicit
  TLS according to the provider. Keep certificate validation enabled.

Container start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`.
`/health` is a liveness check, not a database/Redis/email readiness check.
API documentation is at `/api/v1/docs`.

## Before connecting the mobile app

Exercise real signup, email delivery, verification, login, rides, logout, and
restart persistence on a staging server. Automated tests do not verify external
services or full mobile integration. The mobile messaging service must send the
stored Bearer token with its requests; the inspected Flutter service currently
omits it. Do not weaken server authentication to accommodate that omission.

After staging works, the mobile APP_ENV needs only client-safe values, starting
with `API_URL=https://YOUR-SERVER-ORIGIN` (no trailing slash). Server secrets never
belong in the mobile bundle.

## Remaining limitations

- Group chat unread counts remain 0 because the upstream model has no per-user
  read receipts. Private/direct messaging is explicitly unsupported by this
  implementation; it rejects receiver_id instead of exposing private messages.
- Test email/Redis mocks are not production fallbacks.
- Credit balances, escrow/commission, women-only filtering, and Stripe payment
  endpoints described or referenced in the customized app require separate
  implementation and compatibility work; this fork does not supply them.
- Existing password-reset UX, token purpose separation, upload validation,
  booking concurrency, rate limits, dependency security updates, and backup
  recovery need review before public release.
- The upstream repository has an empty License section and no LICENSE file in
  the inspected tree. Confirm reuse/distribution terms with its author before
  publishing a commercial service.
