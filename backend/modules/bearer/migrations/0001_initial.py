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
            name="BearerKey",
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
                    "key_hash",
                    models.CharField(
                        editable=False,
                        help_text="HMAC-SHA256 of the key",
                        max_length=64,
                        unique=True,
                    ),
                ),
                (
                    "prefix",
                    models.CharField(
                        editable=False, help_text="The start of the key", max_length=32
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        help_text="Whose key it is: requests made with it act as them",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bearer_key",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "bearer key",
            },
        ),
    ]
