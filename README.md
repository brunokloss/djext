# djext

A decoupled **Django + Next.js** boilerplate: a Django backend that serves an API and a Next.js frontend that consumes it, each in its own folder and deployable on its own.

Built on "all you need is Postgres", for starting small projects without extra moving parts: the task queue, email queue, scheduled jobs, cache and sessions all live in the database. There is no Redis, Celery or broker to run. When a project outgrows that, `CACHE_URL=redis://...` switches the cache to Redis and the code stays the same.

## Stack

| Layer    | Tech                                                        |
| -------- | ----------------------------------------------------------- |
| Backend  | Python 3.14+, Django 6, [Django Ninja](https://django-ninja.dev/), [python-decouple](https://github.com/HBNetwork/python-decouple), [structlog](https://www.structlog.org/), [Ruff](https://docs.astral.sh/ruff/), managed with [uv](https://docs.astral.sh/uv/) |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, [shadcn/ui](https://ui.shadcn.com/) (Base UI), [SWR](https://swr.vercel.app/), [Biome](https://biomejs.dev/), [Vitest](https://vitest.dev/), [Playwright](https://playwright.dev/) |
| Database | SQLite (dev default) or Postgres via `DATABASE_URL` (see [Postgres](docs/development.md#postgres-optional)) |

## Project layout

```
.
├── backend/            # Django project
│   ├── config/         # settings, urls (incl. the Ninja API), BaseModel, module loader, asgi/wsgi
│   ├── apps/           # base apps (authd: custom User, login; core: empty, for your models); each keeps its tests in tests/
│   ├── modules/        # features added on top, each documented in its README.md (see Docs below)
│   ├── manage.py
│   └── pyproject.toml
├── frontend/           # Next.js app
│   ├── app/            # App Router pages and layout; (app)/ = pages behind login, with the sidebar
│   ├── components/
│   │   └── ui/         # shadcn/ui components (generated: `npx shadcn@latest add <name>`)
│   ├── lib/api/        # typed API client, SWR hook and generated schema
│   ├── __tests__/      # unit tests (Vitest)
│   ├── e2e/            # end-to-end tests (Playwright)
│   └── package.json
├── .github/workflows/  # CI
└── Makefile            # shortcuts to run/test both sides
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python 3.14 for you if needed)
- Node.js 24 (see `frontend/.nvmrc`; 22.22+ also works) and npm
- Optional: [Docker](https://docs.docker.com/get-docker/), only for the local Postgres (see [Postgres](docs/development.md#postgres-optional))
- `make`
- Optional: VS Code. `.vscode/` sets up the venv interpreter and formats on save (Ruff for Python, Biome for the frontend) and has debug configurations (Run and Debug: Django, its tests and task worker, Next.js, or "Full stack"); install the recommended extensions it suggests. Run `make install` first so the venv and `node_modules` exist.

## Getting started

```bash
make install   # creates the .env files, installs dependencies and migrates
make dev       # runs backend and frontend together
```

- Backend: http://localhost:8000
  - API: `/api/` (interactive docs at `/api/docs` once logged in, health checks at `/api/health` and, with the database, `/api/health-db`)
  - Admin: `/admin/`
- Frontend: http://localhost:3000

The frontend proxies `/api/*` to Django (see [Proxy](docs/architecture.md#proxy)), so the app runs from http://localhost:3000. The admin is opened on Django itself, at http://localhost:8000/admin/; on localhost it shares the session cookie with the frontend, so logging in on either is enough.

`make dev` also runs the mock login provider (see [Log in with a provider](backend/modules/oauth/README.md)) and prefixes each log line with `[BCK]`, `[FRT]` or `[MCK]`. If one process dies, all are stopped; `Ctrl+C` stops everything.

To run a side on its own, use `make backend` or `make frontend`.

## Make targets

Run `make help` for the full list.

| Target          | What it does                                              |
| --------------- | --------------------------------------------------------- |
| `make install`  | Creates the `.env` files if missing, installs dependencies and migrates |
| `make dev`      | Runs backend, frontend and the mock login provider together |
| `make prod`     | Builds the production images and runs them at http://localhost:3000 with DEBUG off (see [Deployment](docs/deployment.md)) |
| `make prod-down` | Stops and removes the `make prod` containers; the Postgres keeps running |
| `make prod-superuser` | Creates an admin user in the `make prod` database (asks for email and password) |
| `make prod-reset` | Stops the `make prod` containers and deletes its database; the next `make prod` migrates a fresh one |
| `make superuser` | Creates an admin user (asks for email and password)      |
| `make migrate`  | Applies the pending migrations                            |
| `make makemigrations` | Creates migrations for the model changes            |
| `make db-up`    | Starts the local Postgres (Docker) when `DATABASE_URL` is set; with SQLite there is nothing to start. The targets that need the database run it themselves |
| `make db-reset` | Deletes the local database (the SQLite file, or drops and recreates the Postgres one), migrates and creates the example users |
| `make db-seed`  | Creates example users with the password `password` (DEBUG only) |
| `make sentry`   | Starts GlitchTip, a local Sentry-compatible server, at http://localhost:8002 (see [Sentry](backend/modules/sentry/README.md)) |
| `make storage`  | Starts RustFS, a local S3-compatible server, at http://localhost:9000 (see [Storage](backend/modules/storage/README.md)) |
| `make api-types` | Exports the OpenAPI schema and regenerates the frontend API types |
| `make backend`  | Runs Django at http://localhost:8000                      |
| `make frontend` | Runs Next.js at http://localhost:3000                     |
| `make lint`     | Lints, format-checks and typechecks both sides (same as CI) |
| `make format`   | Auto-fixes lint issues and formats both sides             |
| `make test`     | Runs backend and frontend unit tests                      |
| `make test-all` | Runs backend, frontend and end-to-end tests               |
| `make test-back`  | Runs backend tests in parallel (`manage.py test --parallel`) and prints the coverage |
| `make test-front` | Runs frontend unit tests (Vitest)                       |
| `make test-e2e`   | Runs end-to-end tests (Playwright)                      |

## Docs

- [Development](docs/development.md): configuration, Postgres, quality and CI, common tasks
- [Architecture](docs/architecture.md): apps and modules, `BaseModel`, the proxy
- [API](docs/api.md): routers, typed endpoints and the typed client
- [Deployment](docs/deployment.md): the production images, the processes and Vercel
- [authd](backend/apps/authd/README.md): users, anonymizing them, login
- Each module documents itself in its `README.md`: [audit](backend/modules/audit/README.md), [bearer](backend/modules/bearer/README.md), [cron](backend/modules/cron/README.md), [crypto](backend/modules/crypto/README.md), [idempotency](backend/modules/idempotency/README.md), [log](backend/modules/log/README.md), [mail](backend/modules/mail/README.md), [oauth](backend/modules/oauth/README.md), [queue](backend/modules/queue/README.md), [runtime](backend/modules/runtime/README.md), [sentry](backend/modules/sentry/README.md), [storage](backend/modules/storage/README.md)

## Status

Each side has a production image, and `make prod` runs both locally. The frontend can go to Vercel instead. See [Deployment](docs/deployment.md).

## License

[MIT](LICENSE)
