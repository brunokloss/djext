# AGENTS.md

Notes for coding agents working on djext. The details are in [README.md](README.md) and [docs/](docs/); this file says why things are the way they are, so a change fits in.

## Why djext exists

To start a new project fast without starting it half-built. A fresh project gets what usually comes late or never: login, an admin back office, an audit log, structured logs, rate limits, background tasks, scheduled jobs, email, tests and CI, all wired together and documented. It is meant for small projects that should stay simple: one Django, one Next.js, one Postgres.

**djext is B2B.** The team creates the accounts in the admin and hands them out. There are no B2C tools yet: no self sign-up, email verification, password reset by email or invites. Don't assume they exist, and don't add them as a side effect of another change.

Keep it that way. A change should make the starting point better for most projects, not add options for one of them.

**Build on what is here, don't start over.** Before writing anything, look for the piece djext already has (login, users, logging, audit, rate limits, tasks, cron, email, storage, the typed API client, the UI components) and extend it. Don't write a parallel version of it, swap it for another library or scaffold a new structure next to the existing one. If something is missing or doesn't fit, say so before working around it.

## Architecture decisions

- **Decoupled.** Django owns data, auth, the admin and background work, and serves only an API. Next.js owns the UI. Each side has its own folder and deploys on its own (the frontend can go to Vercel).
- **Same origin through a proxy.** Next rewrites `/api/*` to Django, so the browser talks to one origin: stock Django session cookies and CSRF, with no CORS and no JWT. Don't add token auth for the browser; `modules/bearer` is for programs.
- **A typed contract.** Django Ninja with typed input and output on every endpoint (a test enforces it). The frontend types are generated from the OpenAPI schema, so a backend change that breaks the frontend fails at compile time.
- **All you need is Postgres.** The task queue (`django-tasks-db`), scheduled jobs (`cron`), cache (an UNLOGGED table), sessions and the email queue (`post_office`) all live in the database. No Redis, Celery or broker by default. `CACHE_URL=redis://...` is the way out when a project outgrows it. SQLite is the development default.
- **Stock Django first.** Use what Django ships (auth, sessions, admin, the tasks framework) and the libraries already in use before writing or adding something. The admin is the back office.
- **Removable modules.** `backend/apps/` is the base every project keeps; `backend/modules/` holds features a project may drop. Removing a module is deleting its folder and the lines its README lists. That is why modules don't import apps, `config` or each other, and talk through `modules/signals/` (import-linter checks it).
- **Public ids.** Rows keep an integer `id` for joins; the API and URLs only show `public_id` (UUIDv7), so ids leak neither counts nor order.
- **Built-in traceability.** One structured log line per event, with a `request_id` shared by Next and Django and by background tasks. Every auth event is logged. The audit log is written in the same transaction as the change, with who asked and whose data it is.
- **Personal data is anonymized, not deleted** (`User.anonymize()`), so records that point at a person survive.
- **Configured by env vars** (`python-decouple`), with `.env.example` as the list. `PROJECT_SLUG` renames the project without editing files, so a fork can keep pulling updates.
- **Current versions on purpose** (Python 3.14, Django 6, Next.js 16): a new project should not start behind.

## Commands

Run from the repo root:

- `make install`: set up both sides (once).
- `make lint`: what CI checks (Ruff, import-linter, Django checks, Biome, typecheck).
- `make format`: auto-fix lint and formatting.
- `make test`: backend and frontend tests. `make test-e2e` runs Playwright.
- `make makemigrations`: after a model change. CI fails on missing migrations.
- `make api-types`: after an API change. CI fails if `frontend/lib/api/` is stale.

## Rules

- Everything in the repo is in plain English: code, comments, docs and commit messages.
- New module: start from `backend/config/module_template/` (see [Architecture](docs/architecture.md)). Short, singular names (`audit`, `bearer`). Its tests go in `tests.py` and its docs in `README.md`, including "Depends on" and "Removing it".
- Models inherit `apps.core.models.BaseModel`.
- Every operation goes through a service, even a trivial one: a function in the app's `services.py` that the API, the admin, tasks, commands and any new entry point (an MCP tool, a webhook) call. Views stay boring: read the request, call the service, shape the answer. So a new way in is a thin adapter, and the rules, the audit log and the side effects come with it.
- A service takes the user it acts for, never the HTTP request. Outside a request (a task, a command, an MCP tool), call it inside `with acting_as(user):` (`modules/signals/context.py`) so the audit log and the logs know who did it.
- `backend/apps/note` is the example to copy: model, services, thin API, idempotent POSTs, an action, a cron job, tests for the services and the API, and the page.
- Don't add database queries to failure paths (a failed login, a rejected key) just to enrich a log line.
- A new env var follows the prefix of its siblings and goes in the matching `.env.example`.
- Change the docs (module README, `docs/`) in the same change as the code. Keep them short; point to `/api/docs` instead of listing endpoints.
