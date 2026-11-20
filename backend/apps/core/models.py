import uuid

from django.db import models


class BaseModel(models.Model):
    """What the project's models have: an internal integer `id`, a public
    UUIDv7 (the one the API and URLs show; never expose `id`) and when the row
    was created and last changed. Modules don't use it (they can't import an
    app): each declares these fields itself.

    No `class Audit` here on purpose: children would inherit it, and the
    audit's check (audit.W001) would stop asking each new model to decide."""

    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# The project's models start here, on BaseModel.
