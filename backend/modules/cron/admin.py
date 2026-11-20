"""Admin for CronSchedule — enable/disable jobs and watch their recent runs.

The list and detail views surface each job's effective expression, next run, and
a strip of its last runs (coloured by django-tasks status), plus a "Schedule now"
action/button to enqueue a one-off run.

It also replaces the bare admin of django-tasks-db's task results (the page a
run links to) with a grouped, read-only one: status, timing, payload, the
traceback of a failed run, and a link back to the job that enqueued it.

Run history is resolved through the CronRun bridge table (the strong link), not by
string-matching DBTaskResult.task_path — so jobs that share a function, or get
renamed, still show the right history.
"""

import json
import logging
import traceback
from datetime import timedelta

from croniter import croniter
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from modules.cron.models import CronSchedule
from modules.cron.registry import (
    SCHEDULE_REGISTRY,
    enqueue_for_schedule,
    load_task_modules,
)

logger = logging.getLogger(__name__)

# django-tasks statuses: READY, RUNNING, FAILED, SUCCESSFUL.
STATUS_COLOR = {
    "SUCCESSFUL": "#22c55e",
    "RUNNING": "#3b82f6",
    "FAILED": "#ef4444",
    "READY": "#94a3b8",
}
# Glyph shown inside the status pill, per status.
STATUS_ICON = {
    "SUCCESSFUL": "✓",
    "RUNNING": "●",
    "FAILED": "✗",
    "READY": "○",
}


def _status_pill(status: str):
    """A rounded, coloured badge with a leading glyph for a task status.

    Falls back to a neutral grey pill for unknown statuses (e.g. PRUNED), so the
    same renderer is safe for both DBTaskResult.status and synthetic labels.
    """
    status = (status or "").upper()
    color = STATUS_COLOR.get(status, "#94a3b8")
    icon = STATUS_ICON.get(status, "·")
    return format_html(
        '<span style="display:inline-flex;align-items:center;gap:4px;'
        "background:{0}1a;color:{0};border:1px solid {0}59;padding:1px 9px;"
        "border-radius:999px;font-size:0.8em;font-weight:600;"
        'letter-spacing:0.02em;white-space:nowrap;">{1} {2}</span>',
        color,
        icon,
        status,
    )


def _elapsed(start, end) -> str:
    """Human duration between two datetimes, e.g. '1.4s', '2m13s', '—'.

    Returns an em dash unless both ends are present (a run that never started or
    hasn't finished yet has no meaningful elapsed time).
    """
    if not start or not end:
        return "—"
    secs = (end - start).total_seconds()
    if secs < 0:
        return "—"
    if secs < 1:
        return f"{secs * 1000:.0f}ms"
    if secs < 60:
        return f"{secs:.1f}s"
    minutes, rem = divmod(int(secs), 60)
    if minutes < 60:
        return f"{minutes}m{rem:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _code_expression(name: str) -> str:
    load_task_modules()
    entry = SCHEDULE_REGISTRY.get(name)
    return entry[0] if entry else ""


def _recent_results(schedule, limit: int):
    """Return the latest (CronRun, DBTaskResult|None) pairs for a schedule.

    Walks the strong link: CronRun rows (newest first) → their DBTaskResult by id.
    A None result means the task result was pruned but the run is still on record.
    """
    runs = list(schedule.runs.all()[:limit])
    if not runs:
        return []
    try:
        from django_tasks_db.models import DBTaskResult
    except ImportError:
        return [(run, None) for run in runs]
    by_id = {
        r.id: r
        for r in DBTaskResult.objects.filter(
            id__in=[run.task_result_id for run in runs]
        )
    }
    return [(run, by_id.get(run.task_result_id)) for run in runs]


def _fmt_dt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else "—"


def _humanize_delta(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 0:
        return "now"
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        return f"{total // 3600}h{(total % 3600) // 60}m"
    return f"{total // 86400}d{(total % 86400) // 3600}h"


class CronScheduleForm(forms.ModelForm):
    expression = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "style": "font-family:monospace;min-width:180px;",
                "placeholder": "e.g. */15 * * * *",
            }
        ),
    )

    class Meta:
        model = CronSchedule
        fields = ("expression", "enabled", "paused_until", "notes")


