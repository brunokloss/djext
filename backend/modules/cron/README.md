# Cron

`modules/cron` runs jobs on a schedule, on top of Django's tasks stored in the database (`django-tasks-db`, no broker). Two processes, both started by `make dev`: `manage.py db_worker` runs the tasks and `manage.py db_scheduler` enqueues the ones that are due, once a minute. Only one scheduler is active at a time (a Postgres advisory lock; on SQLite just run one).

In production, `modules/cron/Procfile` (optional) keeps several workers running with honcho: `cd backend && uv run --with honcho honcho -f modules/cron/Procfile -d . start`. The scheduler runs as its own service.

Declare a job with a cron expression, in a module listed in `CRON_TASK_MODULES` (`config/settings.py`):

```python
from django.tasks import task
from modules.cron.registry import scheduled


@scheduled("0 4 * * *")
@task(queue_name="scheduled_tasks")
def clean_up(): ...
```

Each job gets a row in the admin (Cron). `@scheduled` goes above `@task`; on anything else it raises a `TypeError` when the module loads. A new job starts **disabled**, so a deploy never turns cron on by itself (`CRON_AUTO_ENABLE_NEW_TASKS=True` starts them enabled, and `@scheduled(..., enabled=True)` or `enabled=False` decides it for one job). With `DEBUG=True` there are also three jobs to watch it work: `test_heartbeat` logs a line every minute, `test_always_fails` raises on purpose, to see a failure in the admin and the logs, and `test_email` queues the `welcome` email every 5 minutes, a sample of a recurring one (the worker prints it). All start off (even with `CRON_AUTO_ENABLE_NEW_TASKS`): turn them on in the admin. There you enable, pause, override the expression, see the next run and the last runs, and press "Schedule now". A minute the scheduler missed is skipped, not caught up. The module ships the housekeeping jobs, daily around 05:00 UTC and on from the start, so no table of logs or history grows forever:

| Job | Deletes | Kept for |
| --- | --- | --- |
| `task_result_purge` | finished task results and the cron's run history | `TASK_RESULT_RETENTION_DAYS` (7) |
| `audit_purge` | audit logs (nothing without `modules/audit`) | `AUDIT_RETENTION_DAYS` (1825) |
| `idempotency_purge` | idempotency keys | `IDEMPOTENCY_TTL_HOURS` (24) |
| `mail_purge` | sent emails, their logs and attachments | `EMAIL_RETENTION_DAYS` (30) |
| `session_purge` | expired sessions | `SESSION_COOKIE_AGE` (2 weeks) |
| `admin_log_purge` | the admin's own history (`django_admin_log`) | `ADMIN_LOG_RETENTION_DAYS` (1825) |
| `cache_purge` | the database cache's expired entries, 5,000 per delete (nothing with Redis or without `modules/cache`) | until they expire |

0 keeps everything where a setting allows it. Without `cache_purge`, expired cache entries would stay until the table passed `CACHE_MAX_ENTRIES`, when one write would delete them all inside a request.

## Depends on

The packages `croniter` and `django-tasks-db` (`django_tasks_db` in `INSTALLED_APPS`, plus `TASKS`), and a worker (`manage.py db_worker`) to run what it enqueues. More than one scheduler needs Postgres. Its jobs call `audit`, `cache`, `idempotency` and `mail` by command name and do nothing when those are removed.

## Removing it

Delete `backend/modules/cron/` and these lines: `INSTALLED_APPS` in `config/settings.py` (`django_tasks_db` can go too, if nothing else uses tasks), plus `TASKS`, the `CRON_*` settings and the `DBTaskResult` line in `AUDIT_MODELS`. `make dev` stops starting the worker and the scheduler. Its tables stay in the database until you drop them.
