"""The `@scheduled` decorator and its in-process registry.

django-tasks has no native cron support: a worker only runs what was enqueued.
`@scheduled` goes on top of a task and records its cron expression in
`SCHEDULE_REGISTRY`. The scheduler's `cron_tick` reads that registry once per
minute and enqueues whatever is due; the worker then runs it. The task itself is
left untouched, so the worker finds it by its normal import path.

Usage:

    from django.tasks import task
    from modules.cron.registry import scheduled

    @scheduled("0 6 * * *")
    @task(queue_name="scheduled_tasks")
    def daily_maintenance():
        ...

`@scheduled` on anything that is not a task (a plain function, or `@task`
missing underneath) raises a TypeError when the module is imported, and two
jobs whose functions share a name (in two modules) an ImproperlyConfigured.

The registry is populated as a side effect of importing the module that holds
the decorated functions. The management commands import it lazily for that reason.

Run tracking: `cron_tick` and the admin's "Schedule now" create a CronRun row
linking each enqueue to the DBTaskResult it produced.
"""

import importlib
import logging
import signal
import threading
import time
import traceback

from croniter import croniter
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connection
from django.tasks import Task
from django.utils import timezone

# NOTE: models are NOT imported here. This module is imported very early (task
# modules import it at their top, loaded during app startup), and importing a
# model before the app registry is ready raises AppRegistryNotReady. Functions
# below import CronSchedule/CronRun lazily for that reason. Everything else is
# registry-safe and lives at module top.

# Its own channel in the logs (see modules/log), not `app`.
logger = logging.getLogger("scheduler")

# name -> (cron_expression, Task object)
SCHEDULE_REGISTRY: dict[str, tuple[str, object]] = {}
# Jobs that said how they start (`enabled=True` or `False`), over what
# CRON_AUTO_ENABLE_NEW_TASKS says.
STARTS_ENABLED: dict[str, bool] = {}


def load_task_modules():
    """Import every module named in `settings.CRON_TASK_MODULES`.

    Importing a module runs its `@scheduled` decorators, which is what populates
    `SCHEDULE_REGISTRY`. Keeping the list in settings (rather than importing a
    fixed module) is how this app stays decoupled from any particular project app
    — the project declares where its scheduled functions live, e.g.

        CRON_TASK_MODULES = ["core.tasks"]

    Idempotent: re-importing an already-loaded module is a no-op.
    """
    for module_path in getattr(settings, "CRON_TASK_MODULES", []):
        importlib.import_module(module_path)


def sync_schedules():
    """Create/refresh a CronSchedule row for every @scheduled job in code.

    Loads the task modules (populating the registry), then upserts one row per
    job. Idempotent: new jobs are created with `enabled=False` (so a deploy never
    auto-activates cron), existing ones just get `last_seen_in_code` refreshed.

    Returns (created_count, updated_count).
    """
    from modules.cron.models import CronSchedule  # lazy — see module note

    load_task_modules()
    now = timezone.now()
    # New rows are created enabled when this is on (per-environment, via env).
    # Only the create default — never overrides an existing row.
    auto_enable = getattr(settings, "CRON_AUTO_ENABLE_NEW_TASKS", False)
    created = updated = 0
    for name in SCHEDULE_REGISTRY:
        obj, was_created = CronSchedule.objects.get_or_create(
            name=name,
            defaults={
                "last_seen_in_code": now,
                "enabled": STARTS_ENABLED.get(name, auto_enable),
            },
        )
        if was_created:
            created += 1
        else:
            obj.last_seen_in_code = now
            obj.save(update_fields=["last_seen_in_code", "updated_at"])
            updated += 1
    return created, updated


