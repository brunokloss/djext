import json
from io import StringIO

import tink
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from modules.signals.signals import action_performed

from . import checks, crypto
from .models import Keyset

User = get_user_model()


class Sent:
    """Collects action_performed while in the `with`."""

    def __enter__(self):
        self.actions = []
        action_performed.connect(self.receive, weak=False)
        return self.actions

    def receive(self, **kwargs):
        self.actions.append(kwargs)

    def __exit__(self, *exc):
        action_performed.disconnect(self.receive)


class CryptoTest(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.bia = User.objects.create_user(email="bia@example.com", password="x")

    def test_round_trip(self):
        data = crypto.encrypt(self.ana, b"secret")
        self.assertNotIn(b"secret", data)
        self.assertEqual(crypto.decrypt(self.ana, data), b"secret")
        text = crypto.encrypt_text(self.ana, "senha 123")
        self.assertIsInstance(text, str)
        self.assertEqual(crypto.decrypt_text(self.ana, text), "senha 123")

    def test_one_key_per_owner_made_on_first_use(self):
        self.assertFalse(Keyset.objects.exists())
        crypto.encrypt(self.ana, b"a")
        crypto.encrypt(self.ana, b"b")
        self.assertEqual(Keyset.objects.count(), 1)
        row = Keyset.objects.get()
        self.assertEqual(row.owner_id, str(self.ana.pk))
        # Stored wrapped by the master key, never in the clear.
        self.assertIn("encryptedKeyset", json.loads(row.keyset))

    def test_another_owner_cant_decrypt(self):
        data = crypto.encrypt(self.ana, b"secret")
        with self.assertRaises(crypto.NoKeyset):
            crypto.decrypt(self.bia, data)
        crypto.encrypt(self.bia, b"x")
        with self.assertRaises(tink.TinkError):
            crypto.decrypt(self.bia, data)

    def test_aad_binds_the_ciphertext(self):
        data = crypto.encrypt(self.ana, b"secret", aad=b"invoice:1")
        self.assertEqual(crypto.decrypt(self.ana, data, aad=b"invoice:1"), b"secret")
        with self.assertRaises(tink.TinkError):
            crypto.decrypt(self.ana, data, aad=b"invoice:2")

    def test_shred(self):
        data = crypto.encrypt(self.ana, b"secret")
        with Sent() as sent:
            self.assertTrue(crypto.shred(None, self.ana))
            self.assertFalse(crypto.shred(None, self.ana))
        self.assertEqual(
            [(s["name"], s["target"]) for s in sent], [("crypto.shred", self.ana)]
        )
        with self.assertRaises(crypto.NoKeyset):
            crypto.decrypt(self.ana, data)
        # A new key for new data; the old data stays unreadable.
        crypto.encrypt(self.ana, b"new")
        with self.assertRaises(tink.TinkError):
            crypto.decrypt(self.ana, data)

        self.assertEqual(Keyset.objects.count(), 1)

    def test_envelope(self):
        text = crypto.encrypt_envelope({"body": "olá"}, aad=b"msg:1")
        self.assertEqual(crypto.decrypt_envelope(text, aad=b"msg:1"), {"body": "olá"})
        with self.assertRaises(tink.TinkError):
            crypto.decrypt_envelope(text, aad=b"msg:2")
        self.assertFalse(Keyset.objects.exists())


class KeysetAdminTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="root@example.com", password="x"
        )
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.client.force_login(self.admin)

    def test_deleting_shreds(self):
        crypto.encrypt(self.ana, b"secret")
        row = Keyset.objects.get()
        url = reverse("admin:crypto_keyset_delete", args=[row.pk])
        with Sent() as sent:
            response = self.client.post(url, {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Keyset.objects.exists())
        self.assertEqual([s["target"] for s in sent], [self.ana])

    def test_the_user_page_shows_their_key_read_only(self):
        crypto.encrypt(self.ana, b"secret")
        row = Keyset.objects.get()
        url = reverse("admin:authd_user_change", args=[self.ana.pk])
        response = self.client.get(url)
        self.assertContains(response, row.public_id)
        self.assertNotContains(response, "crypto-keyset-owner_type-owner_id-0-DELETE")
        self.assertNotContains(response, row.keyset)

    def test_deleting_one_whose_owner_is_gone(self):
        crypto.encrypt(self.ana, b"secret")
        row = Keyset.objects.get()
        self.ana.delete()
        url = reverse("admin:crypto_keyset_delete", args=[row.pk])
        response = self.client.post(url, {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Keyset.objects.exists())


class KmsUriTest(SimpleTestCase):
    def ids(self):
        errors = checks.kms_uri(None) + checks.fake_kms_in_production(None)
        return [e.id for e in errors]

    def test_command_makes_a_working_key(self):
        out = StringIO()
        call_command("crypto_fake_kms_uri", stdout=out)
        name, uri = out.getvalue().strip().split("=", 1)
        self.assertEqual(name, "CRYPTO_KMS_URI")
        crypto.master.cache_clear()
        try:
            with override_settings(CRYPTO_KMS_URI=uri):
                text = crypto.encrypt_envelope({"a": 1}, aad=b"r")
                self.assertEqual(crypto.decrypt_envelope(text, aad=b"r"), {"a": 1})
        finally:
            crypto.master.cache_clear()

    @override_settings(CRYPTO_KMS_URI="")
    def test_empty_is_an_error(self):
        self.assertEqual(self.ids(), ["crypto.E001"])

    @override_settings(CRYPTO_KMS_URI="fake-kms://x", DEBUG=False)
    def test_fake_kms_needs_debug(self):
        self.assertEqual(self.ids(), ["crypto.E002"])

    @override_settings(
        CRYPTO_KMS_URI="aws-kms://arn:aws:kms:us-east-1:0:key/k", DEBUG=False
    )
    def test_aws_kms_is_fine(self):
        self.assertEqual(self.ids(), [])
