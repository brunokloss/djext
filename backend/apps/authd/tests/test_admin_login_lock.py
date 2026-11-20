from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.authd.api.auth import email_login_limit
from modules.signals.signals import action_performed
from modules.throttle.throttles import hashed

User = get_user_model()


@override_settings(AUTH_LOGIN_THROTTLE_EMAIL="2/15min", ALLOWED_HOSTS=["testserver"])
class LoginLockAdminTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com", password="x"
        )
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.client.force_login(self.admin)
        self.change_url = reverse("admin:authd_user_change", args=[self.ana.pk])
        self.unlock_url = reverse("admin:authd_user_unlock_login", args=[self.ana.pk])

    def fail(self, times):
        limit = email_login_limit()
        for _ in range(times):
            limit.attempt(hashed(self.ana.email))

    def test_shows_failures_when_not_locked(self):
        self.fail(1)
        page = self.client.get(self.change_url).content.decode()
        self.assertIn("Not locked by email (1 failed login in the last 15 min).", page)
        self.assertIn("A lock by IP clears by itself within 15 min.", page)
        self.assertNotIn(self.unlock_url, page)

    def test_locked_user_shows_unlock_button(self):
        self.fail(2)
        page = self.client.get(self.change_url).content.decode()
        self.assertIn(
            "Locked for 15 more min (2 failed logins in the last 15 min)", page
        )
        self.assertIn(f'formaction="{self.unlock_url}"', page)

    def test_unlock_lifts_the_lock_and_sends_the_action(self):
        self.fail(2)
        sent = []
        action_performed.connect(lambda **kw: sent.append(kw), weak=False)
        try:
            response = self.client.post(self.unlock_url)
        finally:
            action_performed.receivers.pop()
        self.assertRedirects(response, self.change_url)
        self.assertEqual(email_login_limit().status(hashed(self.ana.email)), (0, None))
        self.assertEqual(sent[0]["name"], "auth.unlock_login")
        self.assertEqual(sent[0]["target"], self.ana)

    def test_unlock_is_post_only(self):
        self.assertEqual(self.client.get(self.unlock_url).status_code, 405)

    def test_staff_without_change_permission_cannot_unlock(self):
        self.fail(2)
        staff = User.objects.create_user(
            email="staff@example.com", password="x", is_staff=True
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.post(self.unlock_url).status_code, 403)
        self.assertEqual(email_login_limit().status(hashed(self.ana.email))[0], 2)
