from django.db import migrations

# The emails this module sends (account.py). Created here, not only by
# `make db-seed`, so they exist wherever it is migrated. Edit them in the
# admin (Post Office › Email templates); an existing one is left as it is.
# The links expire after PASSWORD_RESET_TIMEOUT (1 hour).
TEMPLATES = [
    {
        "name": "verify_email",
        "description": "Sign-up: the link that activates the account (modules/signup).",
        "subject": "Confirm your email",
        "content": (
            "Hi {{ name }},\n\nConfirm your email to activate your account: "
            "{{ url }}\nThe link expires in 1 hour.\n"
        ),
        "html_content": (
            '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
            "<h1>Confirm your email</h1>"
            "<p>Hi {{ name }}, use the button below to activate your account. "
            "It expires in 1 hour.</p>"
            '<p><a href="{{ url }}" style="display:inline-block;padding:10px 18px;'
            'background:#2563eb;color:#fff;border-radius:6px;text-decoration:none">'
            "Confirm my email</a></p></div>"
        ),
    },
    {
        "name": "password_reset",
        "description": "Password reset: a link that expires (modules/signup).",
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
]


def create_templates(apps, schema_editor):
    EmailTemplate = apps.get_model("post_office", "EmailTemplate")
    for data in TEMPLATES:
        EmailTemplate.objects.get_or_create(
            name=data["name"], language="", defaults=data
        )


class Migration(migrations.Migration):
    dependencies = [
        ("signup", "0001_initial"),
        ("post_office", "0014_alter_email_recipient_delivery_status_and_more"),
    ]

    operations = [
        migrations.RunPython(create_templates, migrations.RunPython.noop),
    ]
