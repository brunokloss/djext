# Development

## Configuration

Both sides read their settings from a `.env` file, which is git-ignored. Each has a committed `.env.example`, and `make install` creates the `.env` from it when it doesn't exist yet.

### Backend (`backend/.env`)

Read in `config/settings.py` with python-decouple. Real environment variables take precedence over the file.

| Variable               | Default       | What it does                                         |
| ---------------------- | ------------- | ---------------------------------------------------- |
| `SECRET_KEY`           | — (required)  | Django secret key. `make install` generates a fresh one. |
| `DEBUG`                | `False`       | Debug mode. `.env.example` turns it on for development. |
| `ALLOWED_HOSTS`        | empty         | Comma-separated hosts. With `DEBUG=True`, localhost is allowed anyway. |
| `CSRF_TRUSTED_ORIGINS` | empty         | Comma-separated origins allowed to POST through the Next.js proxy. |
| `DATABASE_URL`         | SQLite (`backend/db.sqlite3`) | Database URL, e.g. `postgres://user:pass@host:5432/db`. See [Postgres](#postgres-optional). CI runs the backend tests on Postgres. |
| `CONN_MAX_AGE`         | `60`          | Seconds to keep database connections open; `0` closes them after each request. |
| `PROJECT_SLUG`         | `djext`       | The project's short name: cookie names (`_djext_session`, `_djext_csrf`, `_djext_lang`), the bearer key prefix (`djext_`) and the defaults of `API_TITLE` and `DEFAULT_FROM_EMAIL`. Must match the frontend's `NEXT_PUBLIC_PROJECT_SLUG`. |
| `API_TITLE`            | `<PROJECT_SLUG> API` | API title in the docs and the OpenAPI schema. Run `make api-types` after changing it. |
| `DJANGO_ADMIN_PATH`           | `admin`       | The admin's URL path (`/admin/`). |
| `AUTH_PASSWORD`       | `True`        | Log in with email and password (`/api/auth/login` and the form on `/login`; the admin keeps its own form). |
| `AUTH_GOOGLE_CLIENT_ID` / `_SECRET` | empty | Log in with Google; off while the client id is empty. |
| `AUTH_MICROSOFT_CLIENT_ID` / `_SECRET` | empty | Log in with Microsoft; off while the client id is empty. |
| `AUTH_MOCK_URL`       | empty         | The mock provider (`http://localhost:8001` in `.env.example`). Only with `DEBUG=True`. |
| `PHONENUMBER_DEFAULT_REGION` | `BR` | Country (ISO 3166-1 alpha-2) of phone numbers typed without a country code; the admin's phone field starts on its flag. See [Users](../backend/apps/authd/README.md#users). |
| `LOG_LEVEL`           | `INFO`        | Lowest level written to stdout (see [Logging](../backend/modules/log/README.md)). |

If `SECRET_KEY` is missing, Django refuses to start with `UndefinedValueError: SECRET_KEY not found`.

### Postgres (optional)

SQLite is the default, with nothing to install. Use Postgres when you want the same database as production, and for what only works there: the audit log's `UPDATE` trigger and more than one `manage.py db_scheduler` (one active at a time, through a Postgres lock).

`docker-compose.yml` has one. Put this in `backend/.env`:

```
DATABASE_URL=postgres://djext:djext@localhost:5432/djext
```

Then `make db-up` starts it (the other make targets run it for you while `DATABASE_URL` is set) and `make db-reset` drops and recreates the database. Empty `DATABASE_URL` goes back to SQLite.

In a git worktree, the same container serves a database of its own, named after the worktree's folder (`djext_wk3`; `make db-up` creates it): its migrations, `make db-reset` and tests never touch the main checkout's. Nothing to set; `.env` stays the same.

It uses port 5432. If you already have a Postgres there, `make db-up` fails: change the port in `docker-compose.yml` (`"5433:5432"`) and use `localhost:5433` in `DATABASE_URL`, or stop the other one.

### Frontend (`frontend/.env`)

See [Proxy](architecture.md#proxy) for `BACKEND_URL` and `DJANGO_ADMIN_URL`.

| Variable                   | Default        | What it does |
| -------------------------- | -------------- | ------------ |
| `NEXT_PUBLIC_PROJECT_SLUG` | `djext`        | The start of the cookie names the frontend reads (`_djext_session`, `_djext_csrf`). Must match the backend's `PROJECT_SLUG`. |
| `NEXT_PUBLIC_PROJECT_NAME` | the slug       | The name people see: page title, sidebar, login page. |

Both are read when the app is built: set them before `next build` (the image takes them as build args).

## Quality and CI

| Side     | Lint / format                     | Types                            | Tests                                   |
| -------- | --------------------------------- | ------------- | --------------------------------------- |
| Backend  | Ruff, import-linter (`pyproject.toml`) | —             | Django test runner (each app and module), with coverage |
| Frontend | Biome (`biome.json`)              | `next typegen` + `tsc --noEmit` | Vitest (`__tests__/`), Playwright (`e2e/`) |

`make test-back` ends with the coverage report: the total and, for each file not fully covered, the lines no test runs. There is no minimum; it shows when something arrives without tests. `uv run coverage html` (from `backend/`) writes `htmlcov/` to browse them.

The backend tests ignore what `.env` says for the login switches (`AUTH_PASSWORD`, `AUTH_SIGNUP`, `AUTH_PASSWORD_RESET`, `AUTH_MAGIC_LINK`): they run with the defaults (`config/test_runner.py`), and a test that wants one on turns it on with `override_settings`.

The e2e tests exercise the whole stack: they migrate, create the example users and go through login and logout. Playwright reuses `make dev` if it is already running; otherwise it starts both servers itself.

`.github/workflows/ci.yml` runs on pull requests only (`main` only gets squash merges of code that passed there):

- **backend:** Ruff lint and format check, the import rules (`lint-imports`), `manage.py check`, a check for missing migrations, and the tests with their coverage.
- **frontend:** checks the generated API types are up to date, then `biome ci`, typecheck, unit tests and `next build`.
- **e2e:** Playwright against both servers. It only runs if the other two jobs pass, and uploads the test results when it fails.

CI doesn't use `.env` files; the workflow sets dev-only values for the backend variables.

## Common tasks

Backend (from `backend/`):

```bash
uv run python manage.py migrate
uv run python manage.py startapp <name>
uv add <package>
uv run ruff check --fix .
uv run ruff format .
```

Frontend (from `frontend/`):

```bash
npm run lint        # biome check
npm run format      # biome format --write
npm run typecheck   # next typegen + tsc --noEmit
npm run test        # vitest run (npm run test:watch for watch mode)
npm run e2e         # playwright test
npm run build
```

Your own example data goes in `backend/seed_local.py` (git-ignored): `make db-seed`, and so `make db-reset`, runs it through `manage.py shell` after the usual seeds when it exists. It is a plain script with the models imported; keep it safe to run again (`get_or_create`) and for development only, like `seed_users`.
