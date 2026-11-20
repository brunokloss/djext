from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class PingTest(TestCase):
    def test_ping_answers_pong(self):
        self.client.force_login(User.objects.create_user(email="ana@example.com"))
        response = self.client.post(
            "/api/ping", {"message": "ping"}, content_type="application/json"
        )
        self.assertEqual(response.json(), {"message": "pong"})

    def test_ping_needs_login(self):
        response = self.client.post("/api/ping", {}, content_type="application/json")
        self.assertEqual(response.status_code, 401)
