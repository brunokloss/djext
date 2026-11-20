# Sentry

Errors and traces from Django, the Next server and the browser, off until you set `SENTRY_DSN` (`backend/.env`) and `NEXT_PUBLIC_SENTRY_DSN` (`frontend/.env`, read at build time). Use one Sentry project per side. The browser starts the trace and its calls to `/api` carry it to Django, so a click and the error it causes show up in the same trace; each event has the `request_id` tag, to find its log lines. Nothing personal is sent (no user, IP, cookies or bodies).

To try it locally, `make sentry` starts GlitchTip, a small Sentry-compatible server, at http://localhost:8002 (one container from `docker-compose.yml`, its data in a `glitchtip` database in the local Postgres): sign up, create a project for each side and put their DSNs in the two `.env` files. `make dev` then starts it when a DSN points at it.

To check it, log in as a superuser and press **Send test error** on the home page: it calls `POST /api/debug/error`, which fails on purpose. The browser's events go through `/monitoring` on Next (no CSP or ad-blocker trouble); source maps upload on `next build` with `SENTRY_ORG`, `SENTRY_PROJECT` and `SENTRY_AUTH_TOKEN` (and `SENTRY_URL` for a self-hosted Sentry).

## Depends on

The package `sentry-sdk` (and `structlog`, for the request id).
