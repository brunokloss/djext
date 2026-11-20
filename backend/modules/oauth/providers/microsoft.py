from django.conf import settings

from .base import Provider


def valid_issuer(claims: dict) -> bool:
    # /common: each account comes from its own tenant, personal accounts
    # included (PERSONAL_TENANT).
    tenant = claims.get("tid")
    return bool(tenant) and (
        claims.get("iss") == f"https://login.microsoftonline.com/{tenant}/v2.0"
    )


# Personal accounts (outlook.com...): Microsoft owns that tenant and the email.
PERSONAL_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"


def email_verified(claims: dict) -> bool:
    # Any tenant can put any email on its users, so a work or school email
    # counts only when xms_edov (an optional claim the app registration must
    # add to the ID token) says the tenant owns its domain. Not left to the
    # registration's removeUnverifiedEmailClaim, which this can't see.
    if not claims.get("email"):
        return False
    if claims.get("tid") == PERSONAL_TENANT:
        return True
    return claims.get("xms_edov") in (True, "true", "1")


def provider() -> Provider | None:
    if not settings.AUTH_MICROSOFT_CLIENT_ID:
        return None
    # /common takes work, school and personal accounts.
    base = "https://login.microsoftonline.com/common/oauth2/v2.0"
    return Provider(
        authorize_url=f"{base}/authorize",
        token_url=f"{base}/token",
        client_id=settings.AUTH_MICROSOFT_CLIENT_ID,
        client_secret=settings.AUTH_MICROSOFT_CLIENT_SECRET,
        valid_issuer=valid_issuer,
        email_verified=email_verified,
    )
