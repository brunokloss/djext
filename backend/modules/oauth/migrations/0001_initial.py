import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserIdentity",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "public_id",
                    models.UUIDField(default=uuid.uuid7, editable=False, unique=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "provider",
                    models.CharField(
                        help_text="google, microsoft, mock", max_length=30
                    ),
                ),
                (
                    "uid",
                    models.CharField(
                        help_text="The `sub` claim: their id there", max_length=255
                    ),
                ),
                (
                    "metadata",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="What the provider said about them",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text="Who logs in with it",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="identities",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "user identities",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("provider", "uid"), name="oauth_identity_unique"
                    )
                ],
            },
        ),
    ]
