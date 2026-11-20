import django.core.serializers.json
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# A log is never edited. Besides being deleted, a row may only forget who did it
# (Django's SET_NULL on the actor when that user is deleted: actor, IP, browser and
# session go to empty, never change or come back) and be masked when its user is
# anonymized (log.forget: the object to "***" and each value to "***", keeping the
# keys). Postgres refuses anything else, even raw SQL from the app. Other
# databases (SQLite in development) keep only the check in AuditLog.save().
GUARD = """
CREATE FUNCTION audit_log_masked(v jsonb) RETURNS jsonb AS $$
    SELECT CASE WHEN v IS NULL THEN NULL ELSE (
        SELECT coalesce(jsonb_object_agg(key, '"***"'::jsonb), '{}'::jsonb)
        FROM jsonb_each(v)
    ) END;
$$ LANGUAGE sql IMMUTABLE;

CREATE FUNCTION audit_log_guard() RETURNS trigger AS $$
BEGIN
    IF ROW(NEW.id, NEW.created_at, NEW.action, NEW.content_type_id,
           NEW.object_id, NEW.request_id, NEW.subject_1, NEW.subject_2,
           NEW.subject_3, NEW.name)
       IS NOT DISTINCT FROM
       ROW(OLD.id, OLD.created_at, OLD.action, OLD.content_type_id,
           OLD.object_id, OLD.request_id, OLD.subject_1, OLD.subject_2,
           OLD.subject_3, OLD.name)
       AND (NEW.object_repr = OLD.object_repr OR NEW.object_repr = '***')
       AND (NEW.old_values IS NOT DISTINCT FROM OLD.old_values
            OR NEW.old_values = audit_log_masked(OLD.old_values))
       AND (NEW.new_values IS NOT DISTINCT FROM OLD.new_values
            OR NEW.new_values = audit_log_masked(OLD.new_values))
       AND (NEW.actor_id IS NULL OR NEW.actor_id = OLD.actor_id)
       AND (NEW.ip_address IS NULL OR NEW.ip_address = OLD.ip_address)
       AND (NEW.user_agent = '' OR NEW.user_agent = OLD.user_agent)
       AND (NEW.session_hash = '' OR NEW.session_hash = OLD.session_hash)
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_log rows cannot be changed';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_guard BEFORE UPDATE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_guard();
"""

UNGUARD = """
DROP TRIGGER audit_log_guard ON audit_log;
DROP FUNCTION audit_log_guard();
DROP FUNCTION audit_log_masked(jsonb);
"""


def run(sql):
    def apply(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(sql)

    return apply


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
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
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("create", "Create"),
                            ("update", "Update"),
                            ("delete", "Delete"),
                            ("m2m", "M2M"),
                            ("login", "Login"),
                            ("logout", "Logout"),
                            ("login_failed", "Login Failed"),
                            ("action", "Action"),
                        ],
                        help_text="What was done",
                        max_length=20,
                    ),
                ),
                (
                    "object_id",
                    models.CharField(help_text="The object's id", max_length=64),
                ),
                (
                    "name",
                    models.CharField(
                        blank=True,
                        help_text="For an action, what was done (auth.end_sessions)",
                        max_length=100,
                    ),
                ),
                (
                    "object_repr",
                    models.CharField(
                        blank=True,
                        help_text="The object when it was logged",
                        max_length=200,
                        verbose_name="object",
                    ),
                ),
                (
                    "old_values",
                    models.JSONField(
                        blank=True,
                        encoder=django.core.serializers.json.DjangoJSONEncoder,
                        help_text="Values before",
                        null=True,
                    ),
                ),
                (
                    "new_values",
                    models.JSONField(
                        blank=True,
                        encoder=django.core.serializers.json.DjangoJSONEncoder,
                        help_text="Values after",
                        null=True,
                    ),
                ),
                (
                    "ip_address",
                    models.GenericIPAddressField(
                        blank=True, help_text="The browser's IP", null=True
                    ),
                ),
                (
                    "user_agent",
                    models.TextField(blank=True, help_text="The browser's User-Agent"),
                ),
                (
                    "session_hash",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text="HMAC of the session key salted with the user (groups one login)",
                        max_length=64,
                    ),
                ),
                (
                    "request_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        help_text="X-Request-Id (finds the request's lines in the logs)",
                        max_length=64,
                    ),
                ),
                ("subject_1", models.CharField(blank=True, max_length=100, null=True)),
                ("subject_2", models.CharField(blank=True, max_length=100, null=True)),
                ("subject_3", models.CharField(blank=True, max_length=100, null=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        help_text="Who did it",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="user",
                    ),
                ),
                (
                    "content_type",
                    models.ForeignKey(
                        db_index=False,
                        help_text="The model of the object",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="contenttypes.contenttype",
                        verbose_name="model",
                    ),
                ),
            ],
            options={
                "db_table": "audit_log",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["content_type", "object_id", "-created_at"],
                        name="audit_log_content_057478_idx",
                    ),
                    models.Index(
                        condition=models.Q(("subject_1__isnull", False)),
                        fields=["subject_1"],
                        name="audit_log_subject_1_idx",
                    ),
                    models.Index(
                        condition=models.Q(("subject_2__isnull", False)),
                        fields=["subject_2"],
                        name="audit_log_subject_2_idx",
                    ),
                    models.Index(
                        condition=models.Q(("subject_3__isnull", False)),
                        fields=["subject_3"],
                        name="audit_log_subject_3_idx",
                    ),
                ],
            },
        ),
        migrations.RunPython(run(GUARD), run(UNGUARD)),
    ]
