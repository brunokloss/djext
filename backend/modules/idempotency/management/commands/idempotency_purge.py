from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from modules.idempotency.models import IdempotencyKey

# Deleted in slices, so a big backlog doesn't hold one long lock.
BATCH = 10_000


class Command(BaseCommand):
    help = (
        "Delete idempotency keys older than IDEMPOTENCY_TTL_HOURS. "
        "Run it from cron, e.g. once a day."
    )

    def handle(self, *args, **options):
        hours = settings.IDEMPOTENCY_TTL_HOURS
        old = IdempotencyKey.objects.filter(
            created_at__lt=timezone.now() - timedelta(hours=hours)
        )
        total = 0
        while pks := list(old.values_list("pk", flat=True)[:BATCH]):
            total += IdempotencyKey.objects.filter(pk__in=pks).delete()[0]
        self.stdout.write(f"Deleted {total} idempotency keys older than {hours} hours.")
