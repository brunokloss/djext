from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Note(BaseModel):
    """A note someone keeps for themselves. Only its owner sees it."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes"
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    # Each change goes to the audit log, under the owner's name.
    class Audit:
        subjects = ["owner"]
        exclude = ["updated_at"]

    def __str__(self):
        return self.title
