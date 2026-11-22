from django.apps import AppConfig


class SignupConfig(AppConfig):
    name = "modules.signup"
    verbose_name = "Sign-up"

    def ready(self):
        from . import checks, signals  # noqa: F401
