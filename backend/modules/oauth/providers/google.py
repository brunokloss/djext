from django.conf import settings

from .base import Provider


def valid_issuer(claims: dict) -> bool:
    # Google uses both forms.
    return claims.get("iss") in {"https://accounts.google.com", "accounts.google.com"}


def email_verified(claims: dict) -> bool:
    return claims.get("email_verified") is True


def provider() -> Provider | None:
    if not settings.AUTH_GOOGLE_CLIENT_ID:
        return None
    return Provider(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        client_id=settings.AUTH_GOOGLE_CLIENT_ID,
        client_secret=settings.AUTH_GOOGLE_CLIENT_SECRET,
        valid_issuer=valid_issuer,
        email_verified=email_verified,
    )
