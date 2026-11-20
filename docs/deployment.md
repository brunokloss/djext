# Deployment

Each side has its own production image: `backend/Dockerfile` and `frontend/Dockerfile`. `make prod` builds both and runs them locally with DEBUG off, at http://localhost:3000. Stop `make dev` first, because they use the same ports.

`make prod-superuser` creates an admin in its database, `make prod-down` stops its containers and leaves the Postgres running, and `make prod-reset` deletes its database. The example users of `make db-seed` don't exist here, because they need DEBUG on.

## Backend

One image runs every process. The command you pass picks which one:

| Process   | Command                                                      | How many |
| --------- | ------------------------------------------------------------ | -------- |
| web       | the default: granian on :8000, also serving `/static/`       | any      |
| migrate   | `python manage.py migrate --noinput`                         | once per release, before the rest |
| worker    | `python manage.py db_worker --queue-name default,scheduled_tasks` | one or more (emails, cron jobs) |
| scheduler | `python manage.py db_scheduler`                              | one or more; one is active at a time (a Postgres lock) |

The settings come from the environment, as listed in `backend/.env.example`. Production needs these:

- `SECRET_KEY`: a fresh one.
- `DATABASE_URL`: Postgres.
- `ALLOWED_HOSTS`: the frontend's host, since Next forwards it, plus the host Next uses to reach Django.
- `CSRF_TRUSTED_ORIGINS`: the frontend's origin, plus Django's if the admin is opened there.
- `CRYPTO_KMS_URI`: an `aws-kms://` key. `check --deploy` refuses the fake one.

TLS ends at the load balancer, which also redirects HTTP to HTTPS (see `config/settings.py`). Granian's processes and threads are set with `GRANIAN_WORKERS` and `GRANIAN_BLOCKING_THREADS`.

## Frontend

You have two options.

- **Vercel**: import the repo with `frontend` as the root directory. Set the variables from `frontend/.env.example` in the project. `BACKEND_URL` points at the backend's public address. Nothing in the Dockerfile is used.
- **The image**: Next reads `BACKEND_URL`, `DJANGO_ADMIN_URL`, `STORAGE_BUCKET_URL`, `NEXT_PUBLIC_PROJECT_*` and `NEXT_PUBLIC_SENTRY_*` when it builds, so pass them as `--build-arg`. Set `BACKEND_URL` again at runtime with the same value. It serves on :3000.

In both cases, only Next should be public for the site, because it proxies `/api` to Django. Django itself is public only where the admin is opened (`DJANGO_ADMIN_URL`).
