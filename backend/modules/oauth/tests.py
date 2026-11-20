import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.test import Client, TestCase, override_settings

from modules.oauth.management.commands.oauth_mock import Handler, id_token
from modules.oauth.models import UserIdentity
from modules.oauth.providers import google, id_token_claims, microsoft

User = get_user_model()
# What the Next proxy adds to every request it forwards. Django then checks
# that host against ALLOWED_HOSTS.
PROXY = {"X-Forwarded-Host": "localhost:3000"}
HOSTS = ["localhost", "testserver"]
PROVIDERS = "modules.oauth.providers"


@override_settings(
    ALLOWED_HOSTS=HOSTS,
    AUTH_GOOGLE_CLIENT_ID="client-id",
    AUTH_MICROSOFT_CLIENT_ID="",
    AUTH_MOCK_URL="",
)
class OAuthLoginTest(TestCase):
    """The flow, with the provider's token endpoint patched out."""

    def setUp(self):
        self.client = Client(headers=PROXY)
        self.user = User.objects.create_user(
            email="ana@example.com", password="s3cret-pass"
        )

    def start(self, next=None, provider="google"):
        query = {"next": next} if next else {}
        response = self.client.get(f"/api/auth/{provider}/start", query)
        self.assertEqual(response.status_code, 302)
        return parse_qs(urlsplit(response.url).query)

    def callback(self, email, email_verified=True, state=None, sub="sub-1"):
        params = self.start("/api/docs")
        token = {
            "id_token": id_token(email, "client-id", "https://accounts.google.com")
        }
        claims = {"sub": sub, "email": email, "email_verified": email_verified}
        with (
            patch(
                "modules.oauth.providers.OAuth2Session.fetch_token", return_value=token
            ),
            patch(f"{PROVIDERS}.id_token_claims", return_value=claims),
        ):
            return self.client.get(
                "/api/auth/google/callback",
                {"code": "abc", "state": state or params["state"][0]},
            )

    def test_start_redirects_with_pkce(self):
        params = self.start()
        self.assertEqual(params["client_id"], ["client-id"])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        self.assertEqual(params["nonce"], [self.client.session["oauth"]["nonce"]])
        self.assertEqual(
            params["redirect_uri"], ["http://localhost:3000/api/auth/google/callback"]
        )

    def test_callback_on_https_behind_a_load_balancer(self):
        self.client = Client(headers={**PROXY, "X-Forwarded-Proto": "https"})
        params = self.start()
        self.assertEqual(
            params["redirect_uri"], ["https://localhost:3000/api/auth/google/callback"]
        )

    def test_login(self):
        response = self.callback("ANA@example.com")
        self.assertRedirects(response, "/api/docs", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/api/users/me").status_code, 200)

    def test_first_login_links_the_identity(self):
        self.callback("ana@example.com")
        identity = UserIdentity.objects.get(provider="google", uid="sub-1")
        self.assertEqual(identity.user, self.user)
        self.assertEqual(identity.metadata["email"], "ana@example.com")

    def test_later_logins_go_by_the_identity(self):
        self.callback("ana@example.com")
        self.client.logout()
        # The email changed at Google: still Ana, and the identity says so.
        response = self.callback("ana.lima@example.com")
        self.assertRedirects(response, "/api/docs", fetch_redirect_response=False)
        identity = UserIdentity.objects.get(provider="google", uid="sub-1")
        self.assertEqual(identity.metadata["email"], "ana.lima@example.com")
        self.assertEqual(UserIdentity.objects.count(), 1)

    def test_identity_goes_with_the_user(self):
        self.callback("ana@example.com")
        self.user.delete()
        self.assertFalse(UserIdentity.objects.exists())

    def test_state_must_match(self):
        response = self.callback("ana@example.com", state="forged")
        self.assertEqual(response.url, "/login?error=oauth_invalid_state")
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)

    def test_callback_without_start(self):
        response = self.client.get(
            "/api/auth/google/callback", {"code": "abc", "state": "x"}
        )
        self.assertEqual(response.url, "/login?error=oauth_invalid_state")

    @override_settings(AUTH_MICROSOFT_CLIENT_ID="ms-client-id")
    def test_callback_must_match_the_provider_that_started(self):
        params = self.start(provider="microsoft")
        response = self.client.get(
            "/api/auth/google/callback", {"code": "abc", "state": params["state"][0]}
        )
        self.assertEqual(response.url, "/login?error=oauth_invalid_state")

    def test_unverified_email(self):
        response = self.callback("ana@example.com", email_verified=False)
        self.assertEqual(response.url, "/login?error=oauth_unverified_email")

    @override_settings(AUTH_MICROSOFT_CLIENT_ID="ms-client-id")
    def test_microsoft_email_without_xms_edov_is_unverified(self):
        claims = {"sub": "sub-1", "email": "ana@example.com", "tid": "other-tenant"}
        for extra in [{}, {"xms_edov": False}]:
            params = self.start(provider="microsoft")
            with (
                patch(f"{PROVIDERS}.OAuth2Session.fetch_token", return_value={}),
                patch(f"{PROVIDERS}.id_token_claims", return_value=claims | extra),
            ):
                response = self.client.get(
                    "/api/auth/microsoft/callback",
                    {"code": "abc", "state": params["state"][0]},
                )
            self.assertEqual(response.url, "/login?error=oauth_unverified_email")
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)
        self.assertFalse(UserIdentity.objects.exists())

    def test_unknown_email_is_not_signed_up(self):
        response = self.callback("bob@example.com")
        self.assertEqual(response.url, "/login?error=oauth_no_account")
        self.assertFalse(User.objects.filter(email="bob@example.com").exists())

    def test_inactive_user(self):
        self.user.is_active = False
        self.user.save()
        response = self.callback("ana@example.com")
        self.assertEqual(response.url, "/login?error=oauth_no_account")

    def test_cancelled_on_the_provider(self):
        self.start()
        response = self.client.get(
            "/api/auth/google/callback", {"error": "access_denied"}
        )
        self.assertEqual(response.url, "/login?error=oauth_cancelled")

    def test_failures_send_user_login_failed(self):
        # The contract with whoever listens (log or nobody).
        received = []

        def receiver(sender, credentials, request, **kwargs):
            received.append(credentials)

        user_login_failed.connect(receiver)
        self.addCleanup(user_login_failed.disconnect, receiver)
        self.callback("bob@example.com")
        self.assertEqual(
            received,
            [
                {
                    "provider": "google",
                    "reason": "no_account",
                    "email": "bob@example.com",
                }
            ],
        )

    def test_login_says_which_provider(self):
        # The contract with modules/audit, which logs it as the login's method
        # (see modules/signals/signals.py).
        received = []

        def receiver(sender, request, user, **kwargs):
            received.append(getattr(request, "auth_provider", None))

        user_logged_in.connect(receiver)
        self.addCleanup(user_logged_in.disconnect, receiver)
        self.callback("ana@example.com")
        self.assertEqual(received, ["google"])

    def test_next_must_be_a_local_path(self):
        for next in ["//evil.com", "https://evil.com", "/\\evil.com"]:
            with self.subTest(next=next):
                self.start(next)
                self.assertEqual(self.client.session["oauth"]["next"], "/")

    def test_unconfigured_provider(self):
        for provider in ["microsoft", "mock"]:
            with self.subTest(provider=provider):
                response = self.client.get(f"/api/auth/{provider}/start")
                self.assertEqual(response.url, "/login?error=oauth_not_configured")

    def test_unknown_provider(self):
        response = self.client.get("/api/auth/nope/start")
        self.assertEqual(response.status_code, 422)

    def test_providers_on_the_login_page(self):
        # Only Google is configured here.
        response = self.client.get("/api/auth/providers")
        self.assertEqual(
            response.json()["providers"],
            [{"name": "google", "label": "Google", "url": "/api/auth/google/start"}],
        )

    @override_settings(DEBUG=False, AUTH_MOCK_URL="http://localhost:8001")
    def test_mock_needs_debug(self):
        names = [
            p["name"]
            for p in self.client.get("/api/auth/providers").json()["providers"]
        ]
        self.assertNotIn("mock", names)


