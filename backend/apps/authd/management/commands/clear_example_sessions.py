from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils.dateparse import parse_datetime

from modules.session.models import Session

from .seed_users import USERS


class Command(BaseCommand):
    help = (
        "Delete the sessions the end-to-end tests leave behind: logins of the "
        "example users and anonymous sessions, both since --since (DEBUG only)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--since", required=True, help="ISO 8601 date and time")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Refusing to run with DEBUG=False.")
        since = parse_datetime(options["since"])
        if not isinstance(since, datetime):
            raise CommandError("--since must be an ISO 8601 date and time.")
        emails = [user["email"] for user in USERS]
        # Anonymous sessions have no login time; their expiry tells when they
        # were last saved.
        saved_since = since + timedelta(seconds=settings.SESSION_COOKIE_AGE)
        deleted, _ = Session.objects.filter(
            Q(user__email__in=emails, logged_in_at__gte=since)
            | Q(user__isnull=True, expire_date__gte=saved_since)
        ).delete()
        self.stdout.write(f"  deleted  {deleted} test sessions")
