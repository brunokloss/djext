from django import template
from django.contrib.admin.views.main import PAGE_VAR
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator

from ..admin import diff_table
from ..models import AuditLog

register = template.Library()


@register.simple_tag(takes_context=True)
def audit_history(context, obj):
    """The object's logs, a page at a time, like the admin's own History:
    100 per page, ?p=<page>. Filtered by ?action= (any number) and ?actor=; ?changed=1
    shows only the fields that changed."""
    query = context["request"].GET
    logs = AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(obj), object_id=str(obj.pk)
    )
    # Everyone who appears in this object's history, for the filter.
    actors = get_user_model().objects.filter(
        pk__in=logs.exclude(actor=None).values("actor")
    )

    actions = [a for a in query.getlist("action") if a in AuditLog.Action.values]
    if actions:
        logs = logs.filter(action__in=actions)
    actor = query.get("actor", "")
    if actor.isdigit():
        logs = logs.filter(actor_id=actor)

    paginator = Paginator(logs.select_related("content_type", "actor"), 100)
    page = paginator.get_page(query.get(PAGE_VAR))
    # The filters, kept on the page links.
    filters = query.copy()
    filters.pop(PAGE_VAR, None)
    return {
        "logs": page,
        "page_range": paginator.get_elided_page_range(page.number),
        "pagination_required": paginator.count > 100,
        "page_var": PAGE_VAR,
        "filters": filters.urlencode(),
        "action_choices": AuditLog.Action.choices,
        # None picked is all of them: all come checked.
        "actions": actions or AuditLog.Action.values,
        "actors": actors,
        "actor": actor,
        "only_changed": query.get("changed") == "1",
    }


@register.simple_tag
def audit_diff(log, only_changed=False):
    return diff_table(log, only_changed)
