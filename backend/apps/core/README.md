# core

The project's own app, empty: start its models in `models.py` on `BaseModel` (`public_id`, `created_at`, `updated_at`). `api.py` has `POST /api/ping`, an example endpoint to copy and to try the API with (logged in, `{"message": "ping"}` answers `pong`); delete it once the project has its own. Users and login live in [`authd`](../authd/README.md).

It also groups the admin's apps (`ADMIN_APP_GROUPS`, `admin.py`) and holds the project-wide tests: the API contract, the smoke tests and `BaseModel`'s.
