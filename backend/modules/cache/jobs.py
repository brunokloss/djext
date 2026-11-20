"""Scheduled jobs of the database cache, found by modules/cron (nothing runs
them without it: `manage.py cache_purge` then)."""

from django.core.management import call_command
from django.tasks import task

from modules.cron.registry import scheduled


@scheduled("25 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def cache_purge() -> None:
    """Daily: delete the database cache's expired entries, a batch at a time,
    so no request ever pays for deleting a big backlog. Nothing with Redis."""
    call_command("cache_purge")
