"""Bearer keys: the one way to make, revoke and check them. The API and the
admin call these.

A key is BEARER_KEY_PREFIX plus 43 random characters. Only its HMAC (keyed with
SECRET_KEY) is stored, so changing SECRET_KEY invalidates every key. The
prefix lets `check` skip other Bearer tokens without a query.
"""

import secrets

from django.conf import settings
from django.http import HttpRequest
from django.utils.crypto import salted_hmac

from modules.signals.signals import action_performed

from .models import BearerKey

# How much of the key is kept in the clear, after BEARER_KEY_PREFIX.
VISIBLE_CHARS = 4


def hash_key(key: str) -> str:
    return salted_hmac("modules.bearer", key, algorithm="sha256").hexdigest()


def rotate(request: HttpRequest | None, user) -> tuple[BearerKey, str]:
    """Gives `user` a new key, replacing the old one (which stops working).
    Returns the row and the key itself: show it once, it can't be read back.
    `request` is None from the shell."""
    key = settings.BEARER_KEY_PREFIX + secrets.token_urlsafe(32)
    prefix = key[: len(settings.BEARER_KEY_PREFIX) + VISIBLE_CHARS]
    bearer_key, _ = BearerKey.objects.update_or_create(
        user=user, defaults={"key_hash": hash_key(key), "prefix": prefix}
    )
    action_performed.send(
        None,
        request=request,
        name="auth.bearer_rotate",
        values={"prefix": prefix},
        target=user,
    )
    return bearer_key, key


def revoke(request: HttpRequest | None, user) -> bool:
    """Deletes `user`'s key. False when they had none."""
    bearer_key = BearerKey.objects.filter(user=user).first()
    if bearer_key is None:
        return False
    bearer_key.delete()
    action_performed.send(
        None,
        request=request,
        name="auth.bearer_revoke",
        values={"prefix": bearer_key.prefix},
        target=user,
    )
    return True


def check(token: str):
    """The active user whose key `token` is, or None (security.py)."""
    if not token.startswith(settings.BEARER_KEY_PREFIX):
        return None
    bearer_key = (
        BearerKey.objects.select_related("user")
        .filter(key_hash=hash_key(token), user__is_active=True)
        .first()
    )
    return bearer_key.user if bearer_key else None
