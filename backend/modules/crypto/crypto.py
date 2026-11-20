"""Envelope encryption with Tink: the one way to encrypt and decrypt.

Each owner (any model instance: a user, a company...) gets its own data key
(a Keyset row), made on first use and stored wrapped by the master key. The
master key never leaves the KMS named by CRYPTO_KMS_URI:

    aws-kms://arn:aws:kms:...   production (AWS KMS)
    fake-kms://<keyset>         development and tests, the key is in the URI
                                (`manage.py crypto_fake_kms_uri` makes one)

The KMS is only called to unwrap an owner's key; the unwrapped key is kept in
memory for the next calls. Deleting an owner's key (`shred`) makes all their
data unreadable for good.

    encrypt(owner, data) / decrypt(owner, data)            bytes
    encrypt_text(owner, text) / decrypt_text(owner, text)  str (base64)
    encrypt_envelope(payload, aad) / decrypt_envelope      dict, master key
    shred(request, owner)

`aad` (associated data) binds a ciphertext to where it lives, such as
"invoice:42:password": decrypting it with another `aad` fails, so it can't be
copied to another row. Pass the same value to both sides.
"""

import base64
import io
import json
import os
from functools import lru_cache

import tink
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from tink import aead
from tink.testing import fake_kms

from modules.signals.signals import action_performed

from .models import Keyset

# Tink's AES-GCM keys, for new_keyset() and the KMS clients.
aead.register()


class NoKeyset(Exception):
    """The owner has no key: never had data encrypted, or it was shredded."""


@lru_cache(maxsize=1)
def master() -> aead.Aead:
    uri = settings.CRYPTO_KMS_URI
    if uri.startswith("aws-kms://"):
        # Only here: it pulls in boto3.
        from tink.integration import awskms

        client = awskms.AwsKmsClient(uri, None)
    else:
        client = fake_kms.FakeKmsClient(uri)
    return client.get_aead(uri)


@lru_cache(maxsize=1024)
def unwrap(keyset: str) -> aead.Aead:
    """The owner's key, unwrapped by the KMS (one call per key and process)."""
    handle = tink.read_keyset_handle(tink.JsonKeysetReader(keyset), master())
    return handle.primitive(aead.Aead)


# The KMS client holds HTTPS connections, which a forked process (gunicorn
# --preload, ...) must not share with its parent.
os.register_at_fork(after_in_child=master.cache_clear)


def owner_key(owner) -> dict:
    return {
        "owner_type": ContentType.objects.get_for_model(owner),
        "owner_id": str(owner.pk),
    }


def new_keyset() -> str:
    handle = tink.new_keyset_handle(aead.aead_key_templates.AES256_GCM)
    out = io.StringIO()
    handle.write(tink.JsonKeysetWriter(out), master())
    return out.getvalue()


def keyset_of(owner, create: bool) -> aead.Aead:
    row = Keyset.objects.filter(**owner_key(owner)).first()
    if row is None:
        if not create:
            raise NoKeyset(f"{owner!r} has no key")
        try:
            with transaction.atomic():
                row = Keyset.objects.create(**owner_key(owner), keyset=new_keyset())
        except IntegrityError:
            # Another request made it first.
            row = Keyset.objects.get(**owner_key(owner))
    return unwrap(row.keyset)


def encrypt(owner, data: bytes, aad: bytes = b"") -> bytes:
    """`data` encrypted with `owner`'s key (made on first use)."""
    return keyset_of(owner, create=True).encrypt(data, aad)


def decrypt(owner, data: bytes, aad: bytes = b"") -> bytes:
    """Raises NoKeyset when the owner's key is gone, and
    tink.TinkError when `data` or `aad` don't match."""
    return keyset_of(owner, create=False).decrypt(data, aad)


def encrypt_text(owner, text: str, aad: bytes = b"") -> str:
    return base64.urlsafe_b64encode(encrypt(owner, text.encode(), aad)).decode()


def decrypt_text(owner, text: str, aad: bytes = b"") -> str:
    return decrypt(owner, base64.urlsafe_b64decode(text), aad).decode()


def encrypt_envelope(payload: dict, aad: bytes) -> str:
    """For data with no owner: `payload` encrypted with the master key itself.
    `aad` is required here: with no owner key, it is what keeps a copy in
    another record from decrypting (use the record's id). Every call goes to
    the KMS."""
    data = json.dumps(payload, ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(master().encrypt(data, aad)).decode()


def decrypt_envelope(text: str, aad: bytes) -> dict:
    return json.loads(master().decrypt(base64.urlsafe_b64decode(text), aad))


def shred(request: HttpRequest | None, owner) -> bool:
    """Deletes `owner`'s key: what was encrypted with it can't be read again,
    backups included. False when there was none. Sends `crypto.shred` with
    the owner as target. `request` is None from the shell."""
    deleted, _ = Keyset.objects.filter(**owner_key(owner)).delete()
    if not deleted:
        return False
    action_performed.send(None, request=request, name="crypto.shred", target=owner)
    return True
