from datetime import datetime
from uuid import UUID

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.security import django_auth

from .sessions import end_sessions

router = Router()


class NotFoundOut(Schema):
    detail: str


class SessionOut(Schema):
    id: UUID
    logged_in_at: datetime | None
    ip: str | None
    user_agent: str
    # The session this request came with.
    current: bool


# Session auth, so the CSRF token is checked on DELETE.
@router.get(
    "/auth/sessions", response=list[SessionOut], auth=django_auth, tags=["auth"]
)
def list_sessions(request: HttpRequest):
    """Where you are logged in, newest first."""
    key = request.session.session_key
    return [
        {
            "id": s.public_id,
            "logged_in_at": s.logged_in_at,
            "ip": s.ip,
            "user_agent": s.user_agent,
            "current": s.session_key == key,
        }
        for s in request.auth.sessions.live().order_by("-logged_in_at")
    ]


@router.delete(
    "/auth/sessions/{uuid:session_id}",
    response={204: None, 404: NotFoundOut},
    auth=django_auth,
    tags=["auth"],
)
def end_session(request: HttpRequest, session_id: UUID):
    """Logs that session out. Ending the current one is a logout."""
    if not end_sessions(request, request.auth, public_id=session_id):
        return 404, {"detail": "Not found"}
    return 204, None


@router.delete(
    "/auth/sessions",
    response={204: None},
    auth=django_auth,
    tags=["auth"],
)
def end_all_sessions(request: HttpRequest, keep_current: bool = False):
    """Logs out everywhere, here too (a logout), or with `keep_current` only
    everywhere else."""
    end_sessions(request, request.auth, keep_current=keep_current)
    return 204, None
