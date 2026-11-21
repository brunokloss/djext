from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from modules.signals.signals import login_options_requested

User = get_user_model()


class AuthEndpointTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="ana@example.com", password="s3cret-pass"
        )
        # The default test client skips CSRF checks; the frontend can't.
        self.client = Client(enforce_csrf_checks=True)

    def csrf(self):
        response = self.client.get("/api/auth/csrf")
        self.assertEqual(response.status_code, 204)
        return self.client.cookies[settings.CSRF_COOKIE_NAME].value

    def post(self, path, data=None, token=None):
        headers = {"X-CSRFToken": token} if token else {}
        return self.client.post(
            f"/api/auth/{path}",
            data or {},
            content_type="application/json",
            headers=headers,
        )

    def test_login_and_logout(self):
        token = self.csrf()
        response = self.post(
            "login", {"email": "ANA@example.com", "password": "s3cret-pass"}, token
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.user.username)
        self.assertEqual(self.client.get("/api/users/me").status_code, 200)

        # Login rotated the token: the old one no longer works.
        new_token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertNotEqual(new_token, token)
        self.assertEqual(self.post("logout", token=new_token).status_code, 204)
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)

    def test_wrong_password(self):
        token = self.csrf()
        response = self.post(
            "login", {"email": "ana@example.com", "password": "nope"}, token
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid email or password"})

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        token = self.csrf()
        response = self.post(
            "login", {"email": "ana@example.com", "password": "s3cret-pass"}, token
        )
        self.assertEqual(response.status_code, 401)

    @override_settings(AUTH_PASSWORD=False)
    def test_password_login_disabled(self):
        token = self.csrf()
        response = self.post(
            "login", {"email": "ana@example.com", "password": "s3cret-pass"}, token
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Password login is disabled"})
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)

    def test_login_requires_csrf(self):
        self.csrf()
        response = self.post(
            "login", {"email": "ana@example.com", "password": "s3cret-pass"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)

    def test_logout_requires_csrf(self):
        self.client.force_login(self.user)
        self.csrf()
        self.assertEqual(self.post("logout").status_code, 403)
        self.assertEqual(self.client.get("/api/users/me").status_code, 200)

    def test_logout_when_logged_out(self):
        self.assertEqual(self.post("logout", token=self.csrf()).status_code, 204)


class LoginOptionsTest(TestCase):
    """/auth/providers: authd only knows the password; modules add the rest."""

    def setUp(self):
        # Without the modules' receivers (oauth's): a new list for each test.
        self.enterContext(patch.object(login_options_requested, "receivers", []))

    def options(self):
        return self.client.get("/api/auth/providers").json()

    def test_browsers_may_keep_it_five_minutes(self):
        response = self.client.get("/api/auth/providers")
        self.assertEqual(response["Cache-Control"], "public, max-age=300")

    def test_only_the_password_without_modules(self):
        self.assertEqual(
            self.options(),
            {
                "password": True,
                "providers": [],
                "signup": False,
                "password_reset": False,
            },
        )

    @override_settings(AUTH_PASSWORD=False)
    def test_password_off(self):
        self.assertFalse(self.options()["password"])

    def test_modules_add_options_in_order(self):
        sso = {"name": "sso", "label": "SSO", "url": "/api/auth/sso/start"}
        magic = {"name": "magic", "label": "Email link", "url": "/magic"}
        for option in (sso, magic):
            login_options_requested.connect(
                lambda sender, option=option, **kwargs: [option], weak=False
            )
        self.assertEqual(self.options()["providers"], [sso, magic])


@override_settings(
    AUTH_LOGIN_THROTTLE_EMAIL="2/15min", AUTH_LOGIN_THROTTLE_IP="3/15min"
)
class LoginThrottleTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="ana@example.com", password="s3cret-pass"
        )

    def login(self, email="ana@example.com", password="nope", ip="203.0.113.1"):
        return self.client.post(
            "/api/auth/login",
            {"email": email, "password": password},
            content_type="application/json",
            headers={"X-Forwarded-For": ip},
        )

    def test_too_many_failures_for_an_email(self):
        self.assertEqual(self.login().status_code, 401)
        # Any case, from any IP: the same email.
        self.assertEqual(
            self.login("ANA@example.com", ip="203.0.113.2").status_code, 401
        )
        response = self.login(password="s3cret-pass", ip="203.0.113.3")
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["Retry-After"]), 0)
        # Another email still gets in.
        User.objects.create_user(email="bia@example.com", password="s3cret-pass")
        response = self.login("bia@example.com", "s3cret-pass", ip="203.0.113.4")
        self.assertEqual(response.status_code, 200)

    def test_too_many_failures_from_an_ip(self):
        for email in ("a@example.com", "b@example.com", "c@example.com"):
            self.assertEqual(self.login(email).status_code, 401)
        response = self.login(password="s3cret-pass")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            self.login(password="s3cret-pass", ip="203.0.113.9").status_code, 200
        )

    def test_good_login_clears_the_email_count(self):
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(password="s3cret-pass").status_code, 200)
        self.client.logout()
        self.assertEqual(self.login().status_code, 401)
        # One failure since the good login, not two.
        self.assertEqual(self.login(password="s3cret-pass").status_code, 200)

    def test_good_logins_do_not_use_up_the_ip(self):
        User.objects.create_user(email="bia@example.com", password="s3cret-pass")
        for _ in range(4):
            self.assertEqual(self.login(password="s3cret-pass").status_code, 200)
            self.client.logout()
        self.assertEqual(self.login("bia@example.com").status_code, 401)

    def test_refused_try_is_not_a_failure(self):
        # The IP is full: a try for another email is refused and doesn't
        # count against that email.
        for email in ("a@example.com", "b@example.com", "c@example.com"):
            self.login(email)
        self.assertEqual(self.login().status_code, 429)
        self.assertEqual(self.login().status_code, 429)
        self.assertEqual(self.login(ip="203.0.113.9").status_code, 401)
        self.assertEqual(self.login(ip="203.0.113.9").status_code, 401)

    @override_settings(AUTH_LOGIN_THROTTLE_EMAIL="", AUTH_LOGIN_THROTTLE_IP="")
    def test_empty_rates_turn_it_off(self):
        for _ in range(5):
            self.assertEqual(self.login().status_code, 401)
