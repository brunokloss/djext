from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


class SmokeTest(TestCase):
    def test_admin_login_page_loads(self):
        response = self.client.get(reverse("admin:login"))
        self.assertEqual(response.status_code, 200)

    def test_api_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        time = datetime.fromisoformat(body["time"])
        self.assertLess(abs(timezone.now() - time), timedelta(seconds=5))

    def test_api_health_db(self):
        response = self.client.get("/api/health-db")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_api_health_db_without_database(self):
        from unittest import mock

        from django.db.utils import OperationalError

        with mock.patch(
            "modules.health.api.connection.cursor", side_effect=OperationalError
        ):
            response = self.client.get("/api/health-db")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "error"})

    def test_api_docs_require_login(self):
        from django.contrib.auth import get_user_model

        for path in ("/api/docs", "/api/openapi.json"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertRedirects(
                    response, f"/login?next={path}", fetch_redirect_response=False
                )
        self.client.force_login(
            get_user_model().objects.create_user(email="ana@example.com")
        )
        self.assertEqual(self.client.get("/api/docs").status_code, 200)
        self.assertEqual(self.client.get("/api/openapi.json").status_code, 200)
