import uuid

from django.conf import settings
from django.contrib.sessions.base_session import AbstractBaseSession, BaseSessionManager
from django.db import models
from django.utils import timezone


class SessionQuerySet(models.QuerySet):
    def live(self):
        """Not expired (expired ones wait for the daily clearsessions)."""
        return self.filter(expire_date__gt=timezone.now())


class Session(AbstractBaseSession):
    """Django's session table plus whose session it is and where they logged
    in from, so a user's sessions can be listed and ended. The session store
    (sessions.py) fills these from the session data on every save."""

    # The public id (never the session key, which logs in whoever has it).
    # `id` can't be used: the session key is the primary key.
    public_id = models.UUIDField(default=uuid.uuid7, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        related_name="sessions",
    )
    logged_in_at = models.DateTimeField(null=True)
    ip = models.GenericIPAddressField(null=True)
    user_agent = models.CharField(max_length=256, blank=True)

    objects = BaseSessionManager.from_queryset(SessionQuerySet)()

    # Saved on every request that changes the session; logins and logouts are
    # already in the audit log.
    class Audit:
        skip = True

    @classmethod
    def get_session_store_class(cls):
        from .sessions import SessionStore

        return SessionStore

    def __str__(self):
        # Anonymous sessions have no user and no login time.
        who = str(self.user) if self.user else "Anonymous"
        if self.logged_in_at is None:
            return who
        return f"{who} since {self.logged_in_at:%Y-%m-%d %H:%M}"
