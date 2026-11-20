import ipaddress
from contextvars import ContextVar

from django.utils.crypto import salted_hmac

# The request being handled, for who made the change and from where. None in
# the shell, management commands and jobs.
current_request = ContextVar("audit_request", default=None)

USER_AGENT_MAX_LEN = 500


def request_info(request) -> dict:
    """The log's fields about who and where from, for AuditLog."""
    if request is None:
        return {}
    user = getattr(request, "user", None)
    actor = user if user and user.is_authenticated else None
    return {
        "actor": actor,
        "ip_address": client_ip(request),
        "user_agent": request.headers.get("User-Agent", "")[:USER_AGENT_MAX_LEN],
        "session_hash": session_hash(request, actor),
        "request_id": getattr(request, "request_id", ""),
    }


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


class AuditMiddleware:
    """Keeps the request where the signals can see it. Goes after
    AuthenticationMiddleware, so request.user is there."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            current_request.reset(token)
