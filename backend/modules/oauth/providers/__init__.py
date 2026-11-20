"""Log in with an OpenID Connect provider (the /auth/{provider} endpoints in
api.py): Authorization Code + PKCE, driven by the backend.

A provider is config, not code (one file each): URLs, credentials and how to
tell whether the email it returns really belongs to the user.
"""

import base64
import json
import secrets
import time
from typing import Literal

from authlib.integrations.requests_client import OAuth2Session
from django.http import HttpRequest

from . import google, microsoft, mock
from .base import Provider

# Every provider this module knows; configured() says which ones are on.
type Name = Literal["mock", "google", "microsoft"]

# In the order the login page shows them.
ALL = {"mock": mock, "google": google, "microsoft": microsoft}
# Their names on the login page's buttons.
LABELS = {"mock": "Mock", "google": "Google", "microsoft": "Microsoft"}


def configured() -> dict[str, Provider]:
    """The providers that are on (each one's settings are filled in)."""
    found = {name: module.provider() for name, module in ALL.items()}
    return {name: provider for name, provider in found.items() if provider}


def client(request: HttpRequest, name: str, provider: Provider) -> OAuth2Session:
    return OAuth2Session(
        client_id=provider.client_id,
        client_secret=provider.client_secret,
        scope="openid email profile",
        # On the frontend's host: requests come through the Next proxy (see
        # USE_X_FORWARDED_HOST in settings).
        redirect_uri=request.build_absolute_uri(f"/api/auth/{name}/callback"),
        code_challenge_method="S256",
    )


def id_token_claims(token: dict, provider: Provider, nonce: str) -> dict:
    """The claims of the ID token in a token response, once they say it was
    issued by this provider, for this client, for this login (`nonce`, sent
    with the authorization request) and hasn't expired.

    The signature isn't checked: the token came straight from the provider's
    token endpoint over TLS, which OpenID Connect accepts instead
    (Core 1.0, section 3.1.3.7). The other checks there still apply.
    """
    payload = token["id_token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if not provider.valid_issuer(claims):
        raise ValueError(f"ID token from another issuer: {claims.get('iss')}")
    if provider.client_id not in audiences:
        raise ValueError(f"ID token for another client: {aud}")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("ID token for another login (nonce)")
    if claims.get("exp", 0) <= time.time():
        raise ValueError("ID token expired")
    return claims
