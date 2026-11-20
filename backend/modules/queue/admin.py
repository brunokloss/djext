"""Tasks › Queue in the admin: what is waiting in the task and email queues,
how long it waited, and a warning when no worker seems to be running.
Superusers only.

Like modules/runtime, plain views hooked into admin.site (no model to register,
no admin template overridden). The page polls a JSON endpoint; the admin's home
shows the warning as a message.
"""

from django.conf import settings
from django.contrib import admin, messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_POST

from modules.signals.signals import action_performed

from .stats import STALLED_AFTER, stats
from .tasks import ping


def superuser_only(request):
    if not request.user.is_superuser:
        raise Http404


def queue_view(request):
    superuser_only(request)
    return render(
        request,
        "queue/queue.html",
        {
            **admin.site.each_context(request),
            "title": "Queue",
            "stats": stats(),
            "stats_url": reverse("admin:queue_stats"),
            "ping_url": reverse("admin:queue_ping"),
            "stalled_after": int(STALLED_AFTER.total_seconds()),
        },
    )


def stats_view(request):
    superuser_only(request)
    return JsonResponse(stats())


@require_POST
def ping_view(request):
    """Enqueues the test task and opens its result, to watch the worker run it."""
    superuser_only(request)
    result = ping.enqueue()
    action_performed.send(
        None, request=request, name="queue.ping", values={"task": result.id}
    )
    return redirect("admin:django_tasks_database_dbtaskresult_change", result.id)


def install():
    """Adds the page and its JSON to admin.site's URLs, Queue to its app list
    (the home page and the sidebar, next to Task Results), and the stalled
    warning to its home, for superusers."""
    site = admin.site
    get_urls = site.get_urls
    get_app_list = site.get_app_list
    index = site.index

    def urls():
        return [
            path("queue/", site.admin_view(queue_view), name="queue"),
            path("queue/stats/", site.admin_view(stats_view), name="queue_stats"),
            path("queue/ping/", site.admin_view(ping_view), name="queue_ping"),
            *get_urls(),
        ]

    def app_list(request, app_label=None):
        apps = get_app_list(request, app_label)
        # Inside the group the settings say (ADMIN_APP_GROUPS["queue"], the tasks
        # one), else in the "System" group that modules/runtime may have made
        # (list this module after it in INSTALLED_APPS), else a group of its own.
        wanted = settings.ADMIN_APP_GROUPS.get("queue")
        if not request.user.is_superuser or app_label not in (None, wanted, "system"):
            return apps
        queue = {
            "name": "Queue",
            "object_name": "Queue",
            "perms": {"add": False, "change": False, "delete": False, "view": True},
            "admin_url": reverse("admin:queue"),
            "add_url": None,
            "view_only": True,
        }
        by_label = {app["app_label"]: app for app in apps}
        target = by_label.get(wanted) or by_label.get("system")
        if target is not None:
            target["models"] = sorted(
                [*target["models"], queue], key=lambda model: model["name"]
            )
            return apps
        system = {
            "name": "System",
            "app_label": "system",
            "app_url": "",
            "has_module_perms": True,
            "models": [queue],
        }
        return [*apps, system]

    def home(request, extra_context=None):
        if request.user.is_superuser and stats()["stalled"]:
            messages.warning(
                request,
                f"The worker seems stopped: something has been waiting for more "
                f"than {int(STALLED_AFTER.total_seconds())} s. See Tasks › Queue.",
            )
        return index(request, extra_context)

    site.get_urls = urls
    site.get_app_list = app_list
    site.index = home
