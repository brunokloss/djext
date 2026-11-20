from django.db import models

from .caches import CACHE_TABLE


class CacheEntry(models.Model):
    """A row of the database cache (the table this module's migration makes), shown
    in the admin. Never saved from here: the cache writes it."""

    cache_key = models.CharField(max_length=255, primary_key=True)
    # Base64 of a pickle: only read through the admin's Reveal.
    value = models.TextField()
    expires = models.DateTimeField()

    class Meta:
        managed = False
        db_table = CACHE_TABLE
        verbose_name = "cache entry"
        verbose_name_plural = "cache entries"

    class Audit:
        # Deleting entries is in the admin's history; Reveal is sent to the audit
        # log by the admin itself (action_performed).
        skip = True

    def __str__(self):
        return self.cache_key
