"""The session engine (settings.SESSION_ENGINE): Django's database sessions,
saved to session.Session, which also has whose session it is and where they
logged in from. See "Extending database-backed session engines" in Django's
docs.

`end_sessions` is the one way to end sessions: the API and the admin call it.
`forget` deletes all of a user's (User.anonymize() calls it).

On login (signals.py), `remember_login` puts a public id, the IP, user agent
and time in the session data, and every save copies them, and the user, to
their columns. The id lives in the data too: each save builds a new model
instance, so a column default alone would give a new id on every save.
"""

import ipaddress
import uuid

from django.contrib.auth import SESSION_KEY, logout
from django.contrib.sessions.backends.db import SessionStore as DBStore
from django.http import HttpRequest
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ninja.throttling import BaseThrottle

from modules.signals.signals import action_performed

PUBLIC_ID = "_session_public_id"
IP = "_login_ip"
USER_AGENT = "_login_user_agent"
LOGGED_IN_AT = "_login_at"


class SessionStore(DBStore):
    @classmethod
    def get_model_class(cls):
        from .models import Session

        return Session

    def create_model_instance(self, data):
        return fill(super().create_model_instance(data), data)

    async def acreate_model_instance(self, data):
        return fill(await super().acreate_model_instance(data), data)


def fill(obj, data: dict):
    """Copies the login details from the session data to their columns."""
    # Sessions without a login (anonymous) keep the column default.
    obj.public_id = data.get(PUBLIC_ID) or obj.public_id
    obj.user_id = data.get(SESSION_KEY)
    obj.ip = data.get(IP)
    obj.user_agent = data.get(USER_AGENT, "")
    obj.logged_in_at = parse_datetime(data.get(LOGGED_IN_AT) or "")
    return obj


def client_ip(request: HttpRequest) -> str | None:
    """The same client IP as the rate limits (NINJA_NUM_PROXIES), or None when
    the header holds something that isn't one."""
    try:
        return str(ipaddress.ip_address(BaseThrottle().get_ident(request) or ""))
    except ValueError:
        return None


def remember_login(request: HttpRequest) -> None:
    """Called on login: where it came from, so the user can tell their
    sessions apart."""
    request.session[PUBLIC_ID] = str(uuid.uuid7())
    request.session[IP] = client_ip(request)
    request.session[USER_AGENT] = request.headers.get("User-Agent", "")[:256]
    request.session[LOGGED_IN_AT] = timezone.now().isoformat()


def end_sessions(request: HttpRequest, user, *, public_id=None, keep_current=False):
    """Ends `user`'s live sessions, or only the one with `public_id`, and with
    `keep_current` all but the request's own. Ending the request's own session
    is a logout. Returns how many ended; when any did, sends action_performed
    with the user as target (the audit log and the auth channel)."""
    current = request.session.session_key
    live = user.sessions.live()
    if public_id is not None:
        live = live.filter(public_id=public_id)
    if keep_current:
        live = live.exclude(session_key=current)
    keys = set(live.values_list("session_key", flat=True))
    if not keys:
        return 0
    # The request's own goes through logout(), which also drops its cookie.
    user.sessions.filter(session_key__in=keys - {current}).delete()
    which = "one" if public_id else "others" if keep_current else "all"
    action_performed.send(
        None,
        request=request,
        name="auth.end_sessions",
        values={"which": which, "count": len(keys)},
        target=user,
    )
    if current in keys:
        logout(request)
    return len(keys)


def forget(user) -> None:
    """Every session of `user`, expired too: they hold the IP and browser."""
    from .models import Session

    Session.objects.filter(user=user).delete()
