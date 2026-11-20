import logging
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.signals import user_login_failed
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from ninja import Router

from . import providers
from .models import UserIdentity

logger = logging.getLogger(__name__)

# Paths in full, like every app (see apps/authd/api/__init__.py).
router = Router()


# Log in with a provider (see providers/). The browser navigates (not fetch) to
# /auth/<provider>/start through the Next proxy, goes to the provider, and comes
# back to /auth/<provider>/callback, which starts the session and redirects to
# `next`. Errors go to /login?error=oauth_<reason>. Only existing, active users
# with the same verified email can log in: nobody is signed up this way. Both
# answer with a redirect (302, no body), never JSON.
OAUTH_SESSION_KEY = "oauth"


def login_options() -> list[dict]:
    """The providers that are on, for the login page (/auth/providers, in
    authd; returned on login_options_requested, in signals.py)."""
    return [
        {
            "name": name,
            "label": providers.LABELS[name],
            "url": f"/api/auth/{name}/start",
        }
        for name in providers.configured()
    ]


def oauth_error(
    request: HttpRequest, provider: str, reason: str, *, why: str = "", **credentials
) -> HttpResponseRedirect:
    """Back to /login with the reason. Sends Django's user_login_failed, like a
    wrong password does, so whoever listens (logs, lockouts) sees provider
    failures too. `why` goes in the signal only, when it says more than the
    page should.
    """
    user_login_failed.send(
        sender=__name__,
        credentials={"provider": provider, "reason": why or reason, **credentials},
        request=request,
    )
    return redirect(f"/login?error=oauth_{reason}")


@router.get("/auth/{provider}/start", response={302: None}, tags=["auth"])
def oauth_start(request: HttpRequest, provider: providers.Name, next: str = "/"):
    """Redirects to the provider's login page."""
    config = providers.configured().get(provider)
    if config is None:
        return oauth_error(request, provider, "not_configured")
    # Only same-origin paths, so `next` can't be an open redirect.
    if not next.startswith("/") or not url_has_allowed_host_and_scheme(next, None):
        next = "/"
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    # Comes back inside the ID token: a token made for another login (a
    # replayed or injected one) doesn't carry it.
    nonce = secrets.token_urlsafe(32)
    url, _ = providers.client(request, provider, config).create_authorization_url(
        config.authorize_url,
        state=state,
        code_verifier=code_verifier,
        nonce=nonce,
        prompt="select_account",
    )
    request.session[OAUTH_SESSION_KEY] = {
        "provider": provider,
        "state": state,
        "code_verifier": code_verifier,
        "nonce": nonce,
        "next": next,
    }
    return redirect(url)


@router.get("/auth/{provider}/callback", response={302: None}, tags=["auth"])
def oauth_callback(
    request: HttpRequest,
    provider: providers.Name,
    code: str = "",
    state: str = "",
    error: str = "",
):
    """The provider redirects here: starts the session and redirects to `next`."""
    # One use only: a reload or a replayed URL starts over.
    flow = request.session.pop(OAUTH_SESSION_KEY, None)
    if error:
        # E.g. access_denied when the user cancels on the provider.
        return oauth_error(request, provider, "cancelled")
    config = providers.configured().get(provider)
    if (
        config is None
        or not flow
        or flow["provider"] != provider
        or not secrets.compare_digest(state, flow["state"])
    ):
        return oauth_error(request, provider, "invalid_state")

    try:
        token = providers.client(request, provider, config).fetch_token(
            config.token_url, code=code, code_verifier=flow["code_verifier"]
        )
        claims = providers.id_token_claims(token, config, flow["nonce"])
    except Exception:
        logger.exception("OAuth token exchange with %s failed", provider)
        return oauth_error(request, provider, "failed")

    email = claims.get("email")
    if not email or not config.email_verified(claims):
        # Which claims came, to see why (without the email itself).
        logger.warning(
            "%s did not confirm the email: claims=%s", provider, sorted(claims)
        )
        return oauth_error(request, provider, "unverified_email", email=email)
    sub = claims.get("sub")
    if not sub:
        logger.warning("%s sent no sub claim", provider)
        return oauth_error(request, provider, "failed", email=email)

    # Who this account is, if they logged in with it before (even if the
    # email changed there); otherwise who has this email.
    identity = (
        UserIdentity.objects.filter(provider=provider, uid=sub)
        .select_related("user")
        .first()
    )
    User = get_user_model()
    if identity:
        user = identity.user
    else:
        try:
            user = User._default_manager.get(email__iexact=email)
        except User.DoesNotExist, User.MultipleObjectsReturned:
            # Like EmailBackend (emails are unique whatever the case).
            return oauth_error(request, provider, "no_account", email=email)
    if not user.is_active:
        # The page doesn't say the account exists.
        return oauth_error(request, provider, "no_account", why="inactive", email=email)

    # Named because login() needs a backend when it didn't go through
    # authenticate(); the project's first one, which also restores the user on
    # later requests (read from settings: a module doesn't name the app's).
    # Which provider, for whoever listens to user_logged_in (modules/audit).
    request.auth_provider = provider
    login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
    # After login(), so the change is logged as theirs and in this session.
    save_identity(identity, user, provider, sub, claims)
    return redirect(flow["next"])


# What to keep from the ID token about who they are there.
METADATA_CLAIMS = ("name", "email", "picture", "locale")


def save_identity(identity, user, provider, sub, claims):
    """Creates the identity, or updates what the provider says about them;
    saves only when that changed."""
    metadata = {k: claims[k] for k in METADATA_CLAIMS if k in claims}
    if identity is None:
        UserIdentity.objects.create(
            user=user, provider=provider, uid=sub, metadata=metadata
        )
    elif identity.metadata != metadata:
        identity.metadata = metadata
        identity.save(update_fields=["metadata", "updated_at"])
