"""Who is acting, for code that can't see the request: services, signal
receivers, tasks. So a service takes the user it acts for, not an HTTP
request, and the same service serves the API, the admin, a task or an MCP tool.

- In a request, `RequestContextMiddleware` keeps it in `current_request`, and
  the actor is the logged-in user.
- Outside one (a task, a command, an MCP tool), wrap the call in
  `with acting_as(user):` so the audit log and the logs know who did it.

Like signals.py, this imports nothing of ours: every module may use it.
"""

from contextlib import contextmanager
from contextvars import ContextVar

# The request being handled. None in the shell, commands, tasks and tools.
current_request = ContextVar("current_request", default=None)

_acting = ContextVar("acting_as", default=None)


@contextmanager
def acting_as(user):
    """Says who is acting when there is no request (or overrides it)."""
    token = _acting.set(user)
    try:
        yield
    finally:
        _acting.reset(token)


def request_user(request):
    """The request's logged-in user, or None."""
    user = getattr(request, "user", None)
    return user if user is not None and user.is_authenticated else None


def current_actor():
    """`acting_as`'s user, else the current request's logged-in user, else None."""
    user = _acting.get()
    return user if user is not None else request_user(current_request.get())


class RequestContextMiddleware:
    """Keeps the request where services and receivers can see it. Goes after
    AuthenticationMiddleware, so request.user is there."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            current_request.reset(token)
