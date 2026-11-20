# note

An example feature to copy: a user's own notes, from the model to the page. Delete it once the project has its own features.

It shows how a feature is put together:

- `models.py`: `Note` on `BaseModel`, with an `Audit` class so every change is logged under its owner.
- `services.py`: what can be done with notes. Every entry point (API, admin, task, command, an MCP tool) calls it. Each function takes the user it acts for and the note's id, never the request, and only reaches that user's notes.
- `api.py`: thin views that read the request, call `services.py` and shape the answer. Paths in the decorators, typed input and output, `public_id` shown as `id`.
- `@idempotent` on the POSTs: a retry with the same `Idempotency-Key` gets the first answer back, so a double click makes one note and sends one email.
- `services.email_note()`: stock `send_mail`, which `mail` queues for a worker, and an `action_performed` signal sent without the request: `audit` and `log` find who asked from the request being handled, or from `acting_as(user)` outside one.
- `tasks.py`: a daily `cron` job that deletes notes untouched for `NOTE_RETENTION_DAYS` (0, the default, keeps them). It starts disabled, like every new job.
- `tests/`: `test_services.py` for the rules without HTTP (including the audit log under `acting_as`, as a task or an MCP tool would run), `test_api.py` for the HTTP side (status codes, shape, who may reach what).
- `frontend/app/(app)/notes/`: the page, reading with `useApi` and writing with `api`, plus `frontend/e2e/note.spec.ts`.

## Removing it

Delete `backend/apps/note/`, `frontend/app/(app)/notes/` and `frontend/e2e/note.spec.ts`, then these lines: `"apps.note"` in `INSTALLED_APPS`, `"apps.note.tasks"` in `CRON_TASK_MODULES` and `NOTE_RETENTION_DAYS` (`config/settings.py` and `.env.example`), the email line in `NO_BODY` (`apps/core/tests/test_api_contract.py`), its two lines in `config/urls.py` and the Notes entry in `frontend/components/app-sidebar.tsx`. Run `make api-types` and drop the `note` tables with a migration, or start from a fresh database.
