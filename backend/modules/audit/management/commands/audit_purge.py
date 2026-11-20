from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from modules.audit.models import AuditLog

# Deleted in slices, so a big backlog doesn't hold one long lock.
BATCH = 10_000


class Command(BaseCommand):
    help = (
        "Delete audit logs older than AUDIT_RETENTION_DAYS (0 keeps everything). "
        "Run it from cron, e.g. once a day."
    )

    def handle(self, *args, **options):
        days = settings.AUDIT_RETENTION_DAYS
        if days <= 0:
            self.stdout.write("AUDIT_RETENTION_DAYS is 0: keeping every log.")
            return

        old = AuditLog.objects.filter(
            created_at__lt=timezone.now() - timedelta(days=days)
        )
        total = 0
        while pks := list(old.values_list("pk", flat=True)[:BATCH]):
            total += AuditLog.objects.filter(pk__in=pks).delete()[0]
        self.stdout.write(f"Deleted {total} audit logs older than {days} days.")
