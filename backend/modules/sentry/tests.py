from unittest.mock import patch

import sentry_sdk
import structlog
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import MiddlewareNotUsed
from django.test import Client, RequestFactory, SimpleTestCase, TestCase

from .api import SentryTestError
from .sentry import (
    SentryUserMiddleware,
    _add_request_id,
    init_sentry,
    user_processor,
)

User = get_user_model()


class RequestIdTagTest(SimpleTestCase):
    def test_tags_the_event_with_the_request_id(self):
        with structlog.contextvars.bound_contextvars(request_id="abc123"):
            event = _add_request_id({"tags": {"x": "1"}}, {})
        self.assertEqual(event["tags"], {"x": "1", "request_id": "abc123"})

    def test_no_request_id_no_tag(self):
        self.assertNotIn("tags", _add_request_id({}, {}))


class UserTest(SimpleTestCase):
    def request(self, user):
        request = RequestFactory().get("/")
        request.user = user
        return request

    def test_only_the_id_of_the_user(self):
        user = User(username="0190c1d2-0000-7000-8000-000000000001", email="a@b.co")
        event = user_processor(self.request(user))({"user": {"ip": "1.2.3.4"}}, {})
        self.assertEqual(event["user"], {"id": user.username})

    def test_anonymous_no_user(self):
        event = user_processor(self.request(AnonymousUser()))({}, {})
        self.assertNotIn("user", event)

    def test_reads_the_user_when_the_event_is_sent(self):
        # The Bearer auth only sets request.user in the view.
        request = self.request(AnonymousUser())
        processor = user_processor(request)
        request.user = User(username="0190c1d2-0000-7000-8000-000000000002")
        self.assertEqual(processor({}, {})["user"], {"id": request.user.username})

    def test_middleware_off_without_sentry(self):
        with self.assertRaises(MiddlewareNotUsed):
            SentryUserMiddleware(lambda request: None)

    @patch("modules.sentry.sentry.sentry_sdk.is_initialized", return_value=True)
    @patch("modules.sentry.sentry.sentry_sdk.get_isolation_scope")
    def test_middleware_adds_the_processor(self, get_scope, _):
        SentryUserMiddleware(lambda request: "response")(self.request(AnonymousUser()))
        get_scope.return_value.add_event_processor.assert_called_once()


@patch("modules.sentry.sentry.sentry_sdk.init")
class InitTest(SimpleTestCase):
    def test_no_dsn_no_sentry(self, init):
        init_sentry("", "production", 1.0)
        init.assert_not_called()

    def test_no_personal_data_leaves(self, init):
        # LGPD: no email, IP, cookie or request body goes to Sentry.
        init_sentry("https://key@sentry.example.com/1", "production", 0.5)
        options = init.call_args.kwargs
        self.assertIs(options["send_default_pii"], False)
        self.assertIs(options["before_send"], _add_request_id)
        self.assertIs(options["before_send_transaction"], _add_request_id)
        self.assertEqual(options["environment"], "production")
        self.assertEqual(options["traces_sample_rate"], 0.5)


class LocalVariablesTest(SimpleTestCase):
    """A real event, through a fake transport: what would reach Sentry."""

    def test_no_local_variables_leave(self):
        events = []
        with patch("modules.sentry.sentry.sentry_sdk.init") as init:
            init_sentry("https://key@sentry.example.com/1", "test", 0.0)
        client = sentry_sdk.Client(**init.call_args.kwargs, transport=events.append)
        token = "secret-token"  # noqa: F841 - the local that must not leave
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            with sentry_sdk.new_scope() as scope:
                scope.set_client(client)
                sentry_sdk.capture_exception()
        client.flush()
        frames = events[0]["exception"]["values"][0]["stacktrace"]["frames"]
        self.assertTrue(frames)
        self.assertFalse(any("vars" in frame for frame in frames))
        client.close()


class DebugErrorTest(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True, raise_request_exception=True)

    def post(self):
        csrf = (
            self.client.get("/api/auth/csrf").cookies[settings.CSRF_COOKIE_NAME].value
        )
        return self.client.post("/api/debug/error", HTTP_X_CSRFTOKEN=csrf)

    def test_superuser_gets_the_error(self):
        admin = User.objects.create_superuser(email="root@example.com", password="x")
        self.client.force_login(admin)
        with self.assertRaises(SentryTestError):
            self.post()

    def test_others_get_403(self):
        user = User.objects.create_user(email="ana@example.com", password="x")
        self.client.force_login(user)
        self.assertEqual(self.post().status_code, 403)

    def test_anonymous_gets_401(self):
        self.assertEqual(self.post().status_code, 401)

    def test_needs_csrf(self):
        admin = User.objects.create_superuser(email="root@example.com", password="x")
        self.client.force_login(admin)
        self.assertEqual(self.client.post("/api/debug/error").status_code, 403)
