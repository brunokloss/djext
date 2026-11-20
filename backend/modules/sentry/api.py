from django.http import HttpRequest
from ninja import Router, Schema
from ninja.security import django_auth

router = Router()


class ForbiddenOut(Schema):
    detail: str


class SentryTestError(Exception):
    """Raised on purpose by /debug/error."""


# Superusers only, so nobody else can flood Sentry. Session auth on a POST
# also checks CSRF.
@router.post(
    "/debug/error", response={403: ForbiddenOut}, auth=django_auth, tags=["debug"]
)
def debug_error(request: HttpRequest):
    """Fails with a 500 on purpose, to check that errors reach Sentry in the
    same trace as the browser's click (the "Send test error" button on the home
    page). 403 for everyone but superusers."""
    if not request.auth.is_superuser:
        return 403, {"detail": "Forbidden"}
    raise SentryTestError("Test error from /api/debug/error")
