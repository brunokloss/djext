from django.contrib import admin

from .models import IdempotencyKey


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    """Read-only, to look into a retry. Deleting a key lets the next request
    with it run again."""

    list_display = ("key", "user", "state", "status", "created_at")
    list_filter = ("state", "status")
    search_fields = ("key", "user__email")
    list_select_related = ("user",)
    fields = (
        "key",
        "user",
        "state",
        "status",
        "content_type",
        "fingerprint",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
