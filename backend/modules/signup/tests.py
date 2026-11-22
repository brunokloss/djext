from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.test import Client, TestCase, override_settings
from post_office.models import Email, EmailTemplate

from .checks import login_link_or_password
from .models import Signup
from .tokens import login_link_tokens, reset_tokens, verify_tokens

User = get_user_model()
PASSWORD = "a-long-new-password"
# What the Next proxy adds to every request it forwards: the links are built
# from it.
PROXY = {"HTTP_X_FORWARDED_HOST": "localhost:3000"}


def link(email: Email) -> dict:
    """The uid and token of the link in a queued email."""
    url = urlsplit(email.context["url"])
    query = parse_qs(url.query)
    return {"path": url.path, "uid": query["uid"][0], "token": query["token"][0]}


# Whatever the local .env says.
@override_settings(
    AUTH_PASSWORD=True,
    AUTH_SIGNUP=True,
    AUTH_PASSWORD_RESET=True,
    AUTH_MAGIC_LINK=False,
    ALLOWED_HOSTS=["localhost", "testserver"],
)
class SignupTestCase(TestCase):
    def post(self, path, **body):
        return self.client.post(
            f"/api/auth/{path}", body, content_type="application/json", **PROXY
        )

    def signup(self, email="new@example.com", password=PASSWORD):
        return self.post("signup", email=email, password=password, first_name="New")


class SignupTest(SignupTestCase):
    def test_creates_an_inactive_user_and_sends_the_link(self):
        self.assertEqual(self.signup(email=" New@Example.com ").status_code, 204)
        user = User.objects.get(email="new@example.com")
        self.assertFalse(user.is_active)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertIsNone(user.signup.verified_at)
        email = Email.objects.get()
        self.assertEqual(email.to, ["new@example.com"])
        self.assertEqual(email.template.name, "verify_email")
        self.assertEqual(email.context["name"], "New")
        self.assertIn("Hi New,", email.email_message().body)
        self.assertTrue(
            email.context["url"].startswith("http://localhost:3000/verify?")
        )
        self.assertEqual(link(email)["uid"], user.username)

    def test_the_plain_text_has_the_link_as_it_is(self):
        self.post(
            "signup", email="new@example.com", password=PASSWORD, first_name="D'Ávila"
        )
        email = Email.objects.get()
        body = email.email_message().body
        self.assertIn(email.context["url"], body)
        self.assertNotIn("&amp;", body)
        self.assertIn("Hi D'Ávila,", body)

    def test_an_existing_email_gets_the_same_answer_and_a_note(self):
        User.objects.create_user(email="ana@example.com", password="x")
        self.assertEqual(self.signup(email="ANA@example.com").status_code, 204)
        self.assertEqual(User.objects.count(), 1)
        email = Email.objects.get()
        self.assertEqual(email.template.name, "account_exists")
        self.assertEqual(email.context["login_url"], "http://localhost:3000/login")
        body = email.email_message().body
        self.assertIn("http://localhost:3000/forgot-password", body)

    def test_a_blocked_email_gets_nothing(self):
        User.objects.create_user(email="ana@example.com", password="x", is_active=False)
        self.assertEqual(self.signup(email="ana@example.com").status_code, 204)
        self.assertFalse(Email.objects.exists())

    def test_signing_up_again_while_waiting_takes_the_new_password(self):
        # Someone signed up with another person's email first: when that
        # person signs up, their password wins and the first link is dead.
        self.signup(password="someone-elses-password")
        first = link(Email.objects.get())
        self.assertEqual(self.signup().status_code, 204)
        self.assertEqual(User.objects.count(), 1)
        second = link(Email.objects.latest("id"))
        for found in (first, second):
            del found["path"]
        self.assertEqual(self.post("verify", **first).status_code, 400)
        self.assertEqual(self.post("verify", **second).status_code, 200)
        self.assertTrue(User.objects.get().check_password(PASSWORD))

    def test_a_bad_email_or_a_long_name_is_refused(self):
        for body in (
            {"email": "not-an-email"},
            {"email": "new@example.com", "first_name": "x" * 151},
        ):
            response = self.post("signup", password=PASSWORD, **body)
            self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.exists())
        self.assertFalse(Email.objects.exists())

    @override_settings(AUTH_MAIL_THROTTLE_EMAIL="1/h")
    def test_a_refused_sign_up_does_not_count_against_the_limit(self):
        for _ in range(3):
            self.assertEqual(self.signup(password="short").status_code, 400)
        self.assertEqual(self.signup().status_code, 204)

    def test_a_weak_password_is_refused(self):
        response = self.signup(password="new@example.com")
        self.assertEqual(response.status_code, 400)
        self.assertIn("too similar", response.json()["detail"])
        self.assertFalse(User.objects.exists())

    def test_the_user_cannot_log_in_before_verifying(self):
        self.signup()
        # The right password: told to confirm the email, with a new link
        # (the first may have expired).
        response = self.post("login", email="new@example.com", password=PASSWORD)
        self.assertEqual(response.status_code, 403)
        self.assertIn("We sent a new link", response.json()["detail"])
        self.assertEqual(Email.objects.count(), 2)
        # A wrong one: told nothing.
        response = self.post("login", email="new@example.com", password="wrong")
        self.assertEqual(response.status_code, 401)
        # Blocked by the team, not waiting: told nothing either.
        Signup.objects.all().delete()
        response = self.post("login", email="new@example.com", password=PASSWORD)
        self.assertEqual(response.status_code, 401)

    @override_settings(AUTH_LOGIN_THROTTLE_EMAIL="2/15min")
    def test_the_right_password_before_verifying_is_not_a_failed_login(self):
        self.signup()
        for _ in range(3):
            response = self.post("login", email="new@example.com", password=PASSWORD)
            self.assertEqual(response.status_code, 403)

    def test_two_hours_later_the_login_sends_a_link_that_works(self):
        self.signup()
        expired = link(Email.objects.get())
        del expired["path"]
        later = datetime.now() + timedelta(hours=2)
        with mock.patch.object(verify_tokens, "_now", return_value=later):
            self.assertEqual(self.post("verify", **expired).status_code, 400)
            response = self.post("login", email="new@example.com", password=PASSWORD)
            self.assertIn("We sent a new link", response.json()["detail"])
            fresh = link(Email.objects.latest("id"))
            del fresh["path"]
            self.assertEqual(self.post("verify", **fresh).status_code, 200)
        response = self.post("login", email="new@example.com", password=PASSWORD)
        self.assertEqual(response.status_code, 200)

    @override_settings(AUTH_MAIL_THROTTLE_EMAIL="1/h")
    def test_past_the_limit_the_login_sends_no_link(self):
        self.signup()
        response = self.post("login", email="new@example.com", password=PASSWORD)
        self.assertEqual(response.status_code, 403)
        self.assertIn("Open the link we sent you", response.json()["detail"])
        self.assertEqual(Email.objects.count(), 1)

    def test_the_email_templates_are_created_by_the_migration(self):
        names = set(EmailTemplate.objects.values_list("name", flat=True))
        self.assertLessEqual(
            {"verify_email", "password_reset", "account_exists"}, names
        )


