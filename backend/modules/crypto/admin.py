from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline

from .crypto import shred
from .models import Keyset


@admin.register(Keyset)
class KeysetAdmin(admin.ModelAdmin):
    """Who has a key. Keys are made on first use; deleting one here shreds
    it: that owner's encrypted data can't be read again."""

    list_display = ("__str__", "owner_type", "owner_id", "created_at")
    list_filter = ("owner_type",)
    search_fields = ("owner_id",)
    fields = ("owner_type", "owner_id", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def delete_model(self, request, obj):
        model = obj.owner_type.model_class()
        owner = model and model._default_manager.filter(pk=obj.owner_id).first()
        if owner is None:
            # The owner is gone: nothing to name in the log.
            obj.delete()
        else:
            shred(request, owner)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self.delete_model(request, obj)


class KeysetInline(GenericTabularInline):
    """An owner's key, read only, on the owner's page in the admin (say the
    user's). Shredding stays in the Keyset admin, where deleting is explicit."""

    model = Keyset
    ct_field = "owner_type"
    ct_fk_field = "owner_id"
    fields = ("public_id", "created_at")
    readonly_fields = fields
    extra = 0
    max_num = 1

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
