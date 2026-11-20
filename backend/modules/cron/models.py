import uuid

from croniter import croniter
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class CronSchedule(models.Model):
    """A database-controlled cron job.

    One row per `@scheduled` function discovered in code (synced by
    `registry.sync_schedules`). The code declares a default expression; this row
    can override it and, crucially, gates whether the job runs at all via
    `enabled`. New jobs start disabled so a deploy never silently activates cron.

    `cron_tick` reads these rows every minute, enqueues whatever is due, and
    writes back the bookkeeping fields below.

    Self-contained on purpose: it extends Django's plain Model and uses only the
    stdlib (UUID4 PK + timestamps inline, mirroring django_tasks_db's own
    DBTaskResult), with no dependency on `core`, so this app can be lifted out
    as-is without cross-app coupling.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    name = models.CharField(_("name"), max_length=300, unique=True)
    # Optional override of the in-code expression. Blank = use the code value.
    expression = models.CharField(
        _("expression"), max_length=100, blank=True, default=""
    )
    enabled = models.BooleanField(_("enabled"), default=False)
    # Temporarily skip the job until this moment, without disabling it.
    paused_until = models.DateTimeField(_("paused until"), null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True, default="")

    # Bookkeeping written by sync_schedules + cron_tick.
    last_seen_in_code = models.DateTimeField(
        _("last seen in code"), null=True, blank=True
    )
    # Last minute at which this job was enqueued (display only).
    last_run_at = models.DateTimeField(_("last run at"), null=True, blank=True)
    last_enqueue_at = models.DateTimeField(_("last enqueue at"), null=True, blank=True)
    is_last_enqueue_ok = models.BooleanField(
        _("is last enqueue ok"), null=True, blank=True
    )
    last_enqueue_error = models.TextField(
        _("last enqueue error"), blank=True, default=""
    )

    # Not audited: the scheduler saves it on every run (last_run_at...), which
    # would flood the log. Turn it on, with `exclude`, if you want to see who
    # enabled a job.
    class Audit:
        skip = True

    class Meta:
        verbose_name = _("Cron Schedule")
        verbose_name_plural = _("Cron Schedules")
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def clean(self):
        if self.expression:
            try:
                croniter(self.expression)
            except (ValueError, KeyError) as e:
                raise ValidationError(
                    {"expression": f"Invalid cron expression: {e}"}
                ) from e

    @property
    def is_active(self) -> bool:
        if not self.enabled:
            return False
        if self.paused_until and self.paused_until > timezone.now():
            return False
        return True

    def effective_expression(self, code_expression: str) -> str:
        """The expression actually used: a DB override wins over the code value."""
        return self.expression or code_expression


class CronRun(models.Model):
    """A bridge row linking one cron enqueue to the DBTaskResult it produced.

    django-tasks-db's DBTaskResult is a third-party model we can't add a foreign
    key to, so the link lives here instead — the explicit, strong equivalent of
    django-celery-beat tagging a result with its PeriodicTask. `cron_tick` (and
    the admin "Schedule now" action) create one CronRun per enqueue, storing the
    UUID that `Task.enqueue()` returns. The admin reads a schedule's history
    through this table rather than string-matching DBTaskResult.task_path.

    `task_result_id` is a plain UUID (not a DB ForeignKey) because DBTaskResult
    rows are pruned independently; a dangling id just means the result aged out.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    schedule = models.ForeignKey(
        CronSchedule,
        on_delete=models.CASCADE,
        related_name="runs",
        verbose_name=_("schedule"),
    )
    # UUID of the django_tasks_db.DBTaskResult this enqueue created. Not a FK —
    # see the class docstring.
    task_result_id = models.UUIDField(_("task result id"), db_index=True)
    enqueued_at = models.DateTimeField(_("enqueued at"), default=timezone.now)

    # Not audited: one row per run, written by the scheduler.
    class Audit:
        skip = True

    class Meta:
        verbose_name = _("Cron Run")
        verbose_name_plural = _("Cron Runs")
        ordering = ["-enqueued_at"]
        indexes = [
            models.Index(fields=["schedule", "-enqueued_at"]),
        ]

    def __str__(self):
        return f"{self.schedule_id} → {self.task_result_id}"

    @property
    def task_result(self):
        """The linked DBTaskResult, or None if it was pruned / unavailable."""
        try:
            from django_tasks_db.models import DBTaskResult
        except ImportError:
            return None
        return DBTaskResult.objects.filter(id=self.task_result_id).first()