def scheduled(expression: str, *, enabled: bool | None = None):
    """Declare a cron schedule for a task. Goes above `@task`::

        @scheduled("*/15 * * * *")
        @task(queue_name="scheduled_tasks")
        def sync_something():
            ...

    When the expression matches the current minute, the scheduler enqueues the
    task once. There is no backfill: ticks missed while the scheduler was down are
    simply skipped. Queue, priority, `takes_context`... are the `@task`'s own.
    Use a queue the worker reads (`TASKS` in the settings).

    A new job's CronSchedule row is created disabled, unless
    `CRON_AUTO_ENABLE_NEW_TASKS` is on. `enabled` overrides that for one job:
    `True` starts it on (housekeeping nobody should have to remember to turn on),
    `False` keeps it off even then.
    Either way the admin owns the flag once the row exists: sync never overrides it
    on later deploys.
    """
    croniter(expression)  # validate the expression at import time

    def decorator(task_obj):
        if not isinstance(task_obj, Task):
            name = getattr(task_obj, "__qualname__", repr(task_obj))
            raise TypeError(
                f"@scheduled({expression!r}) is on {name}, which is not a task. "
                "Put @task under it:\n\n"
                f"    @scheduled({expression!r})\n"
                "    @task\n"
                f"    def {getattr(task_obj, '__name__', 'job')}(): ..."
            )
        name = task_obj.func.__name__
        # The CronSchedule row is named after the function only: another
        # module's job with that name would replace this one in silence.
        if (taken := SCHEDULE_REGISTRY.get(name)) and (
            taken[1].module_path != task_obj.module_path
        ):
            raise ImproperlyConfigured(
                f"@scheduled: {taken[1].module_path} and {task_obj.module_path}"
                f" are both named {name!r}. Rename one."
            )
        SCHEDULE_REGISTRY[name] = (expression, task_obj)
        if enabled is not None:
            STARTS_ENABLED[name] = enabled
        return task_obj

    return decorator


def enqueue_for_schedule(schedule, task, by=None):
    """Enqueue `task` on behalf of a CronSchedule and record the strong link.

    Creates a CronRun row pointing at the result id that `enqueue()` returns.
    `by` is the user who ran it by hand (it goes in the log). Used by both
    `cron_tick` and the admin "Schedule now" action so the linkage is identical
    wherever a cron job is enqueued.

    Returns the created CronRun. Raises if the backend gives no result id.
    """
    from modules.cron.models import CronRun  # lazy — see module note

    result = task.enqueue()
    result_id = getattr(result, "id", None)
    if result_id is None:
        # Nothing to link the run to: say so, so it is recorded as a failure.
        raise RuntimeError(f"{schedule.name}: the task backend returned no result id")
    # `tsk` is the field the worker logs while it runs the task: one search
    # follows a job from "enqueued" to "ran".
    # `by` is the admin user who pressed "Schedule now"; the tick passes none.
    if by is None:
        logger.info(
            "cron: %s enqueued",
            schedule.name,
            extra={"tsk": str(result_id), "src": "tick"},
        )
    else:
        logger.info(
            "cron: %s enqueued by hand",
            schedule.name,
            extra={"tsk": str(result_id), "src": "manual", "usr": by.username},
        )
    return CronRun.objects.create(schedule=schedule, task_result_id=result_id)


def cron_tick(now=None):
    """Enqueue every registered job whose expression matches the current minute.

    One pass of the scheduler tick: load the task modules, then for each active
    CronSchedule whose effective expression matches `now`, enqueue it once and
    record the outcome. No backfill — a minute that wasn't ticked is skipped.

    Invoked once per minute by the scheduler loop. One job failing never stops
    the others.
    """
    from modules.cron.models import CronSchedule  # lazy — see module note

    load_task_modules()
    now = (now or timezone.now()).replace(second=0, microsecond=0)
    schedules = {s.name: s for s in CronSchedule.objects.all()}

    for name, (code_expression, task) in SCHEDULE_REGISTRY.items():
        sched = schedules.get(name)
        if sched is None or not sched.is_active:
            continue
        expression = sched.effective_expression(code_expression)
        if not croniter.match(expression, now):
            continue

        logger.info("cron_tick: %s due (expr=%s)", name, expression)
        try:
            enqueue_for_schedule(sched, task)
        except Exception:
            tb = traceback.format_exc()
            logger.exception("cron_tick: enqueue failed for %s", name)
            _record_tick(sched, ok=False, when=now, error=tb)
        else:
            _record_tick(sched, ok=True, when=now, error="")


