"""Scheduled jobs of the idempotency keys, found by modules/cron (nothing runs
them without it: `manage.py idempotency_purge` then)."""

from django.core.management import call_command
from django.tasks import task

from modules.cron.registry import scheduled


@scheduled("10 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def idempotency_purge() -> None:
    """Daily: delete idempotency keys older than IDEMPOTENCY_TTL_HOURS."""
    call_command("idempotency_purge")
