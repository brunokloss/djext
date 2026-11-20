from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from modules.signals.signals import action_performed

from .caches import CACHE_TABLE, caches_from_url
from .models import CacheEntry

User = get_user_model()


class CacheAdminTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_user(
            email="root@example.com", is_staff=True, is_superuser=True
        )
        self.client.force_login(self.root)
        cache.set("alpha", {"n": 1}, 60)
        cache.set("beta", "SECRET-VALUE", 60)
        self.alpha = CacheEntry.objects.get(cache_key__endswith=":alpha")

    def test_list_shows_keys_and_sizes_but_never_values(self):
        response = self.client.get(reverse("admin:cache_cacheentry_changelist"))
        self.assertContains(response, ":alpha")
        self.assertContains(response, ":beta")
        self.assertNotContains(response, "SECRET-VALUE")

    def test_expires_in_the_unit_that_fits(self):
        for delta, shown in [
            (timedelta(seconds=30), "seconds"),
            (timedelta(minutes=10), "minutes"),
            (timedelta(hours=5), "hours"),
            (timedelta(days=3), "days"),
        ]:
            CacheEntry.objects.filter(pk=self.alpha.pk).update(
                expires=timezone.now() + delta + timedelta(seconds=5)
            )
            response = self.client.get(
                reverse("admin:cache_cacheentry_changelist"), {"q": "alpha"}
            )
            self.assertContains(response, shown)

    def test_expires_has_date_and_time_with_seconds(self):
        when = timezone.now().replace(microsecond=0) + timedelta(minutes=10)
        CacheEntry.objects.filter(pk=self.alpha.pk).update(expires=when)
        response = self.client.get(
            reverse("admin:cache_cacheentry_changelist"), {"q": "alpha"}
        )
        shown = timezone.localtime(when).strftime("%Y-%m-%d %H:%M:%S")
        self.assertContains(response, shown)

    def test_expired_entry_says_so(self):
        CacheEntry.objects.filter(pk=self.alpha.pk).update(
            expires=timezone.now() - timedelta(seconds=5)
        )
        response = self.client.get(reverse("admin:cache_cacheentry_changelist"))
        self.assertContains(response, ">expired<")

    def test_search_by_key(self):
        response = self.client.get(
            reverse("admin:cache_cacheentry_changelist"), {"q": "alp"}
        )
        self.assertContains(response, ":alpha")
        self.assertNotContains(response, ":beta")

    def test_detail_has_no_value_just_the_reveal_link(self):
        response = self.client.get(
            reverse("admin:cache_cacheentry_change", args=[self.alpha.pk])
        )
        self.assertContains(response, "Reveal")
        self.assertNotContains(response, "{&#x27;n&#x27;")

    def test_reveal_shows_the_value_and_sends_the_signal(self):
        seen = []
        action_performed.connect(
            lambda **kw: seen.append(kw), weak=False, dispatch_uid="reveal"
        )
        try:
            response = self.client.get(
                reverse("admin:cache_cacheentry_reveal", args=[self.alpha.pk])
            )
        finally:
            action_performed.disconnect(dispatch_uid="reveal")
        self.assertContains(response, "{&#x27;n&#x27;: 1}")
        self.assertEqual(seen[0]["name"], "cache.reveal")
        self.assertEqual(seen[0]["values"], {"key": self.alpha.cache_key})

    def test_reveal_of_a_missing_key_is_404(self):
        response = self.client.get(
            reverse("admin:cache_cacheentry_reveal", args=["nope"])
        )
        self.assertEqual(response.status_code, 404)

    def test_long_values_are_cut(self):
        cache.set("big", "x" * 20_000, 60)
        entry = CacheEntry.objects.get(cache_key__endswith=":big")
        response = self.client.get(
            reverse("admin:cache_cacheentry_reveal", args=[entry.pk])
        )
        self.assertContains(response, "more)")

    def test_delete_selected_clears_the_cache(self):
        self.client.post(
            reverse("admin:cache_cacheentry_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [e.pk for e in CacheEntry.objects.all()],
                "post": "yes",
            },
        )
        self.assertIsNone(cache.get("alpha"))
        self.assertIsNone(cache.get("beta"))

    def test_nobody_can_add_or_edit(self):
        self.assertEqual(
            self.client.get(reverse("admin:cache_cacheentry_add")).status_code,
            403,
        )

    def test_staff_who_are_not_superusers_get_nothing(self):
        staff = User.objects.create_user(email="s@example.com", is_staff=True)
        self.client.force_login(staff)
        for name, args in [
            ("changelist", []),
            ("reveal", [self.alpha.pk]),
        ]:
            response = self.client.get(
                reverse(f"admin:cache_cacheentry_{name}", args=args)
            )
            self.assertEqual(response.status_code, 403, name)


class CacheTests(TestCase):
    def test_set_get_delete(self):
        cache.set("k", {"a": 1}, 60)
        self.assertEqual(cache.get("k"), {"a": 1})
        cache.delete("k")
        self.assertIsNone(cache.get("k"))

    def test_add_does_not_overwrite(self):
        self.assertTrue(cache.add("once", 1, 60))
        self.assertFalse(cache.add("once", 2, 60))
        self.assertEqual(cache.get("once"), 1)

    def test_table_is_unlogged_on_postgres(self):
        if connection.vendor != "postgresql":
            self.skipTest("UNLOGGED is Postgres only")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relpersistence FROM pg_class WHERE relname = %s", [CACHE_TABLE]
            )
            self.assertEqual(cursor.fetchone()[0], "u")


class CachesFromUrlTests(SimpleTestCase):
    def test_empty_is_the_database_cache(self):
        caches = caches_from_url("", max_entries=5)
        self.assertTrue(caches["default"]["BACKEND"].endswith("db.DatabaseCache"))
        self.assertEqual(caches["default"]["OPTIONS"]["MAX_ENTRIES"], 5)

    def test_redis(self):
        caches = caches_from_url("redis://localhost:6379/0", max_entries=5)
        self.assertTrue(caches["default"]["BACKEND"].endswith("redis.RedisCache"))
        self.assertEqual(caches["default"]["LOCATION"], "redis://localhost:6379/0")

    def test_other_schemes_fail(self):
        with self.assertRaises(ValueError):
            caches_from_url("memcached://x", max_entries=5)


class PurgeExpiredTest(TestCase):
    def test_deletes_only_the_expired_in_batches(self):
        from .management.commands.cache_purge_expired import purge_expired

        for i in range(5):
            cache.set(f"old{i}", i, timeout=60)
        cache.set("fresh", 1, timeout=3600)
        CacheEntry.objects.filter(cache_key__contains="old").update(
            expires=timezone.now() - timedelta(minutes=1)
        )
        self.assertEqual(purge_expired(batch=2), 5)
        self.assertEqual(cache.get("fresh"), 1)
        self.assertEqual(CacheEntry.objects.count(), 1)
