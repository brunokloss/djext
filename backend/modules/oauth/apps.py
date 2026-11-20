from django.apps import AppConfig


class OauthConfig(AppConfig):
    name = "modules.oauth"
    verbose_name = "OAuth"

    def ready(self):
        from . import signals  # noqa: F401
