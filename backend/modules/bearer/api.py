from datetime import datetime

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.security import django_auth

from .keys import revoke, rotate
from .models import BearerKey

router = Router()


class BearerKeyOut(Schema):
    # The start of the key, to tell it apart.
    prefix: str
    # When it was made (rotating makes a new one).
    rotated_at: datetime


class NewBearerKeyOut(BearerKeyOut):
    # The key itself: shown this once, it can't be read back.
    key: str


class NotFoundOut(Schema):
    detail: str


# Session auth only (with its CSRF check): a key can't make or delete keys,
# so a leaked one can't lock its owner out.
@router.get(
    "/auth/bearer-key",
    response={200: BearerKeyOut, 404: NotFoundOut},
    auth=django_auth,
    tags=["auth"],
)
def get_bearer_key(request: HttpRequest):
    """Your bearer key (only its start), or 404 when you have none."""
    bearer_key = BearerKey.objects.filter(user=request.auth).first()
    if bearer_key is None:
        return 404, {"detail": "Not found"}
    return {"prefix": bearer_key.prefix, "rotated_at": bearer_key.updated_at}


@router.post(
    "/auth/bearer-key", response={201: NewBearerKeyOut}, auth=django_auth, tags=["auth"]
)
def rotate_bearer_key(request: HttpRequest):
    """A new bearer key, replacing yours (the old one stops working). Send it as
    `Authorization: Bearer <key>`. Shown once: it can't be read back."""
    bearer_key, key = rotate(request, request.auth)
    return 201, {
        "prefix": bearer_key.prefix,
        "rotated_at": bearer_key.updated_at,
        "key": key,
    }


@router.delete(
    "/auth/bearer-key", response={204: None}, auth=django_auth, tags=["auth"]
)
def revoke_bearer_key(request: HttpRequest):
    """Deletes your bearer key (204 even when you had none)."""
    revoke(request, request.auth)
    return 204, None
