"""Logging: one line per event on stdout, through structlog.

Every line has a `channel` (what it is about) and, inside a request, the
`request_id` the frontend also logs (see middleware.py), so one search
by id finds a request across Next and Django. Inside a background task it has
`tsk`, `que` and `wrk` instead (see tasks.py). JSON in production, colored
key=value in development.

Channels:
- request: one line per request (RequestLogMiddleware)
- auth:    logins, logouts and failed logins (auth.py, from Django's auth
           signals in signals.py)
- worker:  background tasks: Django's and django-tasks-db's logs, and our own
           code while a task runs (tasks.py)
- app:     our own code (loggers under apps.* and modules.*)
- django:  Django itself (500 tracebacks from django.request, for example)
- anything else is named after the library (authlib, urllib3...)

Log to a channel of ours with logging.getLogger("auth") or
structlog.get_logger("auth"); __name__ under apps/ or modules/ means "app".
"""

import logging
from datetime import UTC, datetime

import structlog


def add_service(logger, method_name, event_dict):
    # The frontend logs the same fields with service="frontend".
    event_dict["service"] = "backend"
    return event_dict


def add_timestamp(logger, method_name, event_dict):
    # Milliseconds and Z, exactly like the frontend's Date.toISOString().
    now = datetime.now(UTC).isoformat(timespec="milliseconds")
    event_dict["timestamp"] = now.replace("+00:00", "Z")
    return event_dict


def drop_request(logger, method_name, event_dict):
    # Django passes the HttpRequest as `extra` (CSRF failures, for example);
    # its repr says nothing the request channel doesn't.
    event_dict.pop("request", None)
    return event_dict


# Django's own task logs and the database backend's.
WORKER_LOGGERS = ("django.tasks", "django_tasks_db")


def add_channel(logger, method_name, event_dict):
    name = event_dict.pop("logger", "")
    top = name.split(".")[0]
    if name.startswith(WORKER_LOGGERS) or event_dict.get("que"):
        # The task machinery, and our own code while a task runs (`que` is only
        # set then, see tasks.py).
        top = "worker"
    elif top in ("apps", "modules"):
        top = "app"
    event_dict.setdefault("channel", top or "app")
    return event_dict


def dev_columns(logger, method_name, event_dict):
    # Development only: `request  a339fe04  200 GET /api/...`, so the channel
    # and the id line up on the left. `make dev` already says it's the backend.
    # Inside a task the id is the task's (`tsk`, see tasks.py), cut to 8.
    channel = event_dict.pop("channel")
    request_id = event_dict.pop("request_id", None)
    if request_id is None:
        request_id = (event_dict.pop("tsk", None) or "-")[:8]
    event_dict.pop("service")
    # The context comes back in no set order: put the task's fields last, `dur`
    # at the very end (see tasks.py).
    for key in ("que", "wrk", "dur"):
        if key in event_dict:
            event_dict[key] = event_dict.pop(key)
    event_dict["event"] = f"{channel:<9}  {request_id:<8}  {event_dict['event']}"
    return event_dict


# Run on every line, ours (structlog) and Django's or a library's (stdlib).
SHARED_PROCESSORS = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.stdlib.ExtraAdder(),
    drop_request,
    add_timestamp,
    add_service,
    add_channel,
]


def formatter(debug: bool) -> logging.Formatter:
    if debug:
        render = [dev_columns, structlog.dev.ConsoleRenderer(sort_keys=False)]
    else:
        # Tracebacks as a field, so the line stays one JSON object.
        render = [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            *render,
        ],
    )


def logging_config(debug: bool, level: str) -> dict:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *SHARED_PROCESSORS,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structlog": {"()": formatter, "debug": debug},
        },
        "handlers": {
            "null": {"class": "logging.NullHandler"},
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "structlog",
            },
        },
        "root": {"handlers": ["stdout"], "level": level},
        "loggers": {
            # Only the handler above, not Django's own (which mails admins).
            "django": {"handlers": ["stdout"], "level": level, "propagate": False},
            # 4xx are already in the request channel; keep the 500 tracebacks.
            "django.request": {"level": "ERROR"},
            # runserver's access log: the request channel replaces it.
            "django.server": {"handlers": ["null"], "propagate": False},
        },
    }
