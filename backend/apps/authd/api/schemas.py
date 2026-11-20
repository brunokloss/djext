from datetime import datetime
from uuid import UUID

from django.utils import timezone
from ninja import Schema


class ErrorOut(Schema):
    detail: str


class UserOut(Schema):
    id: UUID
    email: str
    first_name: str
    last_name: str
    full_name: str
    # E.164 (+5511912345678), or "" when there is none.
    phone_number: str

    # The public id is the username (a UUID), never the database id.
    @staticmethod
    def resolve_id(obj) -> str:
        return obj.username

    @staticmethod
    def resolve_full_name(obj) -> str:
        return obj.get_full_name()

    @staticmethod
    def resolve_phone_number(obj) -> str:
        return str(obj.phone_number or "")


class MeOut(UserOut):
    """The logged-in user, with what they may do: their groups and every
    permission they have, as user.has_perm() takes it ("auth.add_group")."""

    is_staff: bool
    is_superuser: bool
    groups: list[str]
    permissions: list[str]
    # When this answer was built: an older one came from the cache.
    refreshed_at: datetime

    @staticmethod
    def resolve_groups(obj) -> list[str]:
        return sorted(obj.groups.values_list("name", flat=True))

    @staticmethod
    def resolve_permissions(obj) -> list[str]:
        # Their own and their groups' (all of them for a superuser).
        return sorted(obj.get_all_permissions())

    @staticmethod
    def resolve_refreshed_at(obj) -> datetime:
        return timezone.now()
