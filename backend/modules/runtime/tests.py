from unittest import skipUnless

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


# Skipped when the folder stays but the app is out of INSTALLED_APPS.
@skipUnless(apps.is_installed("modules.runtime"), "runtime is off")
class RuntimeTest(TestCase):
    def setUp(self):
        self.url = reverse("admin:runtime")

    def test_superusers_see_it(self):
        self.client.force_login(User.objects.create_superuser(email="root@example.com"))
        response = self.client.get(self.url)
        self.assertContains(response, "DEBUG")
        self.assertContains(response, "authd")  # A migration.
        # In the sidebar too.
        self.assertContains(response, f'href="{self.url}"')

    @override_settings(SECRET_KEY="s" * 50, AUTH_GOOGLE_CLIENT_SECRET="very-secret")
    def test_secrets_are_masked(self):
        self.client.force_login(User.objects.create_superuser(email="root@example.com"))
        response = self.client.get(self.url)
        self.assertContains(response, "(set, 50 chars)")
        self.assertNotContains(response, "very-secret")

    def test_staff_who_are_not_superusers_dont(self):
        staff = User.objects.create_user(email="staff@example.com", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        response = self.client.get(reverse("admin:index"))
        self.assertNotContains(response, "Runtime")
