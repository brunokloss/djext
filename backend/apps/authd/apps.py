from django.apps import AppConfig


class AuthdConfig(AppConfig):
    name = "apps.authd"
    # "auth" is Django's own.
    label = "authd"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.contrib.admin import site

        from . import signals  # noqa: F401
        from .forms import AdminLoginForm

        # Its password form counts failures like /api/auth/login.
        site.login_form = AdminLoginForm
