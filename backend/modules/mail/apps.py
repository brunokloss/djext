from django.apps import AppConfig


class MailConfig(AppConfig):
    name = "modules.mail"
    verbose_name = "Mail"

    def ready(self):
        # post_office tells a Celery worker about each email it queues; we make a
        # task for each, which the worker sends.
        from django.db import transaction
        from post_office.signals import email_queued

        from .tasks import send_email

        def enqueue_tasks(sender, emails, **kwargs):
            for email in emails:
                # After the commit, or the worker may not see the email yet.
                transaction.on_commit(lambda pk=email.pk: send_email.enqueue(pk))

        email_queued.connect(
            enqueue_tasks, weak=False, dispatch_uid="mail.enqueue_tasks"
        )
