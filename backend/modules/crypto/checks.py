from django.conf import settings
from django.core.checks import Error, register

PREFIXES = ("aws-kms://", "fake-kms://")


@register()
def kms_uri(app_configs, **kwargs):
    if settings.CRYPTO_KMS_URI.startswith(PREFIXES):
        return []
    return [
        Error(
            "CRYPTO_KMS_URI must start with aws-kms:// or fake-kms://.",
            hint="For development: `manage.py crypto_fake_kms_uri`.",
            id="crypto.E001",
        )
    ]


# With `check --deploy` (run in CI), like Django's own security checks: the
# test runner turns DEBUG off, so this can't run on every start.
@register(deploy=True)
def fake_kms_in_production(app_configs, **kwargs):
    if settings.CRYPTO_KMS_URI.startswith("fake-kms://") and not settings.DEBUG:
        return [
            Error(
                "CRYPTO_KMS_URI is a fake KMS (the key is in the URI) "
                "and DEBUG is off.",
                hint="Use an aws-kms:// key in production.",
                id="crypto.E002",
            )
        ]
    return []
