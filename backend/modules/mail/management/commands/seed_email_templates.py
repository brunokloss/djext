from django.core.management.base import BaseCommand
from post_office.models import EmailTemplate

TEMPLATES = [
    {
        "name": "welcome",
        "description": "Example: a greeting with a button. Edit it in the admin.",
        "subject": "Welcome, {{ name }}!",
        "content": "Hi {{ name }},\n\nWelcome aboard. Open {{ url }} to get started.\n",
        "html_content": (
            '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
            "<h1>Welcome, {{ name }}!</h1>"
            "<p>Your account is ready.</p>"
            '<p><a href="{{ url }}" style="display:inline-block;padding:10px 18px;'
            'background:#2563eb;color:#fff;border-radius:6px;text-decoration:none">'
            "Get started</a></p></div>"
        ),
    },
    {
        "name": "password_reset",
        "description": "Example: a link that expires. Edit it in the admin.",
        "subject": "Reset your password",
        "content": (
            "Hi {{ name }},\n\nReset it here: {{ url }}\nThe link expires in 1 hour.\n"
        ),
        "html_content": (
            '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
            "<h1>Reset your password</h1>"
            "<p>Hi {{ name }}, use the button below. It expires in 1 hour.</p>"
            '<p><a href="{{ url }}" style="display:inline-block;padding:10px 18px;'
            'background:#dc2626;color:#fff;border-radius:6px;text-decoration:none">'
            "Choose a new password</a></p></div>"
        ),
    },
    {
        "name": "invoice",
        "description": "Example: sent with the invoice attached.",
        "subject": "Invoice {{ number }}",
        "content": (
            "Hi {{ name }},\n\nInvoice {{ number }} is attached. Total: {{ total }}.\n"
        ),
        "html_content": (
            '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
            "<h1>Invoice {{ number }}</h1>"
            "<p>Hi {{ name }}, the invoice is attached. Total: <b>{{ total }}</b>.</p>"
            "</div>"
        ),
    },
]


class Command(BaseCommand):
    help = "Create the example email templates (Admin › Post Office › Email templates)."

    def handle(self, *args, **options):
        for data in TEMPLATES:
            _, created = EmailTemplate.objects.get_or_create(
                name=data["name"], defaults=data
            )
            self.stdout.write(
                f"  {'created' if created else 'exists '}  {data['name']}"
            )
