import uuid

from django.conf import settings
from django.db import models


class BearerKey(models.Model):
    """A user's bearer key, for programs calling the API as them
    (`Authorization: Bearer <key>`). One per user: rotating replaces it.

    Only an HMAC of the key is kept (see keys.py), so the database never
    holds something that works as the key; `prefix` is the start of it, to
    tell keys apart.
    """

    # Public id (UUIDv7): the one the API and URLs show, never `id`.
    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bearer_key",
        help_text="Whose key it is: requests made with it act as them",
    )
    key_hash = models.CharField(
        max_length=64, unique=True, editable=False, help_text="HMAC-SHA256 of the key"
    )
    prefix = models.CharField(
        max_length=32, editable=False, help_text="The start of the key"
    )

    class Meta:
        verbose_name = "bearer key"

    # Read by modules/audit, if it's installed. Not logged as model changes:
    # keys.py sends `auth.bearer_rotate` and `auth.bearer_revoke` instead,
    # which also reach the auth channel of modules/log.
    class Audit:
        skip = True

    def __str__(self):
        return f"{self.prefix}…"
