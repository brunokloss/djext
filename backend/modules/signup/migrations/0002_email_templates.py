from django.db import migrations

# The emails this module sends (services.py). Created here, not only by
# `make db-seed`, so they exist wherever it is migrated. Edit them in the
# admin (Post Office › Email templates); an existing one is left as it is.
# The links expire after PASSWORD_RESET_TIMEOUT (1 hour). The plain text is
# rendered with autoescape off: otherwise the & in the link becomes &amp;.
# account_exists goes to an email that has an account when someone signs up
# with it (only the inbox learns it); reset_url is empty when
# AUTH_PASSWORD_RESET is off.
TEMPLATES = [
    {
        "name": "verify_email",
        "description": "Sign-up: the link that activates the account (modules/signup).",
        "subject": "Confirm your email",
        "content": (
            "{% autoescape off %}Hi{% if name %} {{ name }}{% endif %},\n\nConfirm "
            "your email to start using your account: {{ url }}\nThe link expires "
            "in 1 hour. If you didn't sign up, ignore this email.\n"
            "{% endautoescape %}"
        ),
        "html_content": (
            '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
            "<h1>Confirm your email</h1>"
            "<p>Hi{% if name %} {{ name }}{% endif %}, use the button below to "
            "start using your account. It expires in 1 hour.</p>"
            "<p>If you didn't sign up, ignore this email.</p>"
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
            "{% autoescape off %}Hi{% if name %} {{ name }}{% endif %},\n\nSomeone "
            "asked to reset the password of your account. Choose a new one: "
            "{{ url }}\nThe link expires in 1 hour. If it wasn't you, ignore "
            "this email: your password stays the same.\n{% endautoescape %}"
        ),
        "html_content": (
            '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
            "<h1>Reset your password</h1>"
            "<p>Hi{% if name %} {{ name }}{% endif %}, someone asked to reset the "
            "password of your account. The button below expires in 1 hour.</p>"
            '<p><a href="{{ url }}" style="display:inline-block;padding:10px 18px;'
            'background:#dc2626;color:#fff;border-radius:6px;text-decoration:none">'
            "Choose a new password</a></p>"
            "<p>If it wasn't you, ignore this email: your password stays the "
            "same.</p></div>"
        ),
    },
    {
        "name": "account_exists",
        "description": "Sign-up with an email that has an account (modules/signup).",
        "subject": "You already have an account",
        "content": (
            "{% autoescape off %}Hi{% if name %} {{ name }}{% endif %},\n\nSomeone "
            "tried to sign up with this email, but it already has an account. "
            "Log in: {{ login_url }}\n"
            "{% if reset_url %}Forgot your password? {{ reset_url }}\n{% endif %}"
            "If it wasn't you, ignore this email.\n{% endautoescape %}"
        ),
        "html_content": (
            '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
            "<h1>You already have an account</h1>"
            "<p>Hi{% if name %} {{ name }}{% endif %}, someone tried to sign up "
            "with this email, but it already has an account.</p>"
            '<p><a href="{{ login_url }}" style="display:inline-block;padding:10px 18px;'
            'background:#2563eb;color:#fff;border-radius:6px;text-decoration:none">'
            "Log in</a></p>"
            '{% if reset_url %}<p>Forgot your password? <a href="{{ reset_url }}">'
            "Choose a new one</a>.</p>{% endif %}"
            "<p>If it wasn't you, ignore this email.</p></div>"
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
