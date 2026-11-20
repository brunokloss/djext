import uuid

from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models, transaction
from django.db.models.functions import Lower
from phonenumber_field.modelfields import PhoneNumberField

from modules.signals.signals import action_performed


def new_username() -> str:
    return str(uuid.uuid7())


class UserManager(DjangoUserManager):
    """Stock manager, but the username is optional (a UUID is generated)."""

    @classmethod
    def normalize_email(cls, email):
        # The whole email, not only the domain like Django: people type it in
        # any case. AbstractUser.clean() uses this too, so the admin does.
        return (email or "").strip().lower()

    def _create_user_object(self, username, email, password, **extra_fields):
        return super()._create_user_object(
            username or new_username(), email, password, **extra_fields
        )

    def create_user(self, email=None, password=None, **extra_fields):
        username = extra_fields.pop("username", None)
        return super().create_user(username, email, password, **extra_fields)

    async def acreate_user(self, email=None, password=None, **extra_fields):
        username = extra_fields.pop("username", None)
        return await super().acreate_user(username, email, password, **extra_fields)

    def create_superuser(self, email=None, password=None, **extra_fields):
        username = extra_fields.pop("username", None)
        return super().create_superuser(username, email, password, **extra_fields)


# Swapping the user model later is painful, so the project starts with its own.
# Stock Django user, except: the username is a generated UUIDv7 that works as
# the public id (never expose `id`), and people log in with their email (see
# backends.py).
class User(AbstractUser):
    username = models.CharField(
        "username",
        max_length=150,
        unique=True,
        default=new_username,
        editable=False,
        validators=[AbstractUser.username_validator],
    )
    email = models.EmailField("email address")
    # Stored in E.164 (+5511912345678); "" when there is none.
    phone_number = PhoneNumberField("phone number", blank=True)
    updated_at = models.DateTimeField("last updated", auto_now=True)

    objects = UserManager()

    # Read by modules/audit, if it's installed: every change to a user is
    # logged, and deleting them deletes those logs (see its log.py).
    class Audit:
        subjects = ["self"]
        exclude = ["last_login", "updated_at"]
        mask = ["password"]

    class Meta(AbstractUser.Meta):
        constraints = [
            # Unique whatever the case, even if an email skipped normalize_email.
            models.UniqueConstraint(
                Lower("email"),
                name="user_email_unique",
                violation_error_message="A user with that email already exists.",
            ),
        ]

    def __str__(self):
        return self.email

    # Used by the admin header ("Welcome, ..."); the username is just a UUID.
    def get_short_name(self):
        return self.first_name or self.email

    def anonymize(self, request=None):
        """Anonymizing a user (LGPD): the admin's "Anonymize" calls it.

        What to erase is each project's call (its legal obligations), so it is
        all written here, by hand: drop the line of a module you removed, add
        what your apps keep about them. Their email, names and phone stay on
        the user as it is. One transaction, logged with who asked. `request`
        is None from the shell.
        """
        from modules.audit import log as audit
        from modules.bearer.keys import revoke
        from modules.crypto.crypto import shred
        from modules.idempotency.models import IdempotencyKey
        from modules.mail.emails import delete_emails_to
        from modules.oauth.models import UserIdentity
        from modules.session import sessions

        with transaction.atomic():
            action_performed.send(
                None, request=request, name="user.anonymize", target=self
            )
            # Blocked: they can't log in, and are logged out everywhere.
            self.is_active = False
            self.save(update_fields=["is_active"])
            sessions.forget(self)
            delete_emails_to(self.email)
            # Their id and what each provider said about them (email, name).
            UserIdentity.objects.filter(user=self).delete()
            revoke(request, self)
            # What was encrypted for them can't be read again.
            shred(request, self)
            # The stored responses may hold their data.
            IdempotencyKey.objects.filter(user=self).delete()
            # Last, so it masks what the lines above logged too.
            audit.forget(self.pk, self.email)
