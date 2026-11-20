import uuid

from django.conf import settings
from django.db import models


class UserIdentity(models.Model):
    """A user's account at a provider: who `sub` is at Google, Microsoft...

    The first login with a provider finds the user by their verified email
    and creates this; later ones find them by it, even if the email changed
    there. Updated with what the provider says about them on each login.
    """

    # Public id (UUIDv7): the one the API and URLs show, never `id`.
    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="identities",
        help_text="Who logs in with it",
    )
    provider = models.CharField(max_length=30, help_text="google, microsoft, mock")
    uid = models.CharField(max_length=255, help_text="The `sub` claim: their id there")
    metadata = models.JSONField(
        default=dict, blank=True, help_text="What the provider said about them"
    )

    class Meta:
        verbose_name_plural = "user identities"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "uid"], name="oauth_identity_unique"
            ),
        ]

    # Read by modules/audit, if it's installed: changes are logged in the
    # user's history. Anonymizing them deletes these (signals.py).
    class Audit:
        subjects = ["user"]
        exclude = ["updated_at"]

    def __str__(self):
        return f"{self.provider}:{self.uid}"
