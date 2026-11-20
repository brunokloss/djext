import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CronSchedule",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="created at"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="updated at"),
                ),
                (
                    "name",
                    models.CharField(max_length=300, unique=True, verbose_name="name"),
                ),
                (
                    "expression",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=100,
                        verbose_name="expression",
                    ),
                ),
                ("enabled", models.BooleanField(default=False, verbose_name="enabled")),
                (
                    "paused_until",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="paused until"
                    ),
                ),
                (
                    "notes",
                    models.TextField(blank=True, default="", verbose_name="notes"),
                ),
                (
                    "last_seen_in_code",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="last seen in code"
                    ),
                ),
                (
                    "last_run_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="last run at"
                    ),
                ),
                (
                    "last_enqueue_at",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="last enqueue at"
                    ),
                ),
                (
                    "is_last_enqueue_ok",
                    models.BooleanField(
                        blank=True, null=True, verbose_name="is last enqueue ok"
                    ),
                ),
                (
                    "last_enqueue_error",
                    models.TextField(
                        blank=True, default="", verbose_name="last enqueue error"
                    ),
                ),
            ],
            options={
                "verbose_name": "Cron Schedule",
                "verbose_name_plural": "Cron Schedules",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="CronRun",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="created at"),
                ),
                (
                    "task_result_id",
                    models.UUIDField(db_index=True, verbose_name="task result id"),
                ),
                (
                    "enqueued_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, verbose_name="enqueued at"
                    ),
                ),
                (
                    "schedule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="runs",
                        to="cron.cronschedule",
                        verbose_name="schedule",
                    ),
                ),
            ],
            options={
                "verbose_name": "Cron Run",
                "verbose_name_plural": "Cron Runs",
                "ordering": ["-enqueued_at"],
                "indexes": [
                    models.Index(
                        fields=["schedule", "-enqueued_at"],
                        name="cron_cronru_schedul_5ff668_idx",
                    )
                ],
            },
        ),
    ]
