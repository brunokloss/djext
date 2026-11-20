# The backend's production image: Django on granian, which also serves the
# admin's CSS/JS at /static/ (DEBUG off, Django doesn't). One image for every
# process; the command picks which (see docs/deployment.md):
#   web        the default, granian on :8000
#   migrate    python manage.py migrate --noinput (once per release)
#   worker     python manage.py db_worker --queue-name default,scheduled_tasks
#   scheduler  python manage.py db_scheduler
# Settings come from the environment, as in backend/.env.example.

FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.10.6 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first: this layer is rebuilt only when the lock changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY . .
# The admin's CSS/JS into STATIC_ROOT. Settings need a SECRET_KEY to load;
# this one only lives in this build step.
RUN SECRET_KEY=collectstatic .venv/bin/python manage.py collectstatic --noinput --clear

FROM python:3.14-slim
RUN useradd --system --uid 1000 --no-create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
# Workers and threads: GRANIAN_WORKERS and GRANIAN_BLOCKING_THREADS.
CMD ["granian", "--interface", "wsgi", "--host", "0.0.0.0", "--port", "8000", \
     "--static-path-route", "/static", "--static-path-mount", "/app/staticfiles", \
     "config.wsgi:application"]
