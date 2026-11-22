from django.conf import settings
from django.core import checks


@checks.register(checks.Tags.security)
def login_link_or_password(app_configs, **kwargs):
    """The login link takes the password's place, not a seat next to it: one
    or the other, so the login page has one email field and one button."""
    if settings.AUTH_MAGIC_LINK and settings.AUTH_PASSWORD:
        return [
            checks.Error(
                "AUTH_MAGIC_LINK and AUTH_PASSWORD are both on.",
                hint="Pick one: set AUTH_PASSWORD=False to log in by link.",
                id="signup.E001",
            )
        ]
    return []
