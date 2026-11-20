"""Scheduled jobs of the notes (listed in CRON_TASK_MODULES). Like every new
job, it starts disabled: turn it on in Admin › Cron."""

from django.conf import settings
from django.tasks import task

from modules.cron.registry import scheduled

from . import services


@scheduled("0 4 * * *")
@task(queue_name="scheduled_tasks")
def delete_old_notes() -> None:
    """Daily: deletes the notes untouched for NOTE_RETENTION_DAYS (0 keeps them)."""
    if settings.NOTE_RETENTION_DAYS > 0:
        services.delete_old_notes(settings.NOTE_RETENTION_DAYS)
