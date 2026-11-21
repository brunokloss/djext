"""Scheduled jobs of the email queue, found by modules/cron. Without cron,
retries and scheduled emails wait until `manage.py enqueue_due_emails` runs."""

import logging

from django.conf import settings
from django.core.management import call_command
from django.tasks import task

from modules.cron.registry import scheduled

logger = logging.getLogger(__name__)


@scheduled("* * * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def enqueue_due_emails() -> None:
    """Every minute: makes the task of each email that is due and has none yet.
    Each email gets its task as it is queued; this catches the ones whose
    retry time came (POST_OFFICE RETRY_INTERVAL) and the ones scheduled for later."""
    call_command("enqueue_due_emails")


@scheduled("30 5 * * *", enabled=True)
@task(queue_name="scheduled_tasks")
def mail_purge() -> None:
    """Daily: delete emails older than EMAIL_RETENTION_DAYS (0 keeps them),
    with their logs and attachments."""
    days = settings.EMAIL_RETENTION_DAYS
    if days > 0:
        call_command("cleanup_mail", days=days, delete_attachments=True)


# Only with DEBUG=True. Starts off, even with CRON_AUTO_ENABLE_NEW_TASKS: turn it
# on in Admin › Cron, or press "Schedule now".
if settings.DEBUG:

    @scheduled("*/5 * * * *", enabled=False)
    @task(queue_name="scheduled_tasks")
    def test_email() -> None:
        """Every 5 minutes: queues an email from the `welcome` template to
        DEFAULT_FROM_EMAIL, as a sample of a recurring email. In development the
        worker prints it. Copy it for a digest or a reminder."""
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