@admin.register(CronSchedule)
class CronScheduleAdmin(admin.ModelAdmin):
    form = CronScheduleForm
    list_display = (
        "job",
        "enabled",
        "effective_expression_display",
        "next_run_display",
        "last_enqueue_display",
        "recent_runs_squares",
    )
    list_filter = ("enabled", "is_last_enqueue_ok")
    search_fields = ("name", "expression", "notes")
    actions = ("action_enable", "action_disable", "action_schedule_now")
    readonly_fields = (
        "name",
        "code_expression_display",
        "next_run_display",
        "recent_runs_table",
        "last_seen_in_code",
        "last_run_at",
        "last_enqueue_at",
        "is_last_enqueue_ok",
        "last_enqueue_error",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    ("code_expression_display", "expression"),
                    ("enabled", "paused_until"),
                    "next_run_display",
                    "notes",
                )
            },
        ),
        ("Recent runs", {"fields": ("recent_runs_table",)}),
        (
            "Tracking",
            {
                "fields": (
                    "last_seen_in_code",
                    "last_run_at",
                    ("last_enqueue_at", "is_last_enqueue_ok"),
                    "last_enqueue_error",
                ),
                "classes": ("collapse",),
            },
        ),
    )
    change_form_template = "admin/cron/cronschedule/change_form.html"

    def has_add_permission(self, request):
        # Schedules are created by sync_schedules from the @scheduled functions in
        # code — a row needs a matching registry entry to ever fire. A hand-added
        # row would be orphaned, so adding via the admin is disabled.
        return False

    def has_delete_permission(self, request, obj=None):
        # sync_schedules would just recreate the row on next boot (the function
        # still exists in code), losing its run history and settings. To retire a
        # job, remove its @scheduled in code. So deleting via the admin is off.
        return False

    # ----- list display ------------------------------------------------------

    @admin.display(description="Name", ordering="name")
    def job(self, obj):
        """The module and function (`modules.cron.tasks.audit_purge`), not only the
        function: two modules can have jobs with the same function name."""
        entry = SCHEDULE_REGISTRY.get(obj.name)
        if entry is None:
            return obj.name  # No longer in code.
        func = entry[1].func
        return f"{func.__module__}.{func.__name__}"

    @admin.display(description="Expression (effective)")
    def effective_expression_display(self, obj):
        code_expr = _code_expression(obj.name)
        effective = obj.expression or code_expr or "(missing)"
        if obj.expression and code_expr and obj.expression != code_expr:
            return format_html(
                '{} <span style="color:#94a3b8;font-size:0.85em;">'
                "(override; code: {})</span>",
                effective,
                code_expr,
            )
        return effective

    @admin.display(description="Last enqueue")
    def last_enqueue_display(self, obj):
        if obj.last_enqueue_at is None:
            return "—"
        color = "#22c55e" if obj.is_last_enqueue_ok else "#ef4444"
        icon = "✓" if obj.is_last_enqueue_ok else "✗"
        label = "OK" if obj.is_last_enqueue_ok else "FAIL"
        return format_html(
            '<span title="{3}" style="display:inline-flex;align-items:center;gap:4px;'
            "background:{0}1a;color:{0};border:1px solid {0}59;padding:1px 9px;"
            'border-radius:999px;font-size:0.8em;font-weight:600;">{1} {2}</span>',
            color,
            icon,
            label,
            _fmt_dt(obj.last_enqueue_at),
        )

    @admin.display(description="Last 10 runs")
    def recent_runs_squares(self, obj):
        recent = _recent_results(obj, 10)
        if not recent:
            return format_html('<span style="color:#94a3b8;">{}</span>', "no runs yet")
        rows = []
        for run, result in recent:
            status = str(result.status).upper() if result else "READY"
            color = STATUS_COLOR.get(status, "#94a3b8")
            elapsed = _elapsed(
                getattr(result, "started_at", None),
                getattr(result, "finished_at", None),
            )
            tooltip = f"{run.enqueued_at:%Y-%m-%d %H:%M} · {status} · {elapsed}"
            rows.append((tooltip, color))
        return format_html_join(
            "",
            '<span title="{}" style="display:inline-block;width:13px;height:13px;'
            'background:{};margin-right:3px;border-radius:3px;vertical-align:middle;">'
            "</span>",
            rows,
        )

    @admin.display(description="Next run")
    def next_run_display(self, obj):
        expr = obj.expression or _code_expression(obj.name)
        if not expr:
            return "—"
        try:
            nxt = croniter(expr, timezone.now()).get_next(timezone.datetime)
        except Exception as e:
            return format_html('<span style="color:#ef4444;">Invalid: {}</span>', e)
        base = format_html(
            "{} UTC (in {})",
            nxt.strftime("%Y-%m-%d %H:%M"),
            _humanize_delta(nxt - timezone.now()),
        )
        if not obj.enabled:
            return format_html(
                '{} <span style="color:#94a3b8;">(disabled)</span>', base
            )
        if obj.paused_until and obj.paused_until > timezone.now():
            return format_html('{} <span style="color:#94a3b8;">(paused)</span>', base)
        return base

    # ----- detail display ----------------------------------------------------

    @admin.display(description="Expression (from code)")
    def code_expression_display(self, obj):
        return _code_expression(obj.name) or "(not registered in code)"

    @admin.display(description="Recent runs")
    def recent_runs_table(self, obj):
        recent = _recent_results(obj, 10)
        if not recent:
            return format_html('<em style="color:#94a3b8;">{}</em>', "no runs yet")
        change_url = "admin:django_tasks_database_dbtaskresult_change"
        td = "padding:7px 10px;border-bottom:1px solid #f1f5f9;"
        td_mono = td + "color:#64748b;font-family:monospace;font-size:0.92em;"
        rows = []
        for i, (run, result) in enumerate(recent):
            status = str(result.status).upper() if result else "PRUNED"
            started = getattr(result, "started_at", None)
            finished = getattr(result, "finished_at", None)
            if result is not None:
                try:
                    id_cell = format_html(
                        '<a href="{}" style="font-family:monospace;">{}</a>',
                        reverse(change_url, args=[result.id]),
                        str(result.id)[:8],
                    )
                except Exception:
                    id_cell = format_html("{}", str(result.id)[:8])
            else:
                id_cell = format_html(
                    '<span style="color:#cbd5e1;">{}</span>',
                    str(run.task_result_id)[:8],
                )
            zebra = "background:#fafafa;" if i % 2 else ""
            rows.append(
                format_html(
                    '<tr style="{}">'
                    '<td style="{}">{}</td>'
                    '<td style="{}">{}</td>'
                    '<td style="{}">{}</td>'
                    '<td style="{}text-align:right;">{}</td>'
                    '<td style="{}">{}</td>'
                    "</tr>",
                    zebra,
                    td_mono,
                    id_cell,
                    td_mono,
                    _fmt_dt(run.enqueued_at),
                    td_mono,
                    _fmt_dt(finished),
                    td_mono,
                    _elapsed(started, finished),
                    td,
                    _status_pill(status),
                )
            )
        th = (
            "padding:8px 10px;text-align:left;font-size:0.78em;font-weight:600;"
            "text-transform:uppercase;letter-spacing:0.04em;color:#64748b;"
            "border-bottom:2px solid #e2e8f0;"
        )
        return format_html(
            '<table style="border-collapse:collapse;width:100%;max-width:760px;'
            "font-size:0.9em;border:1px solid #e2e8f0;border-radius:8px;"
            'overflow:hidden;">'
            "<thead><tr>"
            '<th style="{0}">ID</th>'
            '<th style="{0}">Enqueued</th>'
            '<th style="{0}">Finished</th>'
            '<th style="{0}text-align:right;">Elapsed</th>'
            '<th style="{0}">Status</th>'
            "</tr></thead><tbody>{1}</tbody></table>",
            mark_safe(th),  # noqa: S308 — static, no user input
            mark_safe("".join(rows)),  # noqa: S308 — rows are SafeStrings from format_html
        )

    # ----- actions -----------------------------------------------------------

    @admin.action(description="Enable selected", permissions=["change"])
    def action_enable(self, request, queryset):
        n = queryset.update(enabled=True)
        self.message_user(request, f"{n} cron(s) enabled.", messages.SUCCESS)

    @admin.action(description="Disable selected", permissions=["change"])
    def action_disable(self, request, queryset):
        n = queryset.update(enabled=False)
        self.message_user(request, f"{n} cron(s) disabled.", messages.SUCCESS)

    @admin.action(
        description="Schedule now (enqueue once, ignore enabled flag)",
        permissions=["change"],
    )
    def action_schedule_now(self, request, queryset):
        load_task_modules()
        ok = err = 0
        for sched in queryset:
            if self._enqueue_now(sched, request.user):
                ok += 1
            else:
                err += 1
        level = messages.SUCCESS if err == 0 else messages.WARNING
        self.message_user(request, f"Enqueued {ok}, failed {err}.", level)

    # ----- "Schedule now" button (per-object URL) ----------------------------

    def get_urls(self):
        custom = [
            path(
                "<path:object_id>/schedule-now/",
                self.admin_site.admin_view(self.schedule_now_view),
                name="cron_cronschedule_schedule_now",
            ),
        ]
        return custom + super().get_urls()

    def schedule_now_view(self, request, object_id):
        # It changes things, so POST only (the admin checks the CSRF token): a
        # link or an <img> on another site must not be able to run a job.
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        sched = self.get_object(request, object_id)
        if sched is not None and not self.has_change_permission(request, sched):
            raise PermissionDenied
        if sched is None:
            self.message_user(request, "Not found.", messages.ERROR)
            return HttpResponseRedirect("../../")
        load_task_modules()
        if self._enqueue_now(sched, request.user):
            self.message_user(request, f"{sched.name} enqueued.", messages.SUCCESS)
        else:
            self.message_user(
                request, f"Failed to enqueue {sched.name}.", messages.ERROR
            )
        return HttpResponseRedirect("../")

    @staticmethod
    def _enqueue_now(sched, user) -> bool:
        """Enqueue a one-off run (with the strong link) and record the outcome."""
        entry = SCHEDULE_REGISTRY.get(sched.name)
        now = timezone.now()
        fields = [
            "last_enqueue_at",
            "is_last_enqueue_ok",
            "last_enqueue_error",
            "updated_at",
        ]
        if not entry:
            sched.last_enqueue_at = now
            sched.is_last_enqueue_ok = False
            sched.last_enqueue_error = "not registered in code"
            sched.save(update_fields=fields)
            return False
        try:
            enqueue_for_schedule(sched, entry[1], by=user)
            sched.last_enqueue_at = now
            sched.is_last_enqueue_ok = True
            sched.last_enqueue_error = ""
            sched.save(update_fields=fields)
            return True
        except Exception:
            logger.exception("schedule_now_failed", extra={"job": sched.name})
            sched.last_enqueue_at = now
            sched.is_last_enqueue_ok = False
            sched.last_enqueue_error = traceback.format_exc()
            sched.save(update_fields=fields)
            return False


