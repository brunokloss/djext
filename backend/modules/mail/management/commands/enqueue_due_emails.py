from django.core.management.base import BaseCommand
from django_tasks_db.models import DBTaskResult
from post_office.mail import get_queued

from modules.mail.tasks import send_email


class Command(BaseCommand):
    help = (
        "Make the send task of each email that is due and has none yet: the ones "
        "whose retry time came (POST_OFFICE RETRY_INTERVAL) and the ones scheduled "
        "for later. modules/cron runs it every minute."
    )

    def handle(self, *args, **options):
        waiting = {
            args["args"][0]
            for args in DBTaskResult.objects.filter(
                task_path=f"{send_email.func.__module__}.{send_email.func.__name__}",
                status__in=["READY", "RUNNING"],
            ).values_list("args_kwargs", flat=True)
        }
        for email in get_queued():
            if email.pk not in waiting:
                send_email.enqueue(email.pk)
