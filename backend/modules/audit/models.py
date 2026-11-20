from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class AuditLog(models.Model):
    """One change to a model in settings.AUDIT_MODELS: what changed, who did
    it and in which request. Written in the same transaction as the change,
    so a rollback drops both. Never edited, only forgotten: the actor when
    that user is deleted, the values when they are anonymized (log.forget).
    """

    class Action(models.TextChoices):
        CREATE = "create"
        UPDATE = "update"
        DELETE = "delete"
        M2M = "m2m"
        LOGIN = "login"
        LOGOUT = "logout"
        # object_repr is the email typed in, if it is one.
        LOGIN_FAILED = "login_failed"
        # Something a person did that is not a model change, sent by a module as
        # `action_performed` (modules/signals/signals.py): `name` says what
        # ("auth.end_sessions"), the object is what it was done to (or the
        # actor, when nothing).
        ACTION = "action"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(
        max_length=20, choices=Action.choices, help_text="What was done"
    )
    # Indexed first in Meta.indexes, so not on its own.
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="+",
        db_index=False,
        verbose_name="model",
        help_text="The model of the object",
    )
    object_id = models.CharField(max_length=64, help_text="The object's id")
    name = models.CharField(
        max_length=100,
        blank=True,
        help_text="For an action, what was done (auth.end_sessions)",
    )
    object_repr = models.CharField(
        "object", max_length=200, blank=True, help_text="The object when it was logged"
    )

    # The whole row before and after (None on create and delete). For M2M,
    # new_values is {field, operation, related_model, related_ids}.
    old_values = models.JSONField(
        null=True, blank=True, encoder=DjangoJSONEncoder, help_text="Values before"
    )
    new_values = models.JSONField(
        null=True, blank=True, encoder=DjangoJSONEncoder, help_text="Values after"
    )

    # Who, and from where. The actor goes to NULL when that user is deleted.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="user",
        help_text="Who did it",
    )
    ip_address = models.GenericIPAddressField(
        null=True, blank=True, help_text="The browser's IP"
    )
    user_agent = models.TextField(blank=True, help_text="The browser's User-Agent")
    session_hash = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="HMAC of the session key salted with the user (groups one login)",
    )
    request_id = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="X-Request-Id (finds the request's lines in the logs)",
    )

    # Whose data this is, as "app.model:pk" (subject_key): a user, a tenant...
    # Each model picks up to three (its Audit.subjects, in order). Deleting
    # a subject deletes none of its logs (see log.py's TODO).
    # NULL, not "", when empty: a partial index on IS NOT NULL is one that
    # both SQLite and Postgres use for "subject_1 = <key>".
    subject_1 = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    subject_2 = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001
    subject_3 = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]
        indexes = [
            # An object's history, newest first (the History page).
            models.Index(fields=["content_type", "object_id", "-created_at"]),
            # Every log that names a subject. Partial: an empty
            # column costs nothing.
            *(
                models.Index(
                    fields=[f"subject_{i}"],
                    name=f"audit_log_subject_{i}_idx",
                    condition=models.Q(**{f"subject_{i}__isnull": False}),
                )
                for i in (1, 2, 3)
            ),
        ]

    def __str__(self):
        model = self.content_type.model_class() if self.content_type else None
        name = model.__name__ if model else "?"
        # A failed login has no object id: the email typed in says who.
        which = self.object_id or self.object_repr
        return f"{self.action} {name} {which} by {self.actor or '-'}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Audit logs can't be changed.")
        super().save(*args, **kwargs)

    @property
    def subjects(self) -> list[str]:
        return [s for s in (self.subject_1, self.subject_2, self.subject_3) if s]
