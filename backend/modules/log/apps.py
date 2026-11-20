from django.apps import AppConfig


class LogConfig(AppConfig):
    name = "modules.log"
    verbose_name = "Log"

    def ready(self):
        from . import signals  # noqa: F401  (connects the receivers)