@override_settings(AUTH_GOOGLE_CLIENT_ID="client-id")
class IdTokenClaimsTest(TestCase):
    def token(
        self, client_id="client-id", issuer="https://accounts.google.com", nonce="n1"
    ):
        return {"id_token": id_token("ana@example.com", client_id, issuer, nonce)}

    def claims(self, nonce="n1", **kwargs):
        return id_token_claims(self.token(**kwargs), google.provider(), nonce)

    def test_valid(self):
        self.assertEqual(self.claims()["email"], "ana@example.com")

    def test_another_issuer(self):
        with self.assertRaisesMessage(ValueError, "another issuer"):
            self.claims(issuer="https://evil.com")

    def test_another_client(self):
        with self.assertRaisesMessage(ValueError, "another client"):
            self.claims(client_id="someone-else")

    def test_another_login(self):
        with self.assertRaisesMessage(ValueError, "another login"):
            self.claims(nonce="n2")

    def test_no_nonce(self):
        token = self.token(nonce="")
        with self.assertRaisesMessage(ValueError, "another login"):
            id_token_claims(token, google.provider(), "n1")

    def test_expired(self):
        token = self.token()
        with (
            patch("modules.oauth.providers.time.time", return_value=4e9),
            self.assertRaisesMessage(ValueError, "expired"),
        ):
            id_token_claims(token, google.provider(), "n1")


