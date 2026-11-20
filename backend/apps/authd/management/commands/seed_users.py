from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

PASSWORD = "password"

USERS = [
    {"email": "admin@example.com", "first_name": "Admin", "is_superuser": True},
    {
        "email": "ana@example.com",
        "first_name": "Ana",
        "last_name": "Lima",
        "phone_number": "+5511912345678",
    },
    {"email": "bruno@example.com", "first_name": "Bruno", "last_name": "Costa"},
    {"email": "carla@example.com", "first_name": "Carla", "last_name": "Souza"},
]


class Command(BaseCommand):
    help = f"Create example users, all with the password '{PASSWORD}' (DEBUG only)."

    def handle(self, *args, **options):
        # Known passwords: never on a real server.
        if not settings.DEBUG:
            raise CommandError("Refusing to run with DEBUG=False.")
        User = get_user_model()
        for data in USERS:
            fields = dict(data)
            email = fields.pop("email")
            if User.objects.filter(email=email).exists():
                self.stdout.write(f"  exists   {email}")
                continue
            if fields.pop("is_superuser", False):
                User.objects.create_superuser(email, PASSWORD, **fields)
            else:
                User.objects.create_user(email, PASSWORD, **fields)
            self.stdout.write(f"  created  {email}")
        self.stdout.write(self.style.SUCCESS(f"Password for all: {PASSWORD}"))