class VerifyTest(SignupTestCase):
    def setUp(self):
        self.signup()
        self.user = User.objects.get(email="new@example.com")
        self.link = link(Email.objects.get())
        self.path = self.link.pop("path")

    def verify(self, **body):
        return self.post("verify", **{**self.link, **body})

    def test_activates_the_user_once(self):
        self.assertEqual(self.path, "/verify")
        response = self.verify()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"email": "new@example.com"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertIsNotNone(self.user.signup.verified_at)
        response = self.post("login", email="new@example.com", password=PASSWORD)
        self.assertEqual(response.status_code, 200)
        # Opened again: confirmed already, nothing changes.
        self.assertEqual(self.verify().status_code, 200)
        # The uid is the public id: without the token, not even the email.
        response = self.verify(token="1-abc")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("new@example.com", response.content.decode())

    def test_a_wrong_token_or_uid_is_refused(self):
        self.assertEqual(self.verify(token="1-abc").status_code, 400)
        self.assertEqual(self.verify(uid="not-a-user").status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_a_user_blocked_after_verifying_stays_blocked(self):
        self.verify()
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.verify().status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_a_user_the_team_activated_and_then_blocked_stays_blocked(self):
        # Activated by hand in the admin (a full save), never by the link.
        self.user.is_active = True
        self.user.save()
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.verify().status_code, 400)
        self.post("verify/resend", email="new@example.com")
        self.signup()
        self.assertEqual(Email.objects.count(), 1)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_an_inactive_user_who_never_signed_up_is_not_activated(self):
        Signup.objects.filter(user=self.user).delete()
        self.assertEqual(self.verify().status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_an_anonymized_user_waiting_for_verification_stays_blocked(self):
        self.user.anonymize()
        self.assertEqual(self.verify().status_code, 400)
        self.post("verify/resend", email="new@example.com")
        self.signup()
        self.assertFalse(Email.objects.exists())
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_resend_only_sends_to_who_is_waiting(self):
        self.assertEqual(
            self.post("verify/resend", email="new@example.com").status_code, 204
        )
        self.assertEqual(Email.objects.count(), 2)
        self.verify()
        for email in ("new@example.com", "nobody@example.com"):
            self.assertEqual(self.post("verify/resend", email=email).status_code, 204)
        self.assertEqual(Email.objects.count(), 2)


class PasswordResetTest(SignupTestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ana@example.com", password="old")

    def forgot(self, email="ana@example.com"):
        return self.post("password/forgot", email=email)

    def reset(self, password=PASSWORD, **body):
        return self.post("password/reset", password=password, **body)

    def test_sets_the_new_password_once(self):
        self.assertEqual(self.forgot().status_code, 204)
        email = Email.objects.get()
        self.assertEqual(email.template.name, "password_reset")
        # No name: no email in its place.
        self.assertTrue(email.email_message().body.startswith("Hi,"))
        found = link(email)
        self.assertEqual(found.pop("path"), "/reset-password")
        self.assertEqual(self.post("password/reset/check", **found).status_code, 204)
        response = self.reset(**found)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"email": "ana@example.com"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        # Used: the page says so before asking for a password.
        self.assertEqual(self.post("password/reset/check", **found).status_code, 410)
        self.assertEqual(
            self.reset(password="another-long-one", **found).status_code, 410
        )

    def test_ends_the_users_sessions(self):
        other = Client()
        other.force_login(self.user)
        self.assertEqual(other.get("/api/users/me").status_code, 200)
        self.forgot()
        found = link(Email.objects.get())
        del found["path"]
        self.reset(**found)
        # Deleted, not only refused: the session list doesn't show them.
        self.assertFalse(self.user.sessions.exists())
        self.assertEqual(other.get("/api/users/me").status_code, 401)

    @override_settings(AUTH_LOGIN_THROTTLE_EMAIL="2/15min", AUTH_LOGIN_THROTTLE_IP="")
    def test_lifts_the_login_lock(self):
        login = {"email": "ana@example.com", "password": "wrong"}
        for _ in range(2):
            self.post("login", **login)
        self.assertEqual(self.post("login", **login).status_code, 429)
        self.forgot()
        found = link(Email.objects.get())
        del found["path"]
        self.reset(**found)
        response = self.post("login", email="ana@example.com", password=PASSWORD)
        self.assertEqual(response.status_code, 200)

    def test_a_weak_password_is_refused(self):
        self.forgot()
        found = link(Email.objects.get())
        del found["path"]
        response = self.reset(password="ana@example.com", **found)
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old"))

    def test_only_active_users_with_a_password_get_the_link(self):
        User.objects.create_user(email="off@example.com", password="x", is_active=False)
        User.objects.create_user(email="sso@example.com")  # No usable password.
        for email in ("nobody@example.com", "off@example.com", "sso@example.com"):
            self.assertEqual(self.forgot(email).status_code, 204)
        self.assertFalse(Email.objects.exists())

    def test_a_user_waiting_for_verification_gets_that_link(self):
        self.signup()
        self.forgot("new@example.com")
        names = list(Email.objects.values_list("template__name", flat=True))
        self.assertEqual(names, ["verify_email", "verify_email"])
        self.assertFalse(User.objects.get(email="new@example.com").is_active)


class SettingsTest(SignupTestCase):
    def test_off_by_default(self):
        with self.settings(AUTH_SIGNUP=False, AUTH_PASSWORD_RESET=False):
            self.assertEqual(self.signup().status_code, 403)
            self.assertEqual(
                self.post("password/forgot", email="a@b.co").status_code, 403
            )
        self.assertFalse(User.objects.exists())

    def test_off_without_password_login(self):
        with self.settings(AUTH_PASSWORD=False):
            self.assertEqual(self.signup().status_code, 403)

    def test_login_options_say_what_is_on(self):
        options = self.client.get("/api/auth/providers").json()
        self.assertTrue(options["signup"])
        self.assertTrue(options["password_reset"])
        with self.settings(AUTH_SIGNUP=False, AUTH_PASSWORD_RESET=False):
            options = self.client.get("/api/auth/providers").json()
        self.assertFalse(options["signup"])
        self.assertFalse(options["password_reset"])

    def test_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            "/api/auth/signup",
            {"email": "new@example.com", "password": PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(AUTH_MAIL_THROTTLE_EMAIL="2/h", AUTH_MAIL_THROTTLE_IP="")
    def test_limits_the_emails_per_address(self):
        for _ in range(2):
            self.assertEqual(
                self.post("password/forgot", email="a@b.co").status_code, 204
            )
        response = self.post("password/forgot", email="A@b.co")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertIn("Try again in 60 minutes", response.json()["detail"])
        self.assertEqual(self.post("password/forgot", email="c@b.co").status_code, 204)

    @override_settings(AUTH_MAIL_THROTTLE_EMAIL="2/h", AUTH_MAIL_THROTTLE_IP="")
    def test_confirming_does_not_use_up_the_reset(self):
        for _ in range(2):
            self.assertEqual(
                self.post("verify/resend", email="a@b.co").status_code, 204
            )
        self.assertEqual(self.post("verify/resend", email="a@b.co").status_code, 429)
        self.assertEqual(self.post("password/forgot", email="a@b.co").status_code, 204)

    @override_settings(AUTH_MAIL_THROTTLE_EMAIL="1/h", AUTH_MAIL_THROTTLE_IP="1/h")
    def test_a_try_the_ip_refuses_does_not_count_for_the_email(self):
        self.post("password/forgot", email="a@b.co")
        self.assertEqual(self.post("password/forgot", email="c@b.co").status_code, 429)
        with self.settings(AUTH_MAIL_THROTTLE_IP=""):
            response = self.post("password/forgot", email="c@b.co")
        self.assertEqual(response.status_code, 204)

    @override_settings(AUTH_MAIL_THROTTLE_EMAIL="0/h")
    def test_a_rate_of_zero_refuses_every_try(self):
        response = self.post("password/forgot", email="a@b.co")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "3600")

    @override_settings(AUTH_MAIL_THROTTLE_EMAIL="", AUTH_MAIL_THROTTLE_IP="2/h")
    def test_limits_the_emails_per_ip(self):
        for email in ("a@b.co", "c@b.co"):
            self.assertEqual(self.post("password/forgot", email=email).status_code, 204)
        self.assertEqual(self.post("password/forgot", email="d@b.co").status_code, 429)


# In place of the password, as checks.py asks.
@override_settings(AUTH_MAGIC_LINK=True, AUTH_PASSWORD=False)
class LoginLinkTest(SignupTestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="ana@example.com", password="old", first_name="Ana"
        )

    def ask(self, email="ana@example.com", **body):
        return self.post("login-link", email=email, **body)

    def use(self, found):
        return self.post("login-link/login", uid=found["uid"], token=found["token"])

    def test_sends_a_link_that_logs_in_once(self):
        self.assertEqual(self.ask(" Ana@Example.com ").status_code, 204)
        email = Email.objects.get()
        self.assertEqual(email.template.name, "login_link")
        self.assertEqual(email.context["name"], "Ana")
        found = link(email)
        self.assertEqual(found["path"], "/login-link")
        self.assertTrue(
            email.context["url"].startswith("http://localhost:3000/login-link?")
        )
        methods = []

        def on_login(request, **kwargs):
            methods.append(request.auth_provider)

        user_logged_in.connect(on_login)
        self.addCleanup(user_logged_in.disconnect, on_login)
        self.assertEqual(self.use(found).status_code, 204)
        self.assertEqual(methods, ["login_link"])
        me = self.client.get("/api/users/me").json()
        self.assertEqual(me["email"], "ana@example.com")
        # Logging in changed the last login: the link is used.
        self.assertEqual(self.use(found).status_code, 410)

    def test_works_for_a_user_without_a_password(self):
        User.objects.create_user(email="sso@example.com")
        self.assertEqual(self.ask("sso@example.com").status_code, 204)
        self.assertEqual(self.use(link(Email.objects.get())).status_code, 204)

    def test_any_other_login_kills_the_link(self):
        self.ask()
        found = link(Email.objects.get())
        # A provider's login, say: anything that calls login().
        self.client.force_login(self.user)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.use(found).status_code, 410)

    def test_a_new_password_kills_the_link(self):
        self.ask()
        found = link(Email.objects.get())
        self.user.set_password("new-one")
        self.user.save()
        self.assertEqual(self.use(found).status_code, 410)

    def test_expires(self):
        self.ask()
        found = link(Email.objects.get())
        later = datetime.now() + timedelta(hours=2)
        with mock.patch.object(login_link_tokens, "_now", return_value=later):
            self.assertEqual(self.use(found).status_code, 410)

    def test_a_user_blocked_after_the_email_cannot_use_it(self):
        self.ask()
        found = link(Email.objects.get())
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.use(found).status_code, 410)
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)

    def test_a_wrong_link_or_another_kind_of_token_is_refused(self):
        uid = self.user.username
        for token in ("x", reset_tokens.make_token(self.user)):
            self.assertEqual(self.use({"uid": uid, "token": token}).status_code, 410)
        self.assertEqual(self.use({"uid": "nope", "token": "x"}).status_code, 410)
        # Nor does a login link reset a password.
        self.ask()
        token = link(Email.objects.get())["token"]
        self.assertFalse(reset_tokens.check_token(self.user, token))

    def test_a_dead_link_is_a_failed_login(self):
        failures = []

        def on_failure(credentials, **kwargs):
            failures.append(credentials)

        user_login_failed.connect(on_failure)
        self.addCleanup(user_login_failed.disconnect, on_failure)
        self.use({"uid": self.user.username, "token": "x"})
        self.assertEqual(failures, [{"provider": "login_link", "reason": "dead_link"}])

    def test_the_same_answer_for_any_email(self):
        User.objects.create_user(email="off@example.com", is_active=False)
        for email in ("nobody@example.com", "off@example.com"):
            self.assertEqual(self.ask(email).status_code, 204)
        self.assertFalse(Email.objects.exists())

    def test_a_user_waiting_for_verification_gets_that_link(self):
        # Signed up while the password was on.
        with self.settings(AUTH_PASSWORD=True):
            self.signup()
        self.ask("new@example.com")
        names = list(Email.objects.values_list("template__name", flat=True))
        self.assertEqual(names, ["verify_email", "verify_email"])

    @override_settings(AUTH_MAIL_THROTTLE_EMAIL="")
    def test_carries_next_when_it_is_a_path_here(self):
        self.ask(next="/notes?page=2")
        url = urlsplit(Email.objects.get().context["url"])
        self.assertEqual(parse_qs(url.query)["next"], ["/notes?page=2"])
        for next in ("https://evil.example", "//evil.example", "notes"):
            Email.objects.all().delete()
            self.ask(next=next)
            url = urlsplit(Email.objects.get().context["url"])
            self.assertNotIn("next", parse_qs(url.query))

    @override_settings(AUTH_MAIL_THROTTLE_EMAIL="1/h", AUTH_MAIL_THROTTLE_IP="")
    def test_has_its_own_email_limit(self):
        self.assertEqual(self.ask().status_code, 204)
        self.assertEqual(self.ask().status_code, 429)
        with self.settings(AUTH_PASSWORD=True):
            reset = self.post("password/forgot", email="ana@example.com")
        self.assertEqual(reset.status_code, 204)

    def test_off_by_default(self):
        self.ask()
        found = link(Email.objects.get())
        with self.settings(AUTH_MAGIC_LINK=False):
            self.assertEqual(self.ask().status_code, 403)
            self.assertEqual(self.use(found).status_code, 403)
            self.assertFalse(
                self.client.get("/api/auth/providers").json()["magic_link"]
            )
        self.assertTrue(self.client.get("/api/auth/providers").json()["magic_link"])

    def test_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        for path in ("login-link", "login-link/login"):
            response = client.post(
                f"/api/auth/{path}",
                {"email": "ana@example.com", "uid": "x", "token": "x"},
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 403)

    def test_the_email_template_is_created_by_the_migration(self):
        self.assertTrue(EmailTemplate.objects.filter(name="login_link").exists())

    def test_the_password_and_the_link_are_one_or_the_other(self):
        self.assertEqual(login_link_or_password(None), [])
        with self.settings(AUTH_PASSWORD=True):
            errors = login_link_or_password(None)
        self.assertEqual([e.id for e in errors], ["signup.E001"])
        with self.settings(AUTH_PASSWORD=True, AUTH_MAGIC_LINK=False):
            self.assertEqual(login_link_or_password(None), [])
