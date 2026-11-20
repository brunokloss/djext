# Logging

Both sides write one line per event to stdout: JSON in production (`DEBUG=False`, `next start`), columns in development. Each line has:

- `request_id`: the same on both sides. `frontend/proxy.ts` gives each request an id (or keeps a valid incoming `X-Request-Id`), passes it to Django in that header and returns it in the response. Search for it to see a request go through Next and Django.
- `tsk`, `que`, `wrk` (and `dur`, in ms, on the line that says how it ended): inside a background task, which task (the id the admin shows, its first 8 characters in the `request_id` column in development), its queue and the worker. The cron logs the same `tsk` when it enqueues a job, so one search follows it from "enqueued" to "ran". Django's own `Task id=... state=RUNNING` line comes before these are set.
- `service`: `frontend` or `backend`.
- `channel`: what it is about.

| Channel   | Side     | What                                                    |
| --------- | -------- | ------------------------------------------------------- |
| `request` | both     | One line per request. On the backend with the status, `usr` (the user's UUID), `ses` (the first 12 characters of the session hash the audit log saves in `session_hash`; paste them in the admin's search to find it), `xip` (IP) and `dur` (ms); 4xx/5xx are warnings, with the error body except for 401/403/404. |
| `auth`    | backend  | Logins, logouts and failed logins (password, admin and providers) with `usr` or the `email`, and where they came from: `xip`, `uag` (User-Agent), `lng` (Accept-Language). See `modules/log/auth.py`. |
| `worker`  | backend  | Background tasks: Django's and django-tasks-db's logs, and our code while a task runs, with `tsk`, `que` and `wrk`. |
| `scheduler` | backend | `manage.py db_scheduler` (modules/cron): the ticks and the jobs it enqueues, with the `tsk` the worker will log and `src` (`tick`, or `manual` with the `usr` who pressed "Schedule now" in the admin). |
| `app`     | backend  | Our code: `logging.getLogger(__name__)` under `apps/` or `modules/`. |
| `django`  | backend  | Django itself, like 500 tracebacks and CSRF failures. |
| `error`   | frontend | Server errors in Next (`instrumentation.ts`).           |

The backend side is `modules/log` (logging settings, middlewares, the auth channel and its signals); the frontend logger is `frontend/lib/log.ts`. It can be removed (see [Removing it](#removing-it)).

> **Note:** the IP is the last `X-Forwarded-For` entry. Next passes that header on as it came, so it is only trustworthy behind a load balancer that appends the client's address.

## Depends on

The package `structlog`. It listens to `action_performed` and `login_throttled` (`modules/signals`).

## Removing it

Delete `backend/modules/log/` and these lines: `INSTALLED_APPS`, the two middlewares in `MIDDLEWARE`, and the `logging_config` import and `LOGGING` in `config/settings.py`.
