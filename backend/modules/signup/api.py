from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.signals import user_login_failed
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.utils.crypto import salted_hmac
from django.utils.http import url_has_allowed_host_and_scheme
from ninja import Router, Schema
from ninja.throttling import BaseThrottle, SimpleRateThrottle
from ninja.utils import check_csrf

from . import services

# Paths in full, like every app (see apps/authd/api/__init__.py).
router = Router()


class ErrorOut(Schema):
    detail: str


class ConfirmedOut(Schema):
    # For the login page to fill in.
    email: str


class SignupIn(Schema):
    email: str
    password: str
    first_name: str = ""
    last_name: str = ""


class EmailIn(Schema):
    email: str


class VerifyIn(Schema):
    uid: str
    token: str


class LinkIn(Schema):
    uid: str
    token: str


class ResetIn(LinkIn):
    password: str


class MailLimit(SimpleRateThrottle):
    """How many emails these endpoints send to one address, or from one IP,
    in a period (AUTH_MAIL_THROTTLE_EMAIL, AUTH_MAIL_THROTTLE_IP): each try
    counts, whether or not the email has an account."""

    def __init__(self, scope: str, rate: str, ident: str):
        self.scope = scope
        self.ident = ident
        super().__init__(rate)

    def get_cache_key(self, request: HttpRequest) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.ident}


def mail_wait(request: HttpRequest, email: str, purpose: str) -> int | None:
    """Seconds to wait when a limit is reached, or None. Each limit that lets
    the try in counts it. The IP's first: a try it refuses must not use up
    the email's (someone over their own limit would lock the owner out).
    The email's is per `purpose` ("signup" for the confirmation links,
    "reset" for the password): confirming must not use up the first reset."""
    # Keyed with SECRET_KEY: the cache monitor lists the keys, and an email
    # must not be readable there.
    email = services.normalize_email(email)
    hashed = salted_hmac("modules.signup", email, algorithm="sha256").hexdigest()
    limits = [
        (
            "signup_ip",
            settings.AUTH_MAIL_THROTTLE_IP,
            BaseThrottle().get_ident(request),
        ),
        (f"{purpose}_email", settings.AUTH_MAIL_THROTTLE_EMAIL, hashed),
    ]
    for scope, rate, ident in limits:
        if not rate:
            continue
        limit = MailLimit(scope, rate, ident)
        if not limit.allow_request(request):
            # No history with a rate of 0: the whole period.
            oldest = limit.history[-1] if limit.history else limit.now
            return max(1, int(limit.duration - (limit.now - oldest)))
    return None


def site(request: HttpRequest) -> str:
    """The frontend's address, for the links in the emails: the host the Next
    proxy sends (X-Forwarded-Host), so it must be in ALLOWED_HOSTS."""
    return request.build_absolute_uri("/").rstrip("/")


def refused(request: HttpRequest, enabled: bool, what: str, *, password=True):
    """The answer when the request can't go on, or None. These endpoints have
    no auth, so they check CSRF themselves (like authd's login)."""
    if check_csrf(request):
        return 403, {"detail": "CSRF check failed"}
    # Sign-up and reset are about passwords: off when password login is. The
    # login link (password=False) isn't.
    if not (enabled and (settings.AUTH_PASSWORD or not password)):
        return 403, {"detail": f"{what} is disabled"}
    return None


