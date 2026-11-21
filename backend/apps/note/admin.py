from django.contrib import admin

from .models import Note


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "created_at"]
    search_fields = ["title", "owner__email"]
    list_select_related = ["owner"]
    raw_id_fields = ["owner"]
    readonly_fields = ["public_id", "created_at", "updated_at"]
