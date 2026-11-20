from django.conf import settings

from .base import Provider


def valid_issuer(claims: dict) -> bool:
    return claims.get("iss") == settings.AUTH_MOCK_URL


def email_verified(claims: dict) -> bool:
    return claims.get("email_verified") is True


def provider() -> Provider | None:
    """The fake provider from `manage.py oauth_mock`. Only with DEBUG=True: it
    logs in as any email typed into it."""
    if not (settings.DEBUG and settings.AUTH_MOCK_URL):
        return None
    return Provider(
        authorize_url=f"{settings.AUTH_MOCK_URL}/authorize",
        token_url=f"{settings.AUTH_MOCK_URL}/token",
        client_id="djext",
        client_secret="",
        valid_issuer=valid_issuer,
        email_verified=email_verified,
    )
