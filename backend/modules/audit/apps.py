from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "modules.audit"
    verbose_name = "Audit"

    def ready(self):
        from django.contrib import admin

        from . import checks, log, signals  # noqa: F401

        log.load()
        signals.connect()

        # The History page of each audited model shows its audit log, unless
        # its admin has a template of its own. The admin is already loaded:
        # django.contrib.admin comes first in INSTALLED_APPS.
        for model, model_admin in admin.site._registry.items():
            if model in log.AUDITED and model_admin.object_history_template is None:
                model_admin.object_history_template = "audit/object_history.html"
