"""Turns CACHE_URL into Django's `CACHES`."""

# The database cache's table: made by this module's migration, read by
# Django's DatabaseCache and shown in the admin (models.CacheEntry).
CACHE_TABLE = "cache"


def caches_from_url(url: str, *, max_entries: int) -> dict:
    """Empty: the database cache (an UNLOGGED table on Postgres, made by
    this module's migration). `redis://` or `rediss://`: Redis, through
    Django's own backend.
    Never put anything in the cache that you cannot rebuild.

    Database cache cost: Django runs `SELECT COUNT(*)` on the table at every write
    to enforce MAX_ENTRIES, and that is O(n) on Postgres. Fine for light use; with
    heavy writes, or a table near a million rows, use Redis."""
    if not url:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.db.DatabaseCache",
                "LOCATION": CACHE_TABLE,
                "OPTIONS": {"MAX_ENTRIES": max_entries},
            }
        }
    if url.startswith(("redis://", "rediss://")):
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": url,
            }
        }
    raise ValueError("CACHE_URL must be empty (database) or start with redis://")
