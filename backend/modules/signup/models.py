import uuid

from django.conf import settings
from django.db import models


class Signup(models.Model):
    """A user who signed themselves up (/auth/signup). Only these are activated
    by verifying their email: an inactive user without one was blocked (or
    anonymized) by the team, and a link must not let them back in. The tokens
    in the emails are not stored (see tokens.py)."""

    # Public id (UUIDv7): the one the API and URLs show, never `id`.
    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="signup",
        help_text="Who signed up",
    )
    verified_at = models.DateTimeField(
        null=True, blank=True, help_text="When they verified their email"
    )

    class Meta:
        verbose_name = "sign-up"

    # Read by modules/audit, if it's installed: in that user's history.
    class Audit:
        subjects = ["user"]
        exclude = ["updated_at"]

    def __str__(self):
        return str(self.user)