def _record_tick(sched, *, ok: bool, when, error: str):
    sched.last_run_at = when
    sched.last_enqueue_at = when
    sched.is_last_enqueue_ok = ok
    sched.last_enqueue_error = error
    sched.save(
        update_fields=[
            "last_run_at",
            "last_enqueue_at",
            "is_last_enqueue_ok",
            "last_enqueue_error",
            "updated_at",
        ]
    )


# --- scheduler loop --------------------------------------------------------

STANDBY_RETRY_SECONDS = 10

# Stable, arbitrary 64-bit key identifying this app's scheduler lock. Picked once
# and frozen; any process using the same key contends for the same single slot.
SCHEDULER_LOCK_KEY = 6_812_004_553_991_207_641


def _try_acquire_lock() -> bool:
    # Only Postgres has advisory locks. Elsewhere (SQLite in development) there is
    # nothing to coordinate: run a single scheduler.
    if connection.vendor != "postgresql":
        return True
    with connection.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", [SCHEDULER_LOCK_KEY])
        return bool(cur.fetchone()[0])


def _holds_lock() -> bool:
    """Does this connection still hold the lock? The lock belongs to the database
    session: if the connection dropped and Django reconnected (a network error, a
    failover), it is gone and the loop must not go on ticking as if it had it."""
    if connection.vendor != "postgresql":
        return True
    # A bigint advisory lock shows in pg_locks as its two halves, objsubid 1.
    classid, objid = SCHEDULER_LOCK_KEY >> 32, SCHEDULER_LOCK_KEY & 0xFFFFFFFF
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND classid = %s"
                " AND objid = %s AND objsubid = 1 AND pid = pg_backend_pid()",
                [classid, objid],
            )
            return cur.fetchone() is not None
    except DatabaseError:
        connection.close()  # Django opens a new one on the next query.
        return False


def run_scheduler():
    """Run the scheduler loop — one active instance ticks `cron_tick` per minute.

    Single-active coordination is a Postgres session-level advisory lock: whoever
    grabs it runs the loop; others stay in standby and retry. If the active
    instance dies, Postgres drops the lock and a standby takes over — so you can
    run several for availability with no coordination outside the database. The
    lock is checked before every tick: if the connection dropped, it is gone, and
    the instance goes back to standby instead of ticking without it.

    This is the bare loop. The autoreloader (a dev-runtime concern) lives in the
    `db_scheduler` command, which wraps this call when reload is on.
    """
    shutdown = False

    def _stop(_signum, _frame):
        nonlocal shutdown
        logger.info("Scheduler shutting down")
        shutdown = True

    # signal.signal() only works on the main thread. Under the autoreloader (dev)
    # this runs on a worker thread, where the reloader already handles
    # SIGINT/SIGTERM, so installing handlers there both fails and is redundant.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

    logger.info("Starting scheduler")

    while not shutdown:
        # Standby loop — wait for the lock, keeping the process alive so a
        # supervisor doesn't relaunch us tightly while another instance is active.
        while not shutdown:
            if _try_acquire_lock():
                logger.info("Scheduler lock acquired — this instance is active")
                break
            logger.info("Scheduler standby — another instance holds the lock")
            time.sleep(STANDBY_RETRY_SECONDS)

        if shutdown:
            return

        # Sync CronSchedule rows from the @scheduled decorators so new jobs appear
        # automatically. Only the active instance does this (we hold the lock).
        created, updated = sync_schedules()
        logger.info("Synced schedules: %d created, %d updated", created, updated)

        # Align each tick to second :00 of the next minute so cron fires
        # predictably and doesn't drift over long uptimes.
        while not shutdown:
            now = timezone.now()
            sleep_for = 60 - now.second - (now.microsecond / 1_000_000)
            logger.info("Scheduler running — next tick in %.0fs", sleep_for)
            if sleep_for > 0:
                time.sleep(sleep_for)
            if shutdown:
                break
            if not _holds_lock():
                # Another scheduler may have taken over: back to standby.
                logger.warning("Scheduler lost its lock — back to standby")
                break
            logger.info("tick %s", timezone.now().strftime("%H:%M:%S"))
            try:
                cron_tick()
            except Exception:
                # A failing tick must not kill the loop — log and keep going.
                logger.exception("Scheduler tick failed")
