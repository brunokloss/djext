"""What is waiting to be done and for how long: the background tasks and, with
django-post-office installed, the emails. Something due for longer than
STALLED_AFTER means no worker is taking it."""

from datetime import timedelta

from django.apps import apps
from django.db.models import (
    Avg,
    Case,
    DateTimeField,
    DurationField,
    ExpressionWrapper,
    F,
    Max,
    Min,
    Q,
    When,
)
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from django_tasks_db.models import DBTaskResult, get_date_max

STALLED_AFTER = timedelta(seconds=60)


def seconds(delta: timedelta | None) -> float | None:
    return None if delta is None else round(delta.total_seconds(), 1)


def wait_of(finished_at: str, due_at: Case | Coalesce) -> ExpressionWrapper:
    return ExpressionWrapper(F(finished_at) - due_at, output_field=DurationField())


def tasks(now) -> dict:
    # When a task became ready: its `run_after`, or when it was enqueued if it
    # had none (stored as the maximum date).
    due_at = Case(
        When(run_after=get_date_max(), then=F("enqueued_at")),
        default=Greatest("run_after", "enqueued_at"),
        output_field=DateTimeField(),
    )
    due = DBTaskResult.objects.ready()
    oldest = due.aggregate(oldest=Min(due_at))["oldest"]
    started = DBTaskResult.objects.filter(
        started_at__gte=now - timedelta(hours=1)
    ).aggregate(
        avg=Avg(wait_of("started_at", due_at)), max=Max(wait_of("started_at", due_at))
    )
    return {
        "due": due.count(),
        "running": DBTaskResult.objects.running().count(),
        "oldest_wait": seconds(None if oldest is None else now - oldest),
        "avg_latency": seconds(started["avg"]),
        "max_latency": seconds(started["max"]),
    }


def emails(now) -> dict:
    from post_office.models import STATUS, Email

    due_at = Coalesce("scheduled_time", "created")
    waiting = Email.objects.filter(status__in=[STATUS.queued, STATUS.requeued])
    due = waiting.filter(Q(scheduled_time=None) | Q(scheduled_time__lte=now)).filter(
        Q(expires_at=None) | Q(expires_at__gt=now)
    )
    oldest = due.aggregate(oldest=Min(due_at))["oldest"]
    sent = Email.objects.filter(
        status=STATUS.sent, last_updated__gte=now - timedelta(hours=1)
    ).aggregate(
        avg=Avg(wait_of("last_updated", due_at)),
        max=Max(wait_of("last_updated", due_at)),
    )

    def changed(status: int, since: timedelta) -> int:
        return Email.objects.filter(
            status=status, last_updated__gte=now - since
        ).count()

    day, month = timedelta(hours=24), timedelta(days=30)
    return {
        "due": due.count(),
        "later": waiting.filter(scheduled_time__gt=now).count(),
        "oldest_wait": seconds(None if oldest is None else now - oldest),
        "avg_latency": seconds(sent["avg"]),
        "max_latency": seconds(sent["max"]),
        "failed_24h": changed(STATUS.failed, day),
        "failed_30d": changed(STATUS.failed, month),
        "requeued_24h": changed(STATUS.requeued, day),
        "requeued_30d": changed(STATUS.requeued, month),
    }


def stats(now=None) -> dict:
    now = now or timezone.now()
    data = {"tasks": tasks(now)}
    if apps.is_installed("post_office"):
        data["emails"] = emails(now)
    limit = STALLED_AFTER.total_seconds()
    data["stalled"] = any(
        (part["oldest_wait"] or 0) > limit
        for part in data.values()
        if isinstance(part, dict)
    )
    return data
