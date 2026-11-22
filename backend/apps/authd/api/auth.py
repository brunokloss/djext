from django.apps import apps
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.views.decorators.cache import cache_control
from ninja import Router, Schema
from ninja.decorators import decorate_view
from ninja.throttling import BaseThrottle
from ninja.utils import check_csrf

from modules.signals.signals import (
    inactive_login,
    login_options_requested,
    login_throttled,
)
from modules.throttle.throttles import FailureLimit, hashed

from .schemas import ErrorOut, UserOut

router = Router()


def email_login_limit() -> FailureLimit | None:
    """The per-email login limit (counted under hashed(email)), or None when off.
    The login and the User admin use it, to show and lift a lock."""
    rate = settings.AUTH_LOGIN_THROTTLE_EMAIL
    return FailureLimit("login_email", rate) if rate else None


class LoginIn(Schema):
    email: str
    password: str


# Session login for the frontend: GET /auth/csrf sets the CSRF cookie
# (CSRF_COOKIE_NAME), then POST /auth/login and /auth/logout send it back in
# the X-CSRFToken header.
# Endpoints with auth=django_auth already check CSRF; these two have no auth,
# so they check it themselves.
@router.get("/auth/csrf", response={204: None}, tags=["auth"])
def csrf(request: HttpRequest):
    """Sets the CSRF cookie (CSRF_COOKIE_NAME)."""
    get_token(request)
    return 204, None


def login_limits(
    request: HttpRequest, email: str
) -> list[tuple[str, FailureLimit, str]]:
    """(name, limit, what it counts) for each login limit that is on: failures
    for this email (from any IP: one account guessed from many machines) and
    from this IP (many accounts tried from one machine)."""
    limits = []
    if limit := email_login_limit():
        limits.append(("email", limit, hashed(email)))
    if rate := settings.AUTH_LOGIN_THROTTLE_IP:
        ident = BaseThrottle().get_ident(request)
        limits.append(("ip", FailureLimit("login_ip", rate), ident))
    return limits


def limited_authenticate(sender, request: HttpRequest, email: str, password: str):
    """authenticate() behind login_limits(), for every password login: this
    API and the admin's own form (apps/authd/forms.py). Returns (user or None,
    None), or (None, seconds to wait) when a limit refused the try. `email` is
    normalized; `sender` sends login_throttled."""
    # Each limit counts this try as a failure before the password check (see
    # FailureLimit), and a good login takes it back below.
    counted = []
    for name, limit, ident in login_limits(request, email):
        wait, stamp = limit.attempt(ident)
        if wait:
            # A refused try isn't a failure: take back what the other limits
            # counted. Before authenticate(): no password is checked, and no
            # user_login_failed, so the audit log writes nothing.
            for _, limit, ident, stamp in counted:
                limit.forget(ident, stamp)
            login_throttled.send(
                sender, request=request, email=email, limit=name, retry_after=wait
            )
            return None, wait
        counted.append((name, limit, ident, stamp))
    user = authenticate(request, email=email, password=password)
    if user is None:
        # The right password for an inactive user (one still confirming
        # their email) isn't a failure either: they would end up locked out.
        if getattr(request, "auth_inactive_user", None):
            for _, limit, ident, stamp in counted:
                limit.forget(ident, stamp)
        return None, None
    # The email's failures all go; the IP's stay (only this try is taken
    # back), or one account of its own would let an attacker reset them.
    for name, limit, ident, stamp in counted:
        if name == "email":
            limit.clear(ident)
        else:
            limit.forget(ident, stamp)
    return user, None


@router.post(
    "/auth/login",
    response={200: UserOut, 401: ErrorOut, 403: ErrorOut, 429: ErrorOut},
    tags=["auth"],
)
def login_view(request: HttpRequest, response: HttpResponse, data: LoginIn):
    """Starts a session. Login rotates the CSRF token: read the cookie again.
    403 with the right password for an account that can't log in yet (its
    email is not confirmed). 429 after too many failures (Retry-After says
    when to try again)."""
    if check_csrf(request):
        return 403, {"detail": "CSRF check failed"}
    if not settings.AUTH_PASSWORD:
        return 403, {"detail": "Password login is disabled"}
    email = get_user_model().objects.normalize_email(data.email)
    user, wait = limited_authenticate(login_view, request, email, data.password)
    if wait:
        response["Retry-After"] = str(wait)
        return 429, {"detail": "Too many failed logins. Try again later."}
    if user is None:
        # The right password, but a module knows why the user is inactive.
        if inactive := getattr(request, "auth_inactive_user", None):
            for _, detail in inactive_login.send(
                login_view, request=request, user=inactive
            ):
                if detail:
                    return 403, {"detail": detail}
        return 401, {"detail": "Invalid email or password"}
    login(request, user)
    return user


class LoginOptionOut(Schema):
    name: str
    # The button's text, e.g. "Google".
    label: str
    # Where the browser goes to start it (a full navigation, not fetch).
    url: str


class LoginOptionsOut(Schema):
    # Email and password (AUTH_PASSWORD).
    password: bool
    # Other ways to log in, in the order the page shows them.
    providers: list[LoginOptionOut]
    # Self-service accounts (modules/signup): the links to /signup and
    # /forgot-password.
    signup: bool
    password_reset: bool
    # A login link sent by email (modules/signup): /login-link.
    magic_link: bool


# Public and the same for everyone, and settings only change when the app
# restarts: browsers and proxies may keep it for 5 minutes. The server has
# nothing to cache: it reads settings, no database.
@router.get("/auth/providers", response=LoginOptionsOut, tags=["auth"])
@decorate_view(cache_control(public=True, max_age=300))
def list_login_options(request: HttpRequest):
    """Which ways to log in are on, so the login page only shows those: the
    password, and what the modules return (modules/signals/signals.py)."""
    sent = login_options_requested.send(list_login_options)
    # Off when modules/signup is removed. Sign-up and reset need the
    # password; the login link doesn't.
    installed = apps.is_installed("modules.signup")
    signup = installed and settings.AUTH_PASSWORD
    return {
        "password": settings.AUTH_PASSWORD,
        "providers": [option for _, options in sent for option in options],
        "signup": signup and settings.AUTH_SIGNUP,
        "password_reset": signup and settings.AUTH_PASSWORD_RESET,
        "magic_link": installed and settings.AUTH_MAGIC_LINK,
    }


@router.post("/auth/logout", response={204: None, 403: ErrorOut}, tags=["auth"])
def logout_view(request: HttpRequest):
    """Ends the session (204 even when not logged in)."""
    if check_csrf(request):
        return 403, {"detail": "CSRF check failed"}
    logout(request)
    return 204, None
