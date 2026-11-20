import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="Keyset",
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
                    "owner_id",
                    models.CharField(
                        help_text="The owner's primary key", max_length=64
                    ),
                ),
                (
                    "keyset",
                    models.TextField(
                        editable=False,
                        help_text="Tink keyset, wrapped by the master key (JSON)",
                    ),
                ),
                (
                    "owner_type",
                    models.ForeignKey(
                        help_text="What kind of thing owns it",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="contenttypes.contenttype",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("owner_type", "owner_id"),
                        name="crypto_keyset_owner_unique",
                    )
                ],
            },
        ),
    ]
