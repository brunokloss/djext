"""Background tasks: every log line a task writes says which task and worker.

A worker runs one task at a time, so these go in the log context while it runs
(the way middleware.py does `request_id`), from Django's task signals in
signals.py. Without them a failure in the logs doesn't say which task or which
worker it came from, with more than one worker running.

- `tsk`: the task's id, the one the admin shows (its first 8 characters stand
  in the `request_id` column in development);
- `que`: its queue;
- `wrk`: the worker running it;
- `dur`: how long it took, in ms, only on the line that says how it ended (it is
  bound last, so it comes last).
"""

import time
from contextvars import ContextVar

import structlog

FIELDS = ("tsk", "que", "wrk", "dur")
_started_at: ContextVar[float | None] = ContextVar("task_started_at", default=None)


def started(task_result) -> None:
    _started_at.set(time.monotonic())
    workers = task_result.worker_ids
    structlog.contextvars.bind_contextvars(
        tsk=str(task_result.id),
        que=task_result.task.queue_name,
        wrk=workers[-1] if workers else None,
    )


def finished(task_result) -> None:
    """Puts `dur` on the line Django logs when the task ends."""
    began = _started_at.get()
    if began is not None:
        dur = round((time.monotonic() - began) * 1000)
        structlog.contextvars.bind_contextvars(dur=dur)


def cleanup() -> None:
    """Takes everything out again, after that line."""
    _started_at.set(None)
    structlog.contextvars.unbind_contextvars(*FIELDS)
