# Runtime

`modules/runtime` adds System › Runtime to the admin, for superusers: the Django and Python versions, the settings (secrets show only whether they are set, the database URL without its password) and every migration applied. The settings shown are a fixed list in `modules/runtime/admin.py`, so a new one stays hidden until it's added there.

## Depends on

Nothing besides Django.

## Removing it

Delete `backend/modules/runtime/` and these lines: `INSTALLED_APPS` in `config/settings.py`.
