"""The database cache in the admin, as an ordinary model list: search the keys,
see when they expire and how big they are, delete some (the standard "delete
selected"; select all to clear the cache). Superusers only. There is nothing to
do about expired entries: the cache drops them on its own.

The value is never in the list: "Reveal" shows it, and each reveal is sent as
`action_performed` (modules/audit logs it). Only with the database cache; with
Redis (CACHE_URL) there is no table to show.
"""

import base64
import pickle
from urllib.parse import quote, unquote

from django.conf import settings
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models.functions import Length
from django.http import Http404
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html
from django.utils.timesince import timeuntil

from modules.signals.signals import action_performed

from .models import CacheEntry

REVEAL_LIMIT = 10_000


class CacheEntryAdmin(admin.ModelAdmin):
    list_display = ("cache_key", "expires_at", "expires_in", "size")
    search_fields = ("cache_key",)
    ordering = ("cache_key",)
    fields = ("cache_key", "expires_at", "expires_in", "size", "reveal")
    readonly_fields = fields

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_size=Length("value"))

    @admin.display(description="expires", ordering="expires")
    def expires_at(self, obj):
        # The admin's own format has no seconds.
        return date_format(timezone.localtime(obj.expires), "Y-m-d H:i:s")

    @admin.display(description="expires in", ordering="expires")
    def expires_in(self, obj):
        now = timezone.now()
        if obj.expires <= now:
            return "expired"
        seconds = int((obj.expires - now).total_seconds())
        # timeuntil() starts at minutes: "9 minutes", "2 days".
        return (
            f"{seconds} seconds"
            if seconds < 60
            else timeuntil(obj.expires, now, depth=1)
        )

    @admin.display(description="size", ordering="_size")
    def size(self, obj):
        return obj._size

    @admin.display(description="value")
    def reveal(self, obj):
        url = reverse("admin:cache_cacheentry_reveal", args=[quote(obj.pk)])
        return format_html('<a href="{}">Reveal (logged)</a>', url)

    # Superusers only, and nobody adds or edits: the cache writes the rows.
    def has_module_permission(self, request):
        return request.user.is_superuser

    has_view_permission = has_delete_permission = lambda self, request, obj=None: (
        request.user.is_superuser
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path(
                "<path:object_id>/reveal/",
                self.admin_site.admin_view(self.reveal_view),
                name="cache_cacheentry_reveal",
            ),
            *super().get_urls(),
        ]

    def reveal_view(self, request, object_id):
        if not self.has_view_permission(request):
            raise PermissionDenied
        entry = self.get_object(request, unquote(object_id))
        if entry is None:
            raise Http404
        text = repr(pickle.loads(base64.b64decode(entry.value)))  # noqa: S301
        if len(text) > REVEAL_LIMIT:
            text = text[:REVEAL_LIMIT] + f"… ({len(text) - REVEAL_LIMIT} more)"
        action_performed.send(
            None, request=request, name="cache.reveal", values={"key": entry.cache_key}
        )
        return render(
            request,
            "admin/cache/cacheentry/reveal.html",
            {
                **self.admin_site.each_context(request),
                "title": "Cache value",
                "opts": self.model._meta,
                "entry": entry,
                "value": text,
            },
        )


# Nothing to show with Redis: no table.
if settings.CACHES["default"]["BACKEND"].endswith("db.DatabaseCache"):
    admin.site.register(CacheEntry, CacheEntryAdmin)