def too_many(response: HttpResponse, wait: int):
    response["Retry-After"] = str(wait)
    minutes = -(-wait // 60)
    when = "in a minute" if minutes == 1 else f"in {minutes} minutes"
    return 429, {"detail": f"Too many emails asked for. Try again {when}."}


def invalid(error: ValidationError):
    return 400, {"detail": " ".join(error.messages)}


MAIL_RESPONSES = {204: None, 400: ErrorOut, 403: ErrorOut, 429: ErrorOut}


@router.post("/auth/signup", response=MAIL_RESPONSES, tags=["auth"])
def signup(request: HttpRequest, response: HttpResponse, data: SignupIn):
    """Creates an account, inactive until the email is verified: the link goes
    by email. 204 whether the email has an account or not. 400 when the
    password is too weak (AUTH_PASSWORD_VALIDATORS)."""
    if answer := refused(request, settings.AUTH_SIGNUP, "Sign-up"):
        return answer
    # Checked before the limit: a refused password sends no email.
    fields = (data.email, data.password, data.first_name, data.last_name)
    try:
        services.check(*fields)
    except ValidationError as error:
        return invalid(error)
    if wait := mail_wait(request, data.email, "signup"):
        return too_many(response, wait)
    services.sign_up(site(request), *fields)
    return 204, None


@router.post("/auth/verify/resend", response=MAIL_RESPONSES, tags=["auth"])
def resend_verification(request: HttpRequest, response: HttpResponse, data: EmailIn):
    """Sends the verification link again, if the email is waiting for one.
    204 either way."""
    if answer := refused(request, settings.AUTH_SIGNUP, "Sign-up"):
        return answer
    if wait := mail_wait(request, data.email, "signup"):
        return too_many(response, wait)
    services.resend_verification(site(request), data.email)
    return 204, None


@router.post(
    "/auth/verify",
    response={200: ConfirmedOut, 400: ErrorOut, 403: ErrorOut},
    tags=["auth"],
)
def verify(request: HttpRequest, data: VerifyIn):
    """Activates the account from the link in the email, or says it was
    already. 400 when the link is wrong or expired. Log in afterwards."""
    if answer := refused(request, settings.AUTH_SIGNUP, "Sign-up"):
        return answer
    if (user := services.verify(data.uid, data.token)) is None:
        return 400, {"detail": "This link is invalid or has expired."}
    return 200, {"email": user.email}


@router.post("/auth/password/forgot", response=MAIL_RESPONSES, tags=["auth"])
def forgot_password(request: HttpRequest, response: HttpResponse, data: EmailIn):
    """Sends a link to choose a new password. 204 whether the email has an
    account or not."""
    if answer := refused(request, settings.AUTH_PASSWORD_RESET, "Password reset"):
        return answer
    if wait := mail_wait(request, data.email, "reset"):
        return too_many(response, wait)
    services.request_reset(site(request), data.email)
    return 204, None


DEAD_LINK = {"detail": "This link is invalid, expired or used already."}


@router.post(
    "/auth/password/reset/check",
    response={204: None, 403: ErrorOut, 410: ErrorOut},
    tags=["auth"],
)
def check_reset_link(request: HttpRequest, data: LinkIn):
    """204 when the reset link still works, so the page asks for the new
    password only then; 410 when it is wrong, expired or used already."""
    if answer := refused(request, settings.AUTH_PASSWORD_RESET, "Password reset"):
        return answer
    if services.reset_user(data.uid, data.token) is None:
        return 410, DEAD_LINK
    return 204, None


@router.post(
    "/auth/password/reset",
    response={200: ConfirmedOut, 400: ErrorOut, 403: ErrorOut, 410: ErrorOut},
    tags=["auth"],
)
def reset_password(request: HttpRequest, data: ResetIn):
    """Sets the new password from the link in the email and ends the user's
    sessions. 400 when the password is too weak, 410 when the link is wrong,
    expired or used already."""
    if answer := refused(request, settings.AUTH_PASSWORD_RESET, "Password reset"):
        return answer
    try:
        user = services.reset_password(data.uid, data.token, data.password)
    except ValidationError as error:
        return invalid(error)
    if user is None:
        return 410, DEAD_LINK
    return 200, {"email": user.email}


class LoginLinkIn(EmailIn):
    # The page to go to once logged in: a path on the frontend.
    next: str = ""


def safe_next(next: str) -> str:
    """Only same-origin paths, so the link can't be an open redirect (as in
    modules/oauth)."""
    if next.startswith("/") and url_has_allowed_host_and_scheme(next, None):
        return next
    return ""


@router.post("/auth/login-link", response=MAIL_RESPONSES, tags=["auth"])
def request_login_link(request: HttpRequest, response: HttpResponse, data: LoginLinkIn):
    """Sends a link that logs in. 204 whether the email has an account or
    not. Works with AUTH_PASSWORD off."""
    if answer := refused(
        request, settings.AUTH_MAGIC_LINK, "Login link", password=False
    ):
        return answer
    if wait := mail_wait(request, data.email, "login"):
        return too_many(response, wait)
    services.request_login_link(site(request), data.email, safe_next(data.next))
    return 204, None


@router.post(
    "/auth/login-link/login",
    response={204: None, 403: ErrorOut, 410: ErrorOut},
    tags=["auth"],
)
def login_with_link(request: HttpRequest, data: LinkIn):
    """Starts a session from the link in the email; the link stops working.
    A POST from the page's button, not the link itself, so a mail scanner
    that opens it doesn't use it up. Login rotates the CSRF token: read the
    cookie again. 410 when the link is wrong, expired or used already."""
    if answer := refused(
        request, settings.AUTH_MAGIC_LINK, "Login link", password=False
    ):
        return answer
    if (user := services.login_link_user(data.uid, data.token)) is None:
        # A failed login, as modules/oauth sends for its failures, so whoever
        # listens (the auth log, the audit log) sees tokens being tried.
        user_login_failed.send(
            sender=__name__,
            credentials={"provider": "login_link", "reason": "dead_link"},
            request=request,
        )
        return 410, DEAD_LINK
    # As modules/oauth: login() needs a backend when it didn't go through
    # authenticate(), and modules/audit logs the method.
    request.auth_provider = "login_link"
    login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
    return 204, None
