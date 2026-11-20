from django.http import HttpRequest
from ninja.security import HttpBearer, django_auth


class BearerAuth(HttpBearer):
    """`Authorization: Bearer <key>`, for clients that aren't the browser.

    Sets request.user too, so the rate limits, the /users/me cache, the audit
    log and the request log see who it is, as with a session.
    """

    def authenticate(self, request: HttpRequest, token: str):
        # Imported here: keys.py imports authd's signals, which import the
        # its API, which imports this module.
        from .keys import check

        if (user := check(token)) is not None:
            request.user = user
        return user


# For endpoints that programs may call too: a Bearer key or the session.
# Bearer first: the session auth checks CSRF on POST, PUT and DELETE before it
# looks at the cookie, so a program (no cookie, no CSRF token) would get a 403
# there instead of reaching its key.
user_auth = [BearerAuth(), django_auth]
