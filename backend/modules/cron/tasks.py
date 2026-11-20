"""Jobs that come with the module. Yours go in your own module: list it in
`CRON_TASK_MODULES` (config/settings.py) and decorate with `@scheduled`."""

import logging
import random
import time
from datetime import timedelta

from django.apps import apps
from django.conf import settings
from django.core.management import call_command, get_commands
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


@scheduled("0 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def audit_purge() -> None:
    """Daily: delete audit logs older than AUDIT_RETENTION_DAYS.

    Called by name, not imported: modules don't import each other, and without
    modules/audit there is nothing to purge.
    """
    if "audit_purge" not in get_commands():
        logger.info("audit_purge: modules/audit is not installed, nothing to do")
        return
    call_command("audit_purge")


@scheduled("10 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def idempotency_purge() -> None:
    """Daily: delete idempotency keys older than IDEMPOTENCY_TTL_HOURS.

    Called by name, like audit_purge: without modules/idempotency there is
    nothing to purge.
    """
    if "idempotency_purge" not in get_commands():
        logger.info("idempotency_purge: modules/idempotency is not installed")
        return
    call_command("idempotency_purge")


@scheduled("25 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def cache_purge() -> None:
    """Daily: delete the database cache's expired entries, a batch at a time,
    so no request ever pays for deleting a big backlog.

    Called by name, like audit_purge: without modules/cache there is nothing to do.
    """
    if "cache_purge" in get_commands():
        call_command("cache_purge")


@scheduled("* * * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def enqueue_due_emails() -> None:
    """Every minute: makes the task of each email that is due and has none yet.
    Each email gets its task as it is queued; this catches the ones whose
    retry time came (POST_OFFICE RETRY_INTERVAL) and the ones scheduled for later.

    Called by name, like audit_purge: without modules/mail there is nothing to do.
    """
    if "enqueue_due_emails" in get_commands():
        call_command("enqueue_due_emails")


@scheduled("30 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def mail_purge() -> None:
    """Daily: delete emails older than EMAIL_RETENTION_DAYS (0 keeps them)."""
    days = settings.EMAIL_RETENTION_DAYS
    if days > 0 and "cleanup_mail" in get_commands():
        call_command("cleanup_mail", days=days, delete_attachments=True)


@scheduled("15 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def session_purge() -> None:
    """Daily: delete expired sessions (Django's `clearsessions`)."""
    call_command("clearsessions")


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

    @scheduled("*/5 * * * *", enabled=False)
    @task(queue_name="scheduled_tasks")
    def test_email() -> None:
        """Every 5 minutes: queues an email from the `welcome` template to
        DEFAULT_FROM_EMAIL, as a sample of a recurring email. In development the
        worker prints it. Copy it for a digest or a reminder."""
        if not apps.is_installed("post_office"):
            logger.info("test_email: django-post-office is not installed")
            return
        from post_office import mail

        # Idempotent: creates the example template if it isn't there.
        call_command("seed_email_templates", verbosity=0)
        mail.send(
            settings.DEFAULT_FROM_EMAIL,
            template="welcome",
            context={"name": "there", "url": "http://localhost:3000"},
            render_on_delivery=True,  # A broken template fails only this email.
        )
        logger.info("test_email: queued")
