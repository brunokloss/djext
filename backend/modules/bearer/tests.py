from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from modules.signals.signals import action_performed

from . import keys
from .models import BearerKey

User = get_user_model()


def log_in(user) -> Client:
    """A browser logged in through the API, with CSRF checks on, like the
    frontend (every user here has the password "x")."""
    client = Client(enforce_csrf_checks=True)
    client.get("/api/auth/csrf")
    response = client.post(
        "/api/auth/login",
        {"email": user.email, "password": "x"},
        content_type="application/json",
        headers={"X-CSRFToken": client.cookies[settings.CSRF_COOKIE_NAME].value},
    )
    assert response.status_code == 200, response.content
    return client


def csrf(client: Client) -> dict:
    return {"X-CSRFToken": client.cookies[settings.CSRF_COOKIE_NAME].value}


def bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


class BearerKeyTest(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.browser = log_in(self.ana)
        # A program: no cookies, no CSRF token.
        self.program = Client(enforce_csrf_checks=True)

    def new_key(self) -> str:
        response = self.browser.post("/api/auth/bearer-key", headers=csrf(self.browser))
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["key"]

    def test_the_key_logs_a_program_in(self):
        key = self.new_key()
        self.assertTrue(key.startswith(settings.BEARER_KEY_PREFIX))
        response = self.program.get("/api/users/me", headers=bearer(key))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "ana@example.com")

    def test_only_its_hmac_is_stored(self):
        key = self.new_key()
        row = BearerKey.objects.get(user=self.ana)
        self.assertNotIn(key, (row.key_hash, row.prefix))
        self.assertEqual(row.key_hash, keys.hash_key(key))
        self.assertTrue(key.startswith(row.prefix))

    def test_get_shows_only_the_start(self):
        self.assertEqual(self.browser.get("/api/auth/bearer-key").status_code, 404)
        key = self.new_key()
        body = self.browser.get("/api/auth/bearer-key").json()
        self.assertEqual(set(body), {"prefix", "rotated_at"})
        self.assertTrue(key.startswith(body["prefix"]))

    def test_rotating_kills_the_old_key(self):
        old = self.new_key()
        new = self.new_key()
        self.assertEqual(BearerKey.objects.count(), 1)
        self.assertEqual(
            self.program.get("/api/users/me", headers=bearer(old)).status_code, 401
        )
        self.assertEqual(
            self.program.get("/api/users/me", headers=bearer(new)).status_code, 200
        )

    def test_revoking(self):
        key = self.new_key()
        headers = csrf(self.browser)
        response = self.browser.delete("/api/auth/bearer-key", headers=headers)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(BearerKey.objects.exists())
        self.assertEqual(
            self.program.get("/api/users/me", headers=bearer(key)).status_code, 401
        )

    def test_wrong_or_foreign_tokens_are_401(self):
        self.new_key()
        for token in (f"{settings.BEARER_KEY_PREFIX}wrong", "eyJhbGciOi.not-ours", ""):
            response = self.program.get("/api/users/me", headers=bearer(token))
            self.assertEqual(response.status_code, 401, token)

    def test_inactive_users_keys_stop_working(self):
        key = self.new_key()
        self.ana.is_active = False
        self.ana.save()
        self.assertEqual(
            self.program.get("/api/users/me", headers=bearer(key)).status_code, 401
        )

    def test_a_key_cant_make_or_delete_keys(self):
        # Else a leaked key could lock its owner out.
        key = self.new_key()
        for method in (self.program.get, self.program.post, self.program.delete):
            response = method("/api/auth/bearer-key", headers=bearer(key))
            self.assertIn(response.status_code, (401, 403))
        self.assertEqual(BearerKey.objects.get().key_hash, keys.hash_key(key))

    def test_the_session_still_works_with_csrf(self):
        self.assertEqual(self.browser.get("/api/users/me").status_code, 200)

    def test_rotate_and_revoke_send_actions(self):
        sent = []
        action_performed.connect(lambda **kw: sent.append(kw), weak=False)
        try:
            _, key = keys.rotate(None, self.ana)
            keys.revoke(None, self.ana)
            self.assertFalse(keys.revoke(None, self.ana))
        finally:
            action_performed.receivers.pop()
        self.assertEqual(
            [(s["name"], s["target"]) for s in sent],
            [("auth.bearer_rotate", self.ana), ("auth.bearer_revoke", self.ana)],
        )
        self.assertEqual(
            sent[0]["values"],
            {"prefix": key[: len(settings.BEARER_KEY_PREFIX) + keys.VISIBLE_CHARS]},
        )


class BearerKeyInlineTest(TestCase):
    """The key shows on the user's page in the admin, and deleting it there
    revokes it."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="root@example.com", password="x"
        )
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.client.force_login(self.admin)
        self.change_url = reverse("admin:authd_user_change", args=[self.ana.pk])

    def test_the_inline_shows_only_the_start(self):
        _, key = keys.rotate(None, self.ana)
        response = self.client.get(self.change_url)
        self.assertContains(
            response, key[: len(settings.BEARER_KEY_PREFIX) + keys.VISIBLE_CHARS]
        )
        self.assertNotContains(response, key)

    def test_deleting_in_the_inline_revokes(self):
        row, _ = keys.rotate(None, self.ana)
        sent = []
        action_performed.connect(lambda **kw: sent.append(kw), weak=False)
        try:
            response = self.client.post(
                self.change_url,
                {
                    "email": self.ana.email,
                    "is_active": "on",
                    "sessions-TOTAL_FORMS": "0",
                    "sessions-INITIAL_FORMS": "0",
                    "bearer_key-TOTAL_FORMS": "1",
                    "bearer_key-INITIAL_FORMS": "1",
                    "bearer_key-0-id": row.pk,
                    "bearer_key-0-user": self.ana.pk,
                    "bearer_key-0-DELETE": "on",
                    "crypto-keyset-owner_type-owner_id-TOTAL_FORMS": "0",
                    "crypto-keyset-owner_type-owner_id-INITIAL_FORMS": "0",
                },
            )
        finally:
            action_performed.receivers.pop()
        self.assertEqual(response.status_code, 302)
        self.assertFalse(BearerKey.objects.exists())
        self.assertEqual([s["name"] for s in sent], ["auth.bearer_revoke"])
        self.assertEqual(sent[0]["target"], self.ana)
