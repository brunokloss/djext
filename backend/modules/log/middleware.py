import json
import re
import secrets
import time

import structlog
from django.utils.crypto import salted_hmac

logger = structlog.get_logger("request")

# The id travels in this header: the Next proxy sets it (see frontend/proxy.ts)
# and every response sends it back.
REQUEST_ID_HEADER = "X-Request-Id"
# Only ids that look like one (8 to 64 of [A-Za-z0-9-]); anything else is
# replaced, so a crafted header can't put arbitrary text in the logs.
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9-]{8,64}")


def new_request_id() -> str:
    # 8 hex chars: short enough to read aloud and grep, ~4 billion values.
    return secrets.token_hex(4)


class RequestIdMiddleware:
    """Gives each request an id and puts it on every log line it causes.

    Keeps the X-Request-Id that came in (from the Next proxy) when it looks
    like one, so the frontend and the backend log the same id. Otherwise
    makes a new one. Sends it back in the response header.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        inbound = request.headers.get(REQUEST_ID_HEADER, "")
        if not REQUEST_ID_RE.fullmatch(inbound):
            inbound = new_request_id()
        request.request_id = inbound

        with structlog.contextvars.bound_contextvars(request_id=inbound):
            response = self.get_response(request)
        response[REQUEST_ID_HEADER] = inbound
        return response


def client_ip(request) -> str | None:
    """The browser's IP, from the last X-Forwarded-For entry.

    The Next proxy only fills X-Forwarded-For with the address that connected
    to it when the header is missing; it passes one that came along as is.
    Behind a load balancer that appends the client's address (the usual
    production setup), the last entry is that address and can be trusted.
    With Next exposed directly, a client can send its own header and pick
    the IP that gets logged.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR")


# Enough to tell logins apart without making every line long (48 bits).
SESSION_HASH_LEN = 12


def session_hash(request, user) -> str | None:
    """Groups the requests of one login: Django gives each login a new session
    key. An HMAC of the key, salted with the user and keyed with SECRET_KEY, so
    a log line never holds something that could be used as the session. Only
    its first 12 characters: modules/audit saves the whole of it in
    `session_hash` (modules can't import each other), and the admin's search
    takes the start of it. Reads the key the cookie brought: no query.
    """
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    if not session_key:
        return None
    salt = user.username if user and user.is_authenticated else ""
    digest = salted_hmac(salt, session_key, algorithm="sha256").hexdigest()
    return digest[:SESSION_HASH_LEN]


class RequestLogMiddleware:
    """One line per request on the request channel: `200 GET /api/...` with
    the user, the session, the IP and how long it took. 4xx and 5xx are warnings.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        user = getattr(request, "user", None)
        status = response.status_code
        fields = {
            # The username is a UUID (apps/authd/models.py), never the email.
            "usr": user.username if user and user.is_authenticated else None,
            "ses": session_hash(request, user),
            "xip": client_ip(request),
            "dur": duration_ms,
        }
        # The body of an API error says why (Ninja's 422 lists the invalid
        # fields). 401/403/404 say nothing useful and could tell who exists.
        if (
            status >= 400
            and status not in (401, 403, 404)
            and response.get("Content-Type", "").startswith("application/json")
        ):
            try:
                fields["error"] = json.loads(response.content)
            except ValueError:
                pass

        log = logger.warning if status >= 400 else logger.info
        log(f"{status} {request.method} {request.path}", **fields)
        return response
