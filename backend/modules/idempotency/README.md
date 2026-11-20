# Idempotency keys

`modules/idempotency` makes a retry safe: put `@idempotent` under the router's decorator (`@idempotent(required=True)` to demand the key) and a request that repeats an `Idempotency-Key` gets the first response back, with `Idempotent-Replayed: true`, instead of running the endpoint again. The same key with another body is a 422, and while the first request still runs, a 409. Keys belong to the user who sent them and last `IDEMPOTENCY_TTL_HOURS` (24); a daily cron job purges them, and anonymizing a user deletes theirs. 5xx responses aren't kept, so a retry after one runs again. The decorator's docstring has the details. In the browser, `useIdempotencyKey()` (`frontend/lib/api/idempotency.ts`) keeps one key per action across retries.

## Depends on

The daily purge of old keys runs through `cron`.

## Removing it

Delete `backend/modules/idempotency/` and these lines: `INSTALLED_APPS`, `IDEMPOTENCY_TTL_HOURS` and its `ADMIN_APP_GROUPS` line in `config/settings.py`, plus `@idempotent` on the endpoints that use it. Its table stays in the database until you drop it.
