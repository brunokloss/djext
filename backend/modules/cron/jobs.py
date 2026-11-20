"""The cron's own jobs: its run history, Django's task results and admin log,
and the development jobs. Every other job lives in its module's `jobs.py`
(`modules/audit/jobs.py`, ...), which the scheduler finds by itself."""

import logging
import random
import time
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.tasks import task
from django.utils import timezone

from .models import CronRun
from .registry import scheduled

logger = logging.getLogger(__name__)


@scheduled("0 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def task_result_purge() -> None:
    """Daily: delete finished task results and cron runs older than
    TASK_RESULT_RETENTION_DAYS.

    Results go through django-tasks-db's own command, so its retention rules
    stay its own. The runs only point at results, which are gone by then.
    """
    days = settings.TASK_RESULT_RETENTION_DAYS
    call_command("prune_db_task_results", min_age_days=days, queue_name="*")
    cutoff = timezone.now() - timedelta(days=days)
    count, _ = CronRun.objects.filter(created_at__lt=cutoff).delete()
    logger.info("task_result_purge: deleted %s cron runs", count)


@scheduled("20 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def admin_log_purge() -> None:
    """Daily: delete the admin's history (django_admin_log) older than
    ADMIN_LOG_RETENTION_DAYS (0 keeps it)."""
    days = settings.ADMIN_LOG_RETENTION_DAYS
    if days <= 0 or not apps.is_installed("django.contrib.admin"):
        return
    from django.contrib.admin.models import LogEntry

    cutoff = timezone.now() - timedelta(days=days)
    count, _ = LogEntry.objects.filter(action_time__lt=cutoff).delete()
    logger.info("admin_log_purge: deleted %s entries", count)


# Only with DEBUG=True, to watch the scheduler and a worker work. Both start off,
# even with CRON_AUTO_ENABLE_NEW_TASKS: turn them on in Admin › Cron, or press
# "Schedule now".
if settings.DEBUG:

    @scheduled("* * * * *", enabled=False)
    @task(queue_name="scheduled_tasks")
    def test_heartbeat() -> None:
        """Once a minute: waits a little, so the elapsed time is not always 0."""
        time.sleep(random.uniform(0.05, 0.4))
        logger.info("test_heartbeat: the scheduler and the worker are alive")

    @scheduled("*/5 * * * *", enabled=False)
    @task(queue_name="scheduled_tasks")
    def test_always_fails() -> None:
        """Raises on purpose, to see a failure in the admin and the logs."""
        raise RuntimeError("test_always_fails: this job fails on purpose")