# ---------------------------------------------------------------------------
# DBTaskResult — re-skin the third-party admin (django_tasks_db) in place.
#
# We don't touch the installed package: unregister its bare ModelAdmin and
# register a prettier, read-only one here, so the look matches CronSchedule and
# this app stays self-contained. Guarded so the app still imports if
# django_tasks_db is absent.
# ---------------------------------------------------------------------------

_MONO = "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;"
_CODE_BLOCK = (
    "margin:0;padding:10px 12px;background:#0f172a;color:#e2e8f0;border-radius:6px;"
    "font-size:0.82em;line-height:1.5;overflow:auto;max-height:420px;white-space:pre-wrap;"
    "word-break:break-word;" + _MONO
)


def _pretty_json(value):
    """Render a JSON-serialisable value as a syntax-neutral dark code block."""
    if value in (None, "", {}, []):
        return format_html('<span style="color:#94a3b8;">{}</span>', "—")
    try:
        text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except TypeError, ValueError:
        text = str(value)
    return format_html('<pre style="{}">{}</pre>', mark_safe(_CODE_BLOCK), text)  # noqa: S308


try:
    from django_tasks_db.models import DBTaskResult

    admin.site.unregister(DBTaskResult)

    @admin.register(DBTaskResult)
    class PrettyDBTaskResultAdmin(admin.ModelAdmin):
        """Read-only, grouped view of a task result with status pills + elapsed."""

        list_display = (
            "short_id",
            "task_name",
            "status_pill",
            "queue_name",
            "priority",
            "enqueued_at",
            "elapsed_display",
        )
        list_filter = ("status", "queue_name", "priority")
        search_fields = ("id", "task_path", "queue_name")
        ordering = ["-enqueued_at"]
        date_hierarchy = "enqueued_at"

        fieldsets = (
            (
                "Overview",
                {
                    "fields": (
                        ("status_pill", "queue_name", "priority"),
                        ("task_name", "schedule_link"),
                    )
                },
            ),
            (
                "Timing",
                {
                    "fields": (
                        ("enqueued_at", "run_after"),
                        ("started_at", "finished_at"),
                        "elapsed_display",
                    )
                },
            ),
            (
                "Payload",
                {"fields": ("args_kwargs_pretty", "return_value_pretty")},
            ),
            (
                "Failure",
                {
                    "classes": ("collapse",),
                    "fields": ("exception_class_path", "traceback_pretty"),
                },
            ),
            (
                "Internals",
                {
                    "classes": ("collapse",),
                    "fields": ("id", "task_path", "backend_name", "worker_ids_pretty"),
                },
            ),
        )

        def get_fieldsets(self, request, obj=None):
            """Failure is collapsed, except on a run that failed: that is why
            you opened the page."""
            fieldsets = super().get_fieldsets(request, obj)
            if obj is None or str(obj.status).upper() != "FAILED":
                return fieldsets
            return [
                (
                    name,
                    {**options, "classes": ()} if name == "Failure" else options,
                )
                for name, options in fieldsets
            ]

        # Everything is read-only: results are produced by the worker, never edited.
        def has_add_permission(self, request, obj=None):
            return False

        def has_change_permission(self, request, obj=None):
            return False

        def has_delete_permission(self, request, obj=None):
            return False

        def get_readonly_fields(self, request, obj=None):
            return [
                "id",
                "task_name",
                "task_path",
                "backend_name",
                "queue_name",
                "priority",
                "enqueued_at",
                "run_after",
                "started_at",
                "finished_at",
                "status_pill",
                "schedule_link",
                "elapsed_display",
                "args_kwargs_pretty",
                "return_value_pretty",
                "exception_class_path",
                "traceback_pretty",
                "worker_ids_pretty",
            ]

        # ----- list + detail displays ----------------------------------------

        @admin.display(description="ID", ordering="id")
        def short_id(self, obj):
            return format_html(
                '<span style="{}">{}</span>', mark_safe(_MONO), str(obj.id)[:8]
            )

        @admin.display(description="Task", ordering="task_path")
        def task_name(self, obj):
            # The whole path, "module.path.func": the same function name can
            # live in two modules.
            return (obj.task_path or "").removesuffix("__task__") or "—"

        @admin.display(description="Status", ordering="status")
        def status_pill(self, obj):
            return _status_pill(str(obj.status))

        @admin.display(description="Cron schedule")
        def schedule_link(self, obj):
            """Back-link to the CronSchedule that enqueued this result, if any.

            Resolved through the CronRun link (by task_result_id). Plain tasks
            show an em dash.
            """
            from modules.cron.models import (  # lazy — see registry note
                CronRun,
            )

            run = (
                CronRun.objects.filter(task_result_id=obj.id)
                .select_related("schedule")
                .first()
            )
            sched = run.schedule if run else None
            if sched is None:
                return format_html('<span style="color:#94a3b8;">{}</span>', "—")
            url = reverse("admin:cron_cronschedule_change", args=[sched.id])
            return format_html('<a href="{}">{}</a>', url, sched.name)

        @admin.display(description="Elapsed")
        def elapsed_display(self, obj):
            return _elapsed(obj.started_at, obj.finished_at)

        @admin.display(description="Args / Kwargs")
        def args_kwargs_pretty(self, obj):
            return _pretty_json(obj.args_kwargs)

        @admin.display(description="Return value")
        def return_value_pretty(self, obj):
            return _pretty_json(obj.return_value)

        @admin.display(description="Worker IDs")
        def worker_ids_pretty(self, obj):
            return _pretty_json(obj.worker_ids)

        @admin.display(description="Traceback")
        def traceback_pretty(self, obj):
            if not obj.traceback:
                return format_html('<span style="color:#94a3b8;">{}</span>', "—")
            return format_html(
                '<pre style="{}">{}</pre>', mark_safe(_CODE_BLOCK), obj.traceback
            )

except ImportError:
    pass
