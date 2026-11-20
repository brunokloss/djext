import ipaddress
from contextvars import ContextVar

from django.conf import settings
from django.utils.crypto import salted_hmac

from modules.signals.context import acting_origin, current_actor, request_user

# True while the worker runs a task (signals.py sets it around each one).
in_task = ContextVar("audit_in_task", default=False)

USER_AGENT_MAX_LEN = 500


def request_info(request) -> dict:
    """The log's fields about who and where from, for AuditLog. Without a
    request (a task, a command, an MCP tool), only who: `acting_as`'s user."""
    if request is None:
        return {"actor": current_actor(), "origin": origin(None)}
    actor = request_user(request) or current_actor()
    return {
        "actor": actor,
        "origin": origin(request),
        "ip_address": client_ip(request),
        "user_agent": request.headers.get("User-Agent", "")[:USER_AGENT_MAX_LEN],
        "session_hash": session_hash(request, actor),
        "request_id": getattr(request, "request_id", ""),
    }


def origin(request) -> str:
    """Through what it came: what `acting_as` says, else `admin`, `api` or
    `http` from the request's path, else `task` in the worker, else `system`
    (the shell, a command)."""
    if explicit := acting_origin():
        return explicit
    if request is None:
        return "task" if in_task.get() else "system"
    admin = "/" + getattr(settings, "DJANGO_ADMIN_PATH", "admin").strip("/") + "/"
    if request.path.startswith(admin):
        return "admin"
    if request.path.startswith("/api/"):
        return "api"
    return "http"


def session_hash(request, actor) -> str:
    """Groups what one login did: Django gives each login a new session key.
    An HMAC of the key, salted with the user and keyed with SECRET_KEY, so
    the log never holds something that could be used as the session."""
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    if not session_key:
        return ""
    salt = actor.username if actor else ""
    return salted_hmac(salt, session_key, algorithm="sha256").hexdigest()


def client_ip(request) -> str | None:
    """The last X-Forwarded-For entry (what the load balancer appended), or
    the address that connected. The same rule as modules/log,
    which modules can't import. None when it isn't an IP: the column is an
    `inet` on Postgres, and a made-up header would fail the save (and with
    it the login or the change being logged)."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    value = (
        forwarded.split(",")[-1].strip()
        if forwarded
        else request.META.get("REMOTE_ADDR")
    )
    try:
        return str(ipaddress.ip_address(value or ""))
    except ValueError:
        return None
