import ipaddress

from django.utils.crypto import salted_hmac

from modules.signals.context import current_actor, request_user

USER_AGENT_MAX_LEN = 500


def request_info(request) -> dict:
    """The log's fields about who and where from, for AuditLog. Without a
    request (a task, a command, an MCP tool), only who: `acting_as`'s user."""
    if request is None:
        return {"actor": current_actor()}
    actor = request_user(request) or current_actor()
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