class MicrosoftIssuerTest(TestCase):
    def test_issuer_of_the_tenant(self):
        tid = "9188040d-6c67-4c5b-b112-36a304b66dad"
        iss = f"https://login.microsoftonline.com/{tid}/v2.0"
        self.assertTrue(microsoft.valid_issuer({"tid": tid, "iss": iss}))
        self.assertFalse(microsoft.valid_issuer({"tid": "other", "iss": iss}))
        self.assertFalse(microsoft.valid_issuer({"iss": iss}))


class MicrosoftEmailTest(TestCase):
    email = "ana@example.com"
    tenant = "00000000-0000-0000-0000-000000000001"

    def test_needs_the_domain_owner_to_have_verified_it(self):
        claims = {"email": self.email, "tid": self.tenant}
        self.assertFalse(microsoft.email_verified(claims))
        self.assertFalse(microsoft.email_verified({**claims, "xms_edov": False}))
        self.assertTrue(microsoft.email_verified({**claims, "xms_edov": True}))
        self.assertFalse(
            microsoft.email_verified({"tid": self.tenant, "xms_edov": True})
        )

    def test_personal_accounts(self):
        claims = {"email": self.email, "tid": microsoft.PERSONAL_TENANT}
        self.assertTrue(microsoft.email_verified(claims))
        self.assertFalse(microsoft.email_verified({"tid": microsoft.PERSONAL_TENANT}))


@override_settings(ALLOWED_HOSTS=HOSTS)
class MockProviderTest(TestCase):
    """The whole flow against the real `oauth_mock` server, nothing patched."""

    def setUp(self):
        self.client = Client(headers=PROXY)
        User.objects.create_user(email="ana@example.com", password="s3cret-pass")
        self.server = ThreadingHTTPServer(("localhost", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        url = f"http://localhost:{self.server.server_port}"
        settings = override_settings(DEBUG=True, AUTH_MOCK_URL=url)
        settings.enable()
        self.addCleanup(settings.disable)

    def log_in_as(self, email):
        authorize = self.client.get("/api/auth/mock/start").url
        form = {k: v[0] for k, v in parse_qs(urlsplit(authorize).query).items()}
        # What the mock's login page posts when the user clicks Continue.
        response = requests.post(
            authorize, {**form, "email": email}, allow_redirects=False
        )
        callback = urlsplit(response.headers["Location"])
        return self.client.get(callback.path, parse_qs(callback.query))

    def test_login(self):
        response = self.log_in_as("ana@example.com")
        self.assertEqual(response.url, "/")
        self.assertEqual(self.client.get("/api/users/me").status_code, 200)

    def test_unknown_email(self):
        response = self.log_in_as("bob@example.com")
        self.assertEqual(response.url, "/login?error=oauth_no_account")

    def test_wrong_code_verifier_is_rejected(self):
        authorize = self.client.get("/api/auth/mock/start").url
        form = {k: v[0] for k, v in parse_qs(urlsplit(authorize).query).items()}
        response = requests.post(
            authorize.split("?")[0], {**form, "email": "a@b.c"}, allow_redirects=False
        )
        code = parse_qs(urlsplit(response.headers["Location"]).query)["code"][0]
        token = requests.post(
            authorize.split("?")[0].replace("/authorize", "/token"),
            {"code": code, "code_verifier": "wrong"},
        )
        self.assertEqual(token.status_code, 400)
