from django.apps import AppConfig


class SignupConfig(AppConfig):
    name = "modules.signup"
    verbose_name = "Sign-up"

    def ready(self):
        from . import signals  # noqa: F401
