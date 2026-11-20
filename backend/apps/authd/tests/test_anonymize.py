from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from post_office.models import Email

from modules.audit.models import AuditLog
from modules.bearer import keys
from modules.bearer.models import BearerKey
from modules.crypto import crypto
from modules.idempotency.models import IdempotencyKey
from modules.oauth.models import UserIdentity
from modules.session.models import Session
from modules.session.tests import log_in
from modules.signals.signals import action_performed

User = get_user_model()
EMAIL = "ana@example.com"


class AnonymizeTest(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user(email=EMAIL, password="x")

    def test_blocks_and_keeps_the_rest(self):
        self.ana.anonymize()
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.is_active)
        # Erasing the data is each project's to write.
        self.assertEqual(self.ana.email, EMAIL)

    def test_cannot_log_in_and_sessions_are_gone(self):
        phone = log_in(self.ana)
        self.ana.anonymize()
        self.assertEqual(phone.get("/api/users/me").status_code, 401)
        self.assertFalse(Session.objects.filter(user=self.ana).exists())
        response = Client().post(
            "/api/auth/login",
            {"email": EMAIL, "password": "x"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_erases_what_the_modules_keep(self):
        bia = User.objects.create_user(email="bia@example.com", password="x")
        for user in (self.ana, bia):
            UserIdentity.objects.create(user=user, provider="google", uid=user.email)
            IdempotencyKey.objects.create(user=user, key="k", fingerprint="x")
            keys.rotate(None, user)
        data = crypto.encrypt(self.ana, b"secret")
        Email.objects.create(from_email="app@example.com", to=[EMAIL])
        theirs = Email.objects.create(from_email="app@example.com", to=[bia.email])
        self.ana.anonymize()
        self.assertQuerySetEqual(
            UserIdentity.objects.values_list("user", flat=True), [bia.pk]
        )
        self.assertQuerySetEqual(
            IdempotencyKey.objects.values_list("user", flat=True), [bia.pk]
        )
        self.assertQuerySetEqual(
            BearerKey.objects.values_list("user", flat=True), [bia.pk]
        )
        self.assertQuerySetEqual(Email.objects.all(), [theirs])
        with self.assertRaises(crypto.NoKeyset):
            crypto.decrypt(self.ana, data)

    def test_masks_what_it_logged(self):
        # oauth's deleted identity is logged too, then masked.
        UserIdentity.objects.create(
            user=self.ana, provider="google", uid="1", metadata={"email": "a@b.c"}
        )
        self.ana.anonymize()
        deleted = AuditLog.objects.get(action=AuditLog.Action.DELETE)
        self.assertEqual(deleted.old_values["metadata"], "***")

    def test_sends_the_action(self):
        sent = []
        action_performed.connect(lambda **kw: sent.append(kw), weak=False)
        request = RequestFactory().post("/")
        try:
            self.ana.anonymize(request)
        finally:
            action_performed.receivers.pop()
        self.assertEqual(
            [(a["name"], a["target"], a["request"]) for a in sent],
            [("user.anonymize", self.ana, request)],
        )


@override_settings(ALLOWED_HOSTS=["testserver"])
class AnonymizeAdminTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com", password="x"
        )
        self.ana = User.objects.create_user(email=EMAIL, password="x")
        self.client.force_login(self.admin)
        self.list_url = reverse("admin:authd_user_changelist")
        self.change_url = reverse("admin:authd_user_change", args=[self.ana.pk])

    def post(self, user=None, **typed):
        user = user or self.ana
        url = reverse("admin:authd_user_change", args=[user.pk])
        data = {"CHANGE_FORM-action": "anonymize_user", "_selected_action": user.pk}
        if typed:
            data["confirm"] = "1"
        return self.client.post(url, {**data, **typed})

    def anonymized(self):
        self.ana.refresh_from_db()
        return not self.ana.is_active

    def test_asks_for_the_email_and_the_end_of_the_id(self):
        response = self.post()
        self.assertContains(response, "This is destructive and can't be undone.")
        self.assertContains(response, EMAIL)
        self.assertContains(response, self.ana.username)
        self.assertContains(response, 'name="id_end"')
        self.assertFalse(self.anonymized())

    def test_anonymizes_once_both_match(self):
        response = self.post(email=EMAIL.upper(), id_end=self.ana.username[-4:].upper())
        self.assertRedirects(response, self.change_url, fetch_redirect_response=False)
        self.assertTrue(self.anonymized())
        self.assertContains(self.client.get(self.list_url), f"Anonymized {EMAIL}.")

    def test_wrong_email_or_id_end_does_nothing(self):
        end = self.ana.username[-4:]
        for typed in (
            {"email": "bob@example.com", "id_end": end},
            {"email": EMAIL, "id_end": "0000" if end != "0000" else "1111"},
            {"email": EMAIL, "id_end": ""},
        ):
            with self.subTest(**typed):
                response = self.post(**typed)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "errorlist")
                self.assertFalse(self.anonymized())

    def test_not_from_the_list(self):
        response = self.client.post(
            self.list_url,
            {"action": "anonymize_user", "_selected_action": [self.ana.pk]},
        )
        self.assertNotContains(response, "id_end", status_code=302)
        self.assertFalse(self.anonymized())
        self.assertNotContains(self.client.get(self.list_url), 'value="anonymize_user"')

    def test_not_yourself(self):
        self.post(
            self.admin, email="admin@example.com", id_end=self.admin.username[-4:]
        )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_needs_the_delete_permission(self):
        staff = User.objects.create_user(
            email="staff@example.com", password="x", is_staff=True
        )
        staff.user_permissions.add(
            *apps.get_model("auth", "Permission").objects.filter(
                codename__in=["view_user", "change_user"]
            )
        )
        self.client.force_login(staff)
        self.post(email=EMAIL, id_end=self.ana.username[-4:])
        self.assertFalse(self.anonymized())
