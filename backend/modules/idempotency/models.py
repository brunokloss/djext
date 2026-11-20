import uuid

from django.conf import settings
from django.db import models


class IdempotencyKey(models.Model):
    """One `Idempotency-Key` a user sent to an `@idempotent` endpoint, and the
    response it got, so a retry with the same key gets that response back
    instead of running the endpoint again (see decorators.py).

    `updated_at` doubles as the lock's heartbeat: a key still `processing`
    long after it (the process died mid-request) can be taken over."""

    # Public id (UUIDv7): the one the API and URLs show, never `id`.
    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class State(models.TextChoices):
        PROCESSING = "processing"
        DONE = "done"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        help_text="Who sent it: keys of different users never meet",
    )
    key = models.CharField(max_length=255, help_text="The Idempotency-Key header")
    fingerprint = models.CharField(
        max_length=64, help_text="SHA-256 of method, path and body"
    )
    state = models.CharField(
        max_length=10, choices=State.choices, default=State.PROCESSING
    )
    status = models.PositiveSmallIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=255, blank=True)
    body = models.BinaryField(null=True, blank=True)

    class Meta:
        verbose_name = "idempotency key"
        constraints = [
            models.UniqueConstraint(fields=["user", "key"], name="idempotency_user_key")
        ]
        indexes = [models.Index(fields=["created_at"])]

    # Read by modules/audit, if it's installed: a copy of API responses, not
    # something anyone edits.
    class Audit:
        skip = True

    def __str__(self):
        return self.key
