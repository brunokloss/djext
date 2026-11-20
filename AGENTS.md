# AGENTS.md

Notes for coding agents working on djext. Read [README.md](README.md) and [docs/](docs/) first; this file only lists the rules that are easy to miss.

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
- Prefer stock Django and the libraries already in use before adding a dependency.
- `backend/apps/` is the project's base, `backend/modules/` holds optional features. An app may import a module, never the other way around. Modules don't import `config` or each other; they talk through `modules/signals/`. `make lint` enforces this.
- New module: start from `backend/config/module_template/` (see [Architecture](docs/architecture.md)). Short, singular names (`audit`, `bearer`). Keep its tests in `tests.py` and its docs in `README.md`, including "Depends on" and "Removing it".
- Models inherit `apps.core.models.BaseModel`. The API shows `public_id` (UUIDv7), never the integer `id`.
- One domain function per operation, called by the API, the admin action and anything else that needs it.
- No Redis, Celery or extra services by default: queue, cron, cache and sessions live in the database.
- A new env var follows the prefix of its siblings and goes in the matching `.env.example`.
- Change the docs (module README, `docs/`) in the same change as the code.
