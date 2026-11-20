"""Sign-up, email verification and password reset: the services the API
(api.py) calls. Nobody is logged in for these: the actor is anonymous, and
the actions name the user as their target.

The ones that take an email (sign up, resend the verification, forgot the
password) do the same work whether the email has an account or not, so the
answer doesn't tell who has one: the password is hashed anyway and the email
is only sent when there is someone to send it to.

Those that send a link take `site`, the frontend's address the link points to
("https://app.example.com"): the API builds it from the request.
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


def _send(site: str, user, template: str, path: str, token: str) -> None:
    """Queues the email with a link to `path` on the frontend."""
    url = f"{site.rstrip('/')}{path}?uid={user.username}&token={token}"
    mail.send(
        user.email,
        template=template,
        context={"name": user.get_short_name(), "url": url},
        render_on_delivery=True,
    )


def check(email: str, password: str, first_name="", last_name="") -> None:
    """Raises ValidationError for what sign_up() can't take: a bad email, a
    name too long, or a password that fails AUTH_PASSWORD_VALIDATORS. Asks
    nothing of the database (not even whether the email is taken), so the
    answer doesn't tell who has an account."""
    user = User(
        email=normalize_email(email), first_name=first_name, last_name=last_name
    )
    user.clean_fields(exclude=["username", "password"])
    validate_password(password, user)


def sign_up(site: str, email: str, password: str, first_name="", last_name=""):
    """Creates an inactive user and sends them the verification link; check()
    first. An email that has an account already gets nothing, unless it is
    still waiting for its verification: then the latest sign-up wins (its
    password and names, which kills the earlier links) and a new link goes.
    So someone who signed up with another person's email can't keep that
    account: the link asks for the password (verify())."""
    email = normalize_email(email)
    existing = User.objects.filter(email__iexact=email).first()
    if existing is not None:
        if _waiting(existing):
            existing.set_password(password)
            existing.first_name, existing.last_name = first_name, last_name
            existing.save(update_fields=["password", "first_name", "last_name"])
            _send_verification(site, existing)
        else:
            # As long as creating one takes.
            make_password(password)
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
            action_performed.send(sign_up, name="auth.signup", target=user)
    except IntegrityError:
        # Someone else signed up with this email at the same time.
        return
    _send_verification(site, user)


def _waiting(user) -> bool:
    """Signed up and not verified yet: never one the team blocked."""
    return (
        not user.is_active
        and Signup.objects.filter(user=user, verified_at__isnull=True).exists()
    )


def stop_waiting(user) -> None:
    """A user activated some other way than their link (the team, in the
    admin) is no longer waiting: blocked later, a link must not let them back
    in. On every save that may activate a user (signals.py)."""
    Signup.objects.filter(user=user, verified_at__isnull=True).update(
        verified_at=timezone.now(), updated_at=timezone.now()
    )


def _send_verification(site: str, user) -> None:
    _send(site, user, VERIFY_TEMPLATE, "/verify", verify_tokens.make_token(user))


def resend_verification(site: str, email: str) -> None:
    user = User.objects.filter(email__iexact=normalize_email(email)).first()
    if user is not None and _waiting(user):
        _send_verification(site, user)


def _user(uid: str):
    try:
        return User.objects.get(username=uid)
    except User.DoesNotExist, ValueError:
        return None


def verify(uid: str, token: str, password: str):
    """Activates the user the link was sent to, given the password they signed
    up with: a link alone would activate whatever password was typed, maybe
    by someone else. Returns them, or None when the link is wrong, expired or
    used already, or the password is wrong."""
    user = _user(uid)
    if user is None or not verify_tokens.check_token(user, token):
        return None
    if not user.check_password(password):
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
        action_performed.send(verify, name="auth.verify_email", target=user)
    return user


def request_reset(site: str, email: str) -> None:
    """Sends the reset link to an active user with a password, like Django's
    PasswordResetForm: never to one who is blocked or waiting for their
    verification (resetting doesn't activate anyone)."""
    user = User.objects.filter(
        email__iexact=normalize_email(email), is_active=True
    ).first()
    if user is None or not user.has_usable_password():
        return
    _send(site, user, RESET_TEMPLATE, "/reset-password", reset_tokens.make_token(user))
    action_performed.send(
        request_reset, name="auth.password_reset_request", target=user
    )


def reset_password(uid: str, token: str, password: str):
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
        action_performed.send(reset_password, name="auth.password_reset", target=user)
    return user
