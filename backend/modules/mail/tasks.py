from django.db import transaction
from django.tasks import task
from django.utils import timezone
from post_office.models import STATUS, Email
from post_office.settings import get_log_level, get_max_retries, get_retry_timedelta


@task
def send_email(email_id: int) -> None:
    """Send one email of the queue (a django-post-office row): one task per email.

    The row is locked in the database while it is sent, and skipped if another
    worker has it or it is no longer waiting (sent already, or its retry is
    still in the future). So a duplicate task does nothing, on any number of
    workers and machines.

    A failure is retried like post_office does (POST_OFFICE MAX_RETRIES and
    RETRY_INTERVAL): the email is requeued for later, and `enqueue_due_emails`
    (modules/cron) makes the task for the new attempt. After the last one it is
    `failed`.
    """
    now = timezone.now()
    with transaction.atomic():
        email = (
            Email.objects.select_for_update(skip_locked=True)
            .filter(pk=email_id, status__in=[STATUS.queued, STATUS.requeued])
            .exclude(scheduled_time__gt=now)
            .exclude(expires_at__lte=now)
            .first()
        )
        if email is None:
            return
        try:
            # Renders the template and sends; commit=False raises on failure.
            email.dispatch(commit=False)
        except Exception as error:
            _failed(email, error)
        else:
            email.status = STATUS.sent
            email.save(update_fields=["status", "last_updated"])
            if get_log_level() >= 2:
                email.logs.create(status=STATUS.sent, message="", exception_type="")


def _failed(email: Email, error: Exception) -> None:
    retries = email.number_of_retries or 0
    if retries < get_max_retries():
        email.status = STATUS.requeued
        email.number_of_retries = retries + 1
        email.scheduled_time = timezone.now() + get_retry_timedelta()
    else:
        email.status = STATUS.failed
    email.save(
        update_fields=["status", "number_of_retries", "scheduled_time", "last_updated"]
    )
    if get_log_level() >= 1:
        email.logs.create(
            status=STATUS.failed,
            message=str(error),
            exception_type=type(error).__name__,
        )
