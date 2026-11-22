from django.db import migrations

# The login link's email (services.request_login_link), as in
# 0002_email_templates.py: edit it in the admin; an existing one is left as
# it is. The link expires after PASSWORD_RESET_TIMEOUT (1 hour).
TEMPLATE = {
    "name": "login_link",
    "description": "A link that logs in (modules/signup, AUTH_MAGIC_LINK).",
    "subject": "Your login link",
    "content": (
        "{% autoescape off %}Hi{% if name %} {{ name }}{% endif %},\n\nLog in "
        "with this link: {{ url }}\nIt works once and expires in 1 hour. If you "
        "didn't ask for it, ignore this email.\n{% endautoescape %}"
    ),
    "html_content": (
        '<div style="font-family:sans-serif;max-width:480px;margin:0 auto">'
        "<h1>Your login link</h1>"
        "<p>Hi{% if name %} {{ name }}{% endif %}, use the button below to log "
        "in. It works once and expires in 1 hour.</p>"
        '<p><a href="{{ url }}" style="display:inline-block;padding:10px 18px;'
        'background:#2563eb;color:#fff;border-radius:6px;text-decoration:none">'
        "Log in</a></p>"
        "<p>If you didn't ask for it, ignore this email.</p></div>"
    ),
}


def create_template(apps, schema_editor):
    EmailTemplate = apps.get_model("post_office", "EmailTemplate")
    EmailTemplate.objects.get_or_create(
        name=TEMPLATE["name"], language="", defaults=TEMPLATE
    )


class Migration(migrations.Migration):
    dependencies = [("signup", "0002_email_templates")]

    operations = [
        migrations.RunPython(create_template, migrations.RunPython.noop),
    ]
