from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from modules.cache.caches import CACHE_TABLE
from modules.cache.models import CacheEntry

# Rows per DELETE, so a big backlog never holds the table for long.
BATCH = 5_000


def purge_expired(batch: int = BATCH) -> int:
    """Deletes the expired rows of the database cache, a batch at a time.
    Returns how many. Without it they stay until a read of that key, or until
    the table passes MAX_ENTRIES and one unlucky write deletes them all."""
    now = timezone.now()
    total = 0
    while True:
        keys = list(
            CacheEntry.objects.filter(expires__lt=now).values_list(
                "cache_key", flat=True
            )[:batch]
        )
        if not keys:
            return total
        total += CacheEntry.objects.filter(cache_key__in=keys).delete()[0]


class Command(BaseCommand):
    help = "Delete the expired entries of the database cache (nothing with Redis)."

    def handle(self, *args, **options):
        cache = settings.CACHES["default"]
        if cache.get("LOCATION") != CACHE_TABLE or "DatabaseCache" not in cache.get(
            "BACKEND", ""
        ):
            self.stdout.write("The cache is not the database: nothing to purge.")
            return
        self.stdout.write(f"Deleted {purge_expired()} expired cache entries.")
