"""The auth channel: every login, logout and failed login, by password (API or
admin) or by a provider (modules/oauth), all through Django's auth signals
(signals.py). Actions named `auth.*` are here too (actions.py).

Each line says who (`usr`, the UUID, or the `email` typed in when there is no
user) and where from (`xip`, `uag`, `lng`), so these stand out in the logs:
- many emails from one IP: someone guessing which accounts exist;
- many failures on one email: someone guessing its password;
- a login from an IP or device an account never used.
Nothing here touches the database: failed logins are what an attacker hammers.
"""

import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .middleware import client_ip

logger = logging.getLogger("auth")


def client(request) -> dict:
    """Where the attempt came from: the IP and the headers that tell devices
    apart. Never cookies, tokens or Authorization. Cut to 256 chars so a
    huge header can't blow up the line.
    """
    if request is None:
        return {"xip": None, "uag": None, "lng": None}
    return {
        "xip": client_ip(request),
        "uag": request.headers.get("User-Agent", "")[:256] or None,
        "lng": request.headers.get("Accept-Language", "")[:256] or None,
    }


def email_or_none(value) -> str | None:
    """The email, normalized, or None when it isn't one (a password typed in
    the wrong field, or garbage)."""
    email = get_user_model().objects.normalize_email(value)
    try:
        validate_email(email)
    except ValidationError:
        return None
    return email


def login(request, user):
    logger.info("login", extra={"usr": user.username, **client(request)})


def logout(request, user):
    usr = user.username if user else None
    logger.info("logout", extra={"usr": usr, **client(request)})


def login_failed(request, credentials):
    """A wrong password (`email` from the API, `username` from the admin's
    form) or a provider that didn't log anyone in (modules/oauth adds
    `provider` and `reason`). Only these keys: credentials may hold more.
    """
    email = email_or_none(credentials.get("email") or credentials.get("username"))
    fields = {k: credentials[k] for k in ("provider", "reason") if k in credentials}
    logger.warning("login failed", extra={"email": email, **fields, **client(request)})


def login_throttled(request, email, limit, retry_after):
    """A login refused before the password is checked: too many failures for
    the `email` or from the IP (`limit`), for `retry_after` more seconds."""
    logger.warning(
        "login throttled",
        extra={
            "email": email_or_none(email),
            "limit": limit,
            "retry_after": retry_after,
            **client(request),
        },
    )
