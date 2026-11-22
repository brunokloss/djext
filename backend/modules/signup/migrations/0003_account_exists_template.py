from django.db import migrations

# Sent when someone signs up with an email that has an account: only the
# inbox learns it. reset_url is empty when AUTH_PASSWORD_RESET is off. Edit it
# in the admin; an existing one is left as it is.
TEMPLATE = {
    "name": "account_exists",
    "description": "Sign-up with an email that has an account (modules/signup).",
    "subject": "You already have an account",
    "content": (
        "{% autoescape off %}Hi {{ name }},\n\nSomeone tried to sign up with "
        "this email, but it already has an account. Log in: {{ login_url }}\n"
        "{% if reset_url %}Forgot your password? {{ reset_url }}\n{% endif %}"
        "If it wasn't you, ignore this email.\n{% endautoescape %}"
    ),
    "html_content": (
        '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
        "<h1>You already have an account</h1>"
        "<p>Hi {{ name }}, someone tried to sign up with this email, but it "
        "already has an account.</p>"
        '<p><a href="{{ login_url }}" style="display:inline-block;padding:10px 18px;'
        'background:#2563eb;color:#fff;border-radius:6px;text-decoration:none">'
        "Log in</a></p>"
        '{% if reset_url %}<p>Forgot your password? <a href="{{ reset_url }}">'
        "Choose a new one</a>.</p>{% endif %}"
        "<p>If it wasn't you, ignore this email.</p></div>"
    ),
}


def create_template(apps, schema_editor):
    EmailTemplate = apps.get_model("post_office", "EmailTemplate")
    EmailTemplate.objects.get_or_create(
        name=TEMPLATE["name"], language="", defaults=TEMPLATE
    )


class Migration(migrations.Migration):
    dependencies = [("signup", "0002_email_templates")]

    operations = [migrations.RunPython(create_template, migrations.RunPython.noop)]
