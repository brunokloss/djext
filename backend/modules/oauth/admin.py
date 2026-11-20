from django.contrib import admin

from .models import UserIdentity


@admin.register(UserIdentity)
class UserIdentityAdmin(admin.ModelAdmin):
    list_display = ("__str__", "user", "provider", "updated_at")
    list_filter = ("provider",)
    search_fields = ("uid", "user__email")
    list_select_related = ("user",)
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")
