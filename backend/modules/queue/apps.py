from django.apps import AppConfig


class QueueConfig(AppConfig):
    name = "modules.queue"
    verbose_name = "Queue"

    def ready(self):
        from . import admin

        admin.install()
