"""Scheduled jobs of the audit log, found by modules/cron (nothing runs them
without it: `manage.py audit_purge` then)."""

from django.core.management import call_command
from django.tasks import task

from modules.cron.registry import scheduled


@scheduled("0 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def audit_purge() -> None:
    """Daily: delete audit logs older than AUDIT_RETENTION_DAYS."""
    call_command("audit_purge")
