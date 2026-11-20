import importlib

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import clear_url_caches, reverse

from config import urls

User = get_user_model()


# The admin moves with DJANGO_ADMIN_PATH, so its URLs come from reverse().
def admin_url(name="index", *args):
    return reverse(f"admin:{name}", args=args)


@override_settings(ALLOWED_HOSTS=["localhost", "testserver"])
class AdminLoginTest(TestCase):
    def test_direct_shows_the_password_form(self):
        response = self.client.get(admin_url("login"))
        self.assertContains(response, 'name="password"')

    @override_settings(AUTH_PASSWORD=False)
    def test_password_form_stays_without_password_login(self):
        User.objects.create_superuser("admin@example.com", "s3cret-pass")
        self.client.post(
            admin_url("login"),
            {"username": "admin@example.com", "password": "s3cret-pass"},
        )
        self.assertEqual(self.client.get(admin_url()).status_code, 200)

    def test_logged_in_staff_goes_to_the_admin(self):
        self.client.force_login(User.objects.create_superuser("a@b.c", "x"))
        self.assertRedirects(self.client.get(admin_url("login")), admin_url())


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    AUTH_LOGIN_THROTTLE_EMAIL="2/15min",
    AUTH_LOGIN_THROTTLE_IP="3/15min",
)
class AdminLoginThrottleTest(TestCase):
    """The admin's own form, opened directly on Django, has the API's limits."""

    def setUp(self):
        User.objects.create_superuser("admin@example.com", "s3cret-pass")

    def login(self, email="admin@example.com", password="nope", ip="203.0.113.1"):
        return self.client.post(
            admin_url("login"),
            {"username": email, "password": password},
            headers={"X-Forwarded-For": ip},
        )

    def logged_in(self):
        return self.client.get(admin_url()).status_code == 200

    def test_too_many_failures_for_an_email(self):
        self.login()
        self.login("ADMIN@example.com", ip="203.0.113.2")
        response = self.login(password="s3cret-pass", ip="203.0.113.3")
        self.assertContains(response, "Too many failed logins")
        self.assertFalse(self.logged_in())

    def test_too_many_failures_from_an_ip(self):
        for email in ("a@example.com", "b@example.com", "c@example.com"):
            self.login(email)
        self.assertContains(self.login(password="s3cret-pass"), "Too many failed")
        self.assertFalse(self.logged_in())
        self.login(password="s3cret-pass", ip="203.0.113.9")
        self.assertTrue(self.logged_in())

    def test_counts_with_the_api(self):
        self.client.post(
            "/api/auth/login",
            {"email": "admin@example.com", "password": "nope"},
            content_type="application/json",
        )
        self.login()
        self.assertContains(self.login(password="s3cret-pass"), "Too many failed")

    def test_good_login_clears_the_email_count(self):
        self.login()
        self.login(password="s3cret-pass")
        self.assertTrue(self.logged_in())
        self.client.logout()
        self.login()
        self.login(password="s3cret-pass")
        self.assertTrue(self.logged_in())


class AdminPathTest(TestCase):
    def reload_urls(self):
        importlib.reload(urls)
        clear_url_caches()

    @override_settings(DJANGO_ADMIN_PATH="backoffice")
    def test_admin_moves_to_admin_path(self):
        self.reload_urls()
        self.addCleanup(self.reload_urls)  # Runs after the override is undone.
        self.client.force_login(User.objects.create_superuser("a@b.c", "x"))
        self.assertEqual(self.client.get("/backoffice/").status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 404)
