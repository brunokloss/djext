from django.contrib import admin

from .models import BearerKey


class BearerKeyInline(admin.TabularInline):
    """The user's bearer key, on their page in the admin. Keys are made by
    their owner (/api/auth/bearer-key); deleting it here revokes it (the user
    admin's save_formset calls keys.revoke)."""

    model = BearerKey
    fields = ("prefix", "created_at", "updated_at")
    readonly_fields = fields
    extra = 0
    max_num = 1

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
