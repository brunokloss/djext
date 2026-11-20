"""Sign-up, email verification and password reset: one function per
operation, called by the API (api.py).

The requests that take an email (sign up, resend the verification, forgot the
password) do the same work and give the same answer whether the email has an
account or not, so they don't tell who has one: the password is hashed
anyway and the email is only sent when there is someone to send it to.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError, transaction
from django.utils import timezone
from post_office import mail

from modules.signals.signals import action_performed

from .models import Signup
from .tokens import reset_tokens, verify_tokens

User = get_user_model()

# The email templates (Post Office › Email templates in the admin), created
# by migrations/0002_email_templates.py.
VERIFY_TEMPLATE = "verify_email"
RESET_TEMPLATE = "password_reset"


def normalize_email(email: str) -> str:
    return User.objects.normalize_email(email)


def _send(request, user, template: str, path: str, token: str) -> None:
    """Queues the email with a link to `path` on the frontend. Built from the
    request's host, the one the Next proxy sends (X-Forwarded-Host), so it
    must be in ALLOWED_HOSTS."""
    url = request.build_absolute_uri(f"{path}?uid={user.username}&token={token}")
    mail.send(
        user.email,
        template=template,
        context={"name": user.get_short_name(), "url": url},
        render_on_delivery=True,
    )


def sign_up(request, email: str, password: str, first_name="", last_name=""):
    """Creates an inactive user and sends them the verification link. Raises
    ValidationError for a password that fails AUTH_PASSWORD_VALIDATORS. An
    email that has an account already gets nothing, unless it is still
    waiting for its verification: then the link goes again."""
    email = normalize_email(email)
    validate_password(
        password, User(email=email, first_name=first_name, last_name=last_name)
    )
    existing = User.objects.filter(email__iexact=email).first()
    if existing is not None:
        # As long as creating one takes.
        make_password(password)
        _resend(request, existing)
        return
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_active=False,
            )
            Signup.objects.create(user=user)
            action_performed.send(
                sign_up, request=request, name="auth.signup", target=user
            )
    except IntegrityError:
        # Someone else signed up with this email at the same time.
        return
    _send(request, user, VERIFY_TEMPLATE, "/verify", verify_tokens.make_token(user))


def _waiting(user) -> bool:
    """Signed up and not verified yet: never one the team blocked."""
    return (
        not user.is_active
        and Signup.objects.filter(user=user, verified_at__isnull=True).exists()
    )


def _resend(request, user) -> None:
    if _waiting(user):
        _send(request, user, VERIFY_TEMPLATE, "/verify", verify_tokens.make_token(user))


def resend_verification(request, email: str) -> None:
    user = User.objects.filter(email__iexact=normalize_email(email)).first()
    if user is not None:
        _resend(request, user)


def _user(uid: str):
    try:
        return User.objects.get(username=uid)
    except User.DoesNotExist, ValueError:
        return None


def verify(request, uid: str, token: str):
    """Activates the user the link was sent to. Returns them, or None when
    the link is wrong, expired or used already."""
    user = _user(uid)
    if user is None or not verify_tokens.check_token(user, token):
        return None
    with transaction.atomic():
        # Locked: two clicks on the link activate them once.
        signup = (
            Signup.objects.select_for_update()
            .filter(user=user, verified_at__isnull=True)
            .first()
        )
        if signup is None or user.is_active:
            return None
        signup.verified_at = timezone.now()
        signup.save(update_fields=["verified_at", "updated_at"])
        user.is_active = True
        user.save(update_fields=["is_active"])
        action_performed.send(
            verify, request=request, name="auth.verify_email", target=user
        )
    return user


def request_reset(request, email: str) -> None:
    """Sends the reset link to an active user with a password, like Django's
    PasswordResetForm: never to one who is blocked or waiting for their
    verification (resetting doesn't activate anyone)."""
    user = User.objects.filter(
        email__iexact=normalize_email(email), is_active=True
    ).first()
    if user is None or not user.has_usable_password():
        return
    _send(
        request, user, RESET_TEMPLATE, "/reset-password", reset_tokens.make_token(user)
    )
    action_performed.send(
        request_reset, request=request, name="auth.password_reset_request", target=user
    )


def reset_password(request, uid: str, token: str, password: str):
    """Sets the new password. Returns the user, or None when the link is wrong,
    expired or used already. Raises ValidationError for a password that fails
    AUTH_PASSWORD_VALIDATORS. Their sessions end: each one holds a hash of the
    old password (get_session_auth_hash)."""
    user = _user(uid)
    if user is None or not user.is_active or not reset_tokens.check_token(user, token):
        return None
    validate_password(password, user)
    with transaction.atomic():
        user.set_password(password)
        user.save(update_fields=["password"])
        action_performed.send(
            reset_password, request=request, name="auth.password_reset", target=user
        )
    return user
