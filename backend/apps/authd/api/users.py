from uuid import UUID

from django.contrib.auth import get_user_model
from django.http import Http404, HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router

from modules.bearer.security import user_auth
from modules.cache.decorators import cached_per_user

from .schemas import ErrorOut, MeOut, UserOut

router = Router()

# The cache name of /users/me; authd/signals.py drops it when its user changes.
ME_CACHE = "authd:me"


# Session or Bearer token: 401 without either. Declared before /users/{user_id} so
# "me" never reaches it.
@router.get("/users/me", response=MeOut, auth=user_auth, tags=["users"])
@cached_per_user(ME_CACHE, timeout=10 * 60)
def me(request: HttpRequest):
    """The logged-in user, with their groups and permissions. Cached for 10
    minutes; a login or a change to the user starts it over."""
    return request.auth


@router.get(
    "/users/{user_id}",
    response={200: UserOut, 404: ErrorOut},
    auth=user_auth,
    tags=["users"],
)
def get_user(request: HttpRequest, user_id: UUID):
    """Any user for superusers; others can only see themselves (404 otherwise,
    so ids can't be probed)."""
    if not request.auth.is_superuser and request.auth.username != str(user_id):
        raise Http404
    return get_object_or_404(get_user_model(), username=str(user_id))
