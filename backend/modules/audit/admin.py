from django.apps import apps
from django.contrib import admin
from django.contrib.admin.templatetags.admin_urls import admin_urlname
from django.contrib.auth.models import Permission
from django.core.exceptions import FieldDoesNotExist
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html, format_html_join
from django.utils.http import urlencode
from django.utils.safestring import mark_safe

from .models import AuditLog

# The admin's own colors, so they follow its light and dark themes.
ADDED = "background: var(--message-success-bg);"
REMOVED = "background: var(--message-error-bg);"
CHANGED = "background: var(--message-warning-bg);"

CELL = (
    '<td style="padding: 4px 8px; vertical-align: top; font-family: monospace;'
    ' white-space: pre-wrap; word-break: break-word;">{}</td>'
)
ROW = (
    '<tr style="{}"><th style="text-align: left; padding: 4px 8px;'
    ' vertical-align: top; white-space: nowrap;">{}</th>' + CELL + CELL + "</tr>"
)


def link(model, object_id, fallback=""):
    """🔗 to the object's admin page, its name when it has none, or ❌ when
    it no longer exists. Plain text when there is no object id."""
    if not object_id:
        # A failed login names no object: only the email typed in, if any.
        return format_html("{}", fallback) if fallback else "—"
    target = model._base_manager.filter(pk=object_id).first() if model else None
    return link_to(target, fallback or object_id)


def link_to(target, fallback):
    if target is None:
        return format_html('<span title="Deleted">❌</span> {}', fallback)
    label = format_html("{}{}", target, perm_tag(target))
    try:
        url = reverse(admin_urlname(target._meta, "change"), args=[target.pk])
    except NoReverseMatch:
        return label
    return format_html('<a href="{}">🔗 {}</a>', url, label)


def perm_tag(target):
    """For a permission, what user.has_perm() takes: "auth.add_group"."""
    if not isinstance(target, Permission):
        return ""
    return format_html(
        " <code>{}.{}</code>", target.content_type.app_label, target.codename
    )


def diff_table(log, only_changed=False):
    """Every field, before and after: green when added, red when removed,
    yellow when changed. Or only those, with only_changed."""
    if log.action == AuditLog.Action.M2M:
        return m2m_list(log)

    old = log.old_values or {}
    new = log.new_values or {}
    if not old and not new:
        return "—"
    rows = []
    for key in sorted(old.keys() | new.keys()):
        if key not in old:
            style = ADDED
        elif key not in new:
            style = REMOVED
        elif old[key] != new[key]:
            style = CHANGED
        elif only_changed:
            continue
        else:
            style = ""
        rows.append((style, key, old.get(key, "—"), new.get(key, "—")))
    if not rows:
        return "—"

    return mark_safe(
        # min-width: the readonly field shrinks to its content otherwise.
        '<table style="border-collapse: collapse; width: 100%; min-width: 900px;">'
        '<thead><tr style="border-bottom: 1px solid #ccc;">'
        '<th style="text-align: left; padding: 4px 8px;">Field</th>'
        '<th style="text-align: left; padding: 4px 8px; width: 45%;">Before</th>'
        '<th style="text-align: left; padding: 4px 8px; width: 45%;">After</th>'
        "</tr></thead><tbody>"
        f"{format_html_join('', ROW, rows)}</tbody></table>"
    )


def m2m_list(log):
    """ADD on groups (Group), then each one."""
    payload = log.new_values or {}
    field = payload.get("field", "")
    header = format_html(
        '<div style="margin-bottom: 8px;"><strong>{}</strong> on <code>{}</code>'
        " ({})</div>",
        str(payload.get("operation", "")).upper(),
        field,
        payload.get("related_model", ""),
    )
    ids = payload.get("related_ids") or []
    if not ids:
        return mark_safe(f"{header}<em>—</em>")
    model = log.content_type.model_class() if log.content_type else None
    try:
        related = model._meta.get_field(field).related_model if model else None
    except FieldDoesNotExist:
        related = None
    # One query for all of them (with the permissions' content types).
    targets = {}
    if related:
        rows = related._base_manager.filter(pk__in=ids)
        if related is Permission:
            rows = rows.select_related("content_type")
        targets = {str(row.pk): row for row in rows}
    links = ((link_to(targets.get(str(pk)), pk),) for pk in ids)
    items = format_html_join("", "<li>{}</li>", links)
    return mark_safe(f'{header}<ul style="margin: 0; padding-left: 20px;">{items}</ul>')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read only: logs are never edited, and only go when their subject does."""

    list_display = (
        "created_at",
        "action",
        "name",
        "content_type",
        "object_repr",
        "actor",
        "origin",
        "ip_address",
    )
    list_filter = ("action", "origin", "content_type", "name")
    search_fields = (
        "name",
        "object_id",
        "object_repr",
        "actor__email",
        "actor__username",
        "session_hash",
        "request_id",
    )
    date_hierarchy = "created_at"
    list_select_related = ("content_type", "actor")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    ("content_type", "object_id"),
                    "created_at",
                    ("action", "name"),
                    "object_link",
                    "subject_links",
                ),
            },
        ),
        ("Changes", {"fields": ("diff",)}),
        (
            "Author",
            {
                "fields": (
                    ("actor", "origin"),
                    ("ip_address", "user_agent"),
                    ("session_link", "request_link"),
                ),
            },
        ),
        ("Raw", {"fields": (("old_values", "new_values"),), "classes": ("collapse",)}),
    )
    readonly_fields = (
        "id",
        "content_type",
        "object_id",
        "created_at",
        "action",
        "name",
        "object_link",
        "subject_links",
        "diff",
        "actor",
        "origin",
        "ip_address",
        "user_agent",
        "session_link",
        "request_link",
        "old_values",
        "new_values",
    )

    @admin.display(description="Object")
    def object_link(self, obj):
        model = obj.content_type.model_class() if obj.content_type else None
        return link(model, obj.object_id, obj.object_repr)

    @admin.display(description="Subjects")
    def subject_links(self, obj):
        links = []
        for key in obj.subjects:
            label, pk = key.split(":", 1)
            try:
                model = apps.get_model(label)
            except LookupError:
                model = None
            links.append((label, link(model, pk)))
        return format_html_join(", ", "{}: {}", links) or "—"

    @admin.display(description="Diff")
    def diff(self, obj):
        return diff_table(obj)

    def same(self, field, value):
        """🔗 to every log with the same value, and how many there are."""
        if not value:
            return "—"
        count = AuditLog.objects.filter(**{field: value}).count()
        url = reverse("admin:audit_auditlog_changelist")
        query = urlencode({field: value})
        logs = "log" if count == 1 else "logs"
        html = '<a href="{}?{}">🔗 {}</a> ({} {})'
        return format_html(html, url, query, value, count, logs)

    @admin.display(description="Session hash")
    def session_link(self, obj):
        """Groups what one login did: everything logged with this session."""
        return self.same("session_hash", obj.session_hash)

    @admin.display(description="Request id")
    def request_link(self, obj):
        return self.same("request_id", obj.request_id)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
