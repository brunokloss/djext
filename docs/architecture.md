# Architecture

## Apps and modules

Both folders hold plain Django apps, listed by hand in `INSTALLED_APPS`:

- `backend/apps/`: the base every project gets (`authd`: the custom `User` and login; `core`: no models yet, where the project's start, plus the admin's app groups and the project-wide tests).
- `backend/modules/`: features you add on top, such as `oauth`. Create one from the template in `backend/config/module_template/`, so every module starts the same way (`apps.py` with `name = "modules.<name>"`, `models.py`, `tests.py`, `migrations/` and a `README.md` with "Depends on" and "Removing it"):

  ```bash
  # from backend/
  mkdir modules/invoice
  uv run python manage.py startapp invoice modules/invoice --template config/module_template -e py,md
  ```

  Then add `"modules.invoice"` to `INSTALLED_APPS`, fill in its README and, if it has an API, `api.add_router("", router)` in `config/urls.py` (paths like `/invoices/...` go in the decorators; see [API](api.md)).

Imports only go one way: an app may import a module (`authd` uses `throttle`, `bearer`, `cache` and `phone`, and `User.anonymize()` calls most of them), never the other way around; modules don't import `config` either (settings reach them through `django.conf.settings`), nor each other. What they need to tell each other goes through the signals in `backend/modules/signals/signals.py`, which imports nothing of ours: `action_performed` (something a person did, such as clearing the cache; `audit` and `log` log it), `login_throttled` and `login_options_requested` (the login page asks which ways to log in besides the password are on; `oauth` returns its providers) and `inactive_login` (the right password for an account not active yet; `signup` resends its confirmation link and says why). Anyone sends them and anyone listens, so a module works without the one that listens. Next to them, `modules/signals/context.py` says who is acting: the request being handled (kept by its `RequestContextMiddleware`) or, outside a request, the user set with `with acting_as(user):`. That is how a service that never sees the request still gets its actor into the audit log and the logs. [import-linter](https://import-linter.readthedocs.io/) checks these rules (`[tool.importlinter]` in `backend/pyproject.toml`, run by `make lint` and CI); a test that needs another module skips itself when that module is out and is listed in `ignore_imports`.

Each module keeps its tests in its folder (`tests.py`) and its docs in its `README.md`, so removing one is deleting its folder and the lines its README lists.

The project's models inherit `apps.core.models.BaseModel`: the primary key stays the integer `id`, used only inside, and `public_id` (UUIDv7) is the one the API and URLs show, plus `created_at` and `updated_at`. In a schema, return `public_id` as `id: UUID` (like `SessionOut`), and add `exclude = ["updated_at"]` to the model's `Audit` class. Modules can't import an app, so theirs (`oauth`'s `UserIdentity`, `bearer`'s `BearerKey`, `crypto`'s `Keyset`, `idempotency`'s `IdempotencyKey`) declare the same three fields themselves. The models without them are the ones Django shapes (`User`, `Session`, the cache table), the audit log (never updated) and `cron`'s, whose primary key is a UUID.

```python
from apps.core.models import BaseModel


class Order(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
```

The admin's sidebar keeps few groups: `ADMIN_APP_GROUPS` (`config/settings.py`) lists the apps that show inside the group of another (Users and User identities with Groups, Cron Schedules and Queue with Task Results, Runtime with the audit logs). Only the listing changes, not the URLs. An app that isn't installed is skipped, so removing a module leaves its line harmless.

## Proxy

`frontend/next.config.ts` rewrites `/api/*` to the Django Ninja API, so the browser only talks to the Next origin and no CORS setup is needed.

Configured in `frontend/.env` (see `frontend/.env.example`):

| Variable             | Default                 | What it does                                  |
| -------------------- | ----------------------- | --------------------------------------------- |
| `BACKEND_URL`        | `http://localhost:8000` | Where the Django backend runs                 |
| `DJANGO_ADMIN_URL`   | empty                   | The admin's address, for the Admin link staff see in the sidebar. Empty: no link. |

In production (`DEBUG=False`) Django doesn't serve its static files (the admin's CSS/JS). `make static` dumps them (`collectstatic`) into `backend/staticfiles/` (git-ignored); serve that folder at `/static/` from the web server in front of Django.

Some details make this work:

- `skipTrailingSlashRedirect` is on. Otherwise Next redirects Django's URLs that end with a slash to the slashless form and Django redirects them back, forever.
- The rules use `:path(.*)` so the trailing slash Django expects is kept.
- `CSRF_TRUSTED_ORIGINS` in `backend/.env` includes `http://localhost:3000`. Without it, POSTs that come through the proxy (like the login) fail the CSRF origin check.

> **Note:** in production only the Next server may reach Django: keep port 8000 on a private network or behind a firewall. Django trusts the `X-Forwarded-Host` and `X-Forwarded-Proto` headers (`USE_X_FORWARDED_HOST`, `SECURE_PROXY_SSL_HEADER`), and anyone who reaches it directly can fake them.

> **Note:** in production put a load balancer or reverse proxy in front of Next that appends the client's address to `X-Forwarded-For` (or overwrites the header). Django takes the client's IP from its last entry, and Next passes on whatever header the client sent. Without that proxy, any client picks its own IP on every request: the per-IP rate limits (`API_THROTTLE_ANON`, `AUTH_LOGIN_THROTTLE_IP`) stop nothing, and `xip` in the logs is whatever the client says. The per-email login limit still holds.

> **Note:** the admin needs Django reachable, while the API only needs the Next server to reach it. In production, open only `/admin/` and `/static/` to the people who use it (IP allowlist, VPN) and keep the rest of port 8000 private.
