"""Sentry: errors and traces, off while SENTRY_DSN is empty.

The frontend (@sentry/nextjs) starts the trace in the browser and sends it in
the `sentry-trace` and `baggage` headers, which the Next proxy passes on, so a
click in the browser and the error it causes here show up in the same trace.
"""

import sentry_sdk
import structlog
from django.core.exceptions import MiddlewareNotUsed
from sentry_sdk.integrations.django import DjangoIntegration


def _add_request_id(event, hint):
    # The same id as in the logs (modules/log), to find their lines.
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id:
        event.setdefault("tags", {})["request_id"] = request_id
    return event


def user_processor(request):
    """Puts the user's id (the username, a UUID in djext's User) on the
    event, so Sentry counts the users an error hit and can filter by one.
    Only the id: never the email or the name.

    Reads request.user when the event is sent, not when the request comes
    in: the Bearer auth (modules/bearer/security.py) only sets it in the view.
    No extra query: the request log reads the same lazy user anyway.
    """

    def processor(event, hint):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            event["user"] = {"id": user.username}
        return event

    return processor


class SentryUserMiddleware:
    """Adds user_processor to the request's own Sentry scope (the Django
    integration opens one per request). Not used without Sentry: the scope
    would then be shared, and each request would add one more processor."""

    def __init__(self, get_response):
        if not sentry_sdk.is_initialized():
            raise MiddlewareNotUsed
        self.get_response = get_response

    def __call__(self, request):
        sentry_sdk.get_isolation_scope().add_event_processor(user_processor(request))
        return self.get_response(request)


def init_sentry(dsn: str, environment: str, traces_sample_rate: float) -> None:
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        integrations=[DjangoIntegration()],
        # No emails, IPs, cookies or request bodies leave for Sentry (LGPD).
        # Of the user, only the id (SentryUserMiddleware). The request_id tag
        # leads to the logs.
        send_default_pii=False,
        # Not the local variables of each frame: they hold tokens, keys and
        # personal data when a call fails.
        include_local_variables=False,
        before_send=_add_request_id,
        before_send_transaction=_add_request_id,
    )
