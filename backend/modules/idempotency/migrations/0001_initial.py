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
            name="IdempotencyKey",
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
                    "key",
                    models.CharField(
                        help_text="The Idempotency-Key header", max_length=255
                    ),
                ),
                (
                    "fingerprint",
                    models.CharField(
                        help_text="SHA-256 of method, path and body", max_length=64
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[("processing", "Processing"), ("done", "Done")],
                        default="processing",
                        max_length=10,
                    ),
                ),
                ("status", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("content_type", models.CharField(blank=True, max_length=255)),
                ("body", models.BinaryField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        help_text="Who sent it: keys of different users never meet",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "idempotency key",
                "indexes": [
                    models.Index(
                        fields=["created_at"], name="idempotency_created_9b771e_idx"
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "key"), name="idempotency_user_key"
                    )
                ],
            },
        ),
    ]
