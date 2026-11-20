import base64

import tink
from django.core.management.base import BaseCommand
from tink import aead, proto_keyset_format, secret_key_access
from tink.testing import fake_kms


class Command(BaseCommand):
    # It is how you get the key the checks ask for.
    requires_system_checks = []
    help = "Prints a new fake-kms:// master key for CRYPTO_KMS_URI (development only)."

    def handle(self, *args, **options):
        aead.register()
        handle = tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM)
        keyset = proto_keyset_format.serialize(handle, secret_key_access.TOKEN)
        key = base64.urlsafe_b64encode(keyset).decode().rstrip("=")
        self.stdout.write(f"CRYPTO_KMS_URI={fake_kms.FAKE_KMS_PREFIX}{key}")
