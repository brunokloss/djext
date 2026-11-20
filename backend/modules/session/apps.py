from django.apps import AppConfig


class SessionConfig(AppConfig):
    name = "modules.session"
    verbose_name = "Sessions"

    def ready(self):
        from . import signals  # noqa: F401
