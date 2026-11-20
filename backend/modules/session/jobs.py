"""Scheduled jobs of the sessions, found by modules/cron."""

from django.core.management import call_command
from django.tasks import task

from modules.cron.registry import scheduled


@scheduled("15 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def session_purge() -> None:
    """Daily: delete expired sessions (Django's `clearsessions`, on this
    module's session store)."""
    call_command("clearsessions")
