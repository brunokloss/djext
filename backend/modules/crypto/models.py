import uuid

from django.contrib.contenttypes.models import ContentType
from django.db import models


class Keyset(models.Model):
    """The data key of one owner (a user, a company...): what encrypts their
    data. Stored wrapped by the master key (CRYPTO_KMS_URI), so the database
    alone can't decrypt anything.

    Deleting it (crypto.shred) makes everything encrypted with it unreadable,
    wherever the copies are, backups included.
    """

    # Public id (UUIDv7): the one the API and URLs show, never `id`.
    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    owner_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, help_text="What kind of thing owns it"
    )
    owner_id = models.CharField(max_length=64, help_text="The owner's primary key")
    keyset = models.TextField(
        editable=False, help_text="Tink keyset, wrapped by the master key (JSON)"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner_type", "owner_id"], name="crypto_keyset_owner_unique"
            ),
        ]

    # Read by modules/audit, if it's installed. Not logged as model changes
    # (the keyset is a secret): crypto.shred sends `crypto.shred` instead.
    class Audit:
        skip = True

    def __str__(self):
        return f"{self.owner_type.app_labeled_name} {self.owner_id}"
