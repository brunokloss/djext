from django.apps import AppConfig


class RuntimeConfig(AppConfig):
    name = "modules.runtime"
    verbose_name = "Runtime"

    def ready(self):
        from . import admin

        admin.install()
