import hashlib

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from .throttles import (
    AnonThrottle,
    FailureLimit,
    UserThrottle,
    hashed,
    throttles,
)

User = get_user_model()


class ThrottleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ana@example.com", password="x")

    def request(self, user=None, ip="203.0.113.1"):
        request = RequestFactory().get("/api/health", HTTP_X_FORWARDED_FOR=ip)
        request.user = user or AnonymousUser()
        return request

    def test_anon_is_limited_per_ip(self):
        throttle = AnonThrottle("2/min")
        self.assertTrue(throttle.allow_request(self.request()))
        self.assertTrue(throttle.allow_request(self.request()))
        self.assertFalse(throttle.allow_request(self.request()))
        # Another IP has its own count.
        self.assertTrue(throttle.allow_request(self.request(ip="203.0.113.2")))

    def test_ip_is_the_last_forwarded_entry(self):
        throttle = AnonThrottle("1/min")
        self.assertTrue(throttle.allow_request(self.request(ip="1.1.1.1, 203.0.113.1")))
        self.assertFalse(
            throttle.allow_request(self.request(ip="2.2.2.2, 203.0.113.1"))
        )

    def test_anon_skips_logged_in_users(self):
        throttle = AnonThrottle("1/min")
        for _ in range(3):
            self.assertTrue(throttle.allow_request(self.request(self.user)))

    def test_user_is_limited_per_user_from_any_ip(self):
        throttle = UserThrottle("1/min")
        self.assertTrue(throttle.allow_request(self.request(self.user, "203.0.113.1")))
        self.assertFalse(throttle.allow_request(self.request(self.user, "203.0.113.2")))
        # Logged out: not this throttle's business.
        self.assertTrue(throttle.allow_request(self.request()))

    def test_empty_rate_turns_it_off(self):
        self.assertEqual(
            [type(t) for t in throttles(anon="1/min", user="")], [AnonThrottle]
        )


class ApiThrottleTests(TestCase):
    def test_health_has_no_limit(self):
        # Load balancers poll it, and it must not need the cache table.
        for _ in range(130):
            self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_api_answers_429_with_retry_after(self):
        if not settings.API_THROTTLE_ANON:
            self.skipTest("API_THROTTLE_ANON is off")
        limit = int(settings.API_THROTTLE_ANON.split("/")[0])
        for _ in range(limit):
            self.assertEqual(self.client.get("/api/auth/csrf").status_code, 204)
        response = self.client.get("/api/auth/csrf")
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)


class FailureLimitTests(TestCase):
    def test_tries_count_before_their_outcome_is_known(self):
        # A burst in parallel: every try is counted before any password check
        # ends, so the ones past the limit are refused.
        limit = FailureLimit("t", "2/15min")
        self.assertIsNone(limit.attempt("x")[0])
        self.assertIsNone(limit.attempt("x")[0])
        wait, stamp = limit.attempt("x")
        self.assertGreater(wait, 0)
        self.assertIsNone(stamp)

    def test_forget_takes_back_one_try(self):
        limit = FailureLimit("t", "2/15min")
        limit.attempt("x")
        _, stamp = limit.attempt("x")
        limit.forget("x", stamp)
        self.assertIsNone(limit.attempt("x")[0])
        self.assertIsNotNone(limit.attempt("x")[0])


class HashedTests(SimpleTestCase):
    def test_keyed_with_the_secret_key(self):
        email = "ana@example.com"
        self.assertNotEqual(hashed(email), hashlib.sha256(email.encode()).hexdigest())
        with override_settings(SECRET_KEY="another-" + "x" * 50):
            other = hashed(email)
        self.assertNotEqual(hashed(email), other)


class ForgetSameTimestampTests(TestCase):
    def test_forget_takes_back_only_one_of_two_equal_stamps(self):
        limit = FailureLimit("t", "3/15min")
        limit.timer = lambda: 1000.0
        limit.attempt("x")
        _, stamp = limit.attempt("x")
        limit.forget("x", stamp)
        self.assertEqual(limit.status("x"), (1, None))
