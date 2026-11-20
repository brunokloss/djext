from django.apps import AppConfig


class CryptoConfig(AppConfig):
    name = "modules.crypto"
    verbose_name = "Crypto"

    def ready(self):
        from . import checks  # noqa: F401
