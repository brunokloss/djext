from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, RequestFactory, TestCase

from modules.signals.signals import action_performed

from . import sessions
from .models import Session

User = get_user_model()


def log_in(user, **headers) -> Client:
    """A browser of its own, logged in as `user` through the API (every user
    here has the password "x"), so the session gets its headers."""
    client = Client(headers=headers)
    response = client.post(
        "/api/auth/login",
        {"email": user.email, "password": "x"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return client


class SessionsApiTest(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.laptop = log_in(self.ana, user_agent="Laptop")
        self.phone = log_in(self.ana, user_agent="Phone")

    def me(self, client):
        return client.get("/api/users/me").status_code

    def listed(self, client):
        response = client.get("/api/auth/sessions")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_each_login_is_a_session(self):
        rows = self.listed(self.laptop)
        self.assertEqual([r["user_agent"] for r in rows], ["Phone", "Laptop"])
        self.assertEqual([r["current"] for r in rows], [False, True])

    def test_the_id_survives_a_save(self):
        # Each save builds a new model instance: the id must not change.
        before = [r["id"] for r in self.listed(self.laptop)]
        for row in Session.objects.all():
            store = sessions.SessionStore(row.session_key)
            store["something"] = 1
            store.save()
        self.assertEqual([r["id"] for r in self.listed(self.laptop)], before)

    def test_only_your_own(self):
        bob = User.objects.create_user(email="bob@example.com", password="x")
        self.assertEqual(len(self.listed(log_in(bob))), 1)

    def test_logout_drops_it(self):
        self.phone.post("/api/auth/logout")
        self.assertEqual(len(self.listed(self.laptop)), 1)

    def test_end_another_session(self):
        phone = next(r for r in self.listed(self.laptop) if not r["current"])
        response = self.laptop.delete(f"/api/auth/sessions/{phone['id']}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.me(self.phone), 401)
        self.assertEqual(self.me(self.laptop), 200)

    def test_end_the_current_session_logs_out(self):
        current = next(r for r in self.listed(self.laptop) if r["current"])
        self.laptop.delete(f"/api/auth/sessions/{current['id']}")
        self.assertEqual(self.me(self.laptop), 401)
        self.assertEqual(self.me(self.phone), 200)

    def test_someone_elses_session_is_not_found(self):
        bob = User.objects.create_user(email="bob@example.com", password="x")
        theirs = self.listed(log_in(bob))[0]["id"]
        response = self.laptop.delete(f"/api/auth/sessions/{theirs}")
        self.assertEqual(response.status_code, 404)

    def test_end_all_logs_out_here_too(self):
        response = self.laptop.delete("/api/auth/sessions")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.me(self.laptop), 401)
        self.assertEqual(self.me(self.phone), 401)

    def test_end_all_but_this_one(self):
        log_in(self.ana, user_agent="Tablet")
        sent = []
        action_performed.connect(lambda **kw: sent.append(kw), weak=False)
        try:
            response = self.laptop.delete("/api/auth/sessions?keep_current=true")
        finally:
            action_performed.receivers.pop()
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.me(self.phone), 401)
        self.assertEqual(
            [r["user_agent"] for r in self.listed(self.laptop)], ["Laptop"]
        )
        self.assertEqual(sent[0]["name"], "auth.end_sessions")
        self.assertEqual(sent[0]["values"]["count"], 2)
        self.assertEqual(sent[0]["target"], self.ana)

    def test_needs_login(self):
        self.assertEqual(Client().get("/api/auth/sessions").status_code, 401)

    def test_needs_csrf(self):
        client = log_in(self.ana)
        client.handler.enforce_csrf_checks = True
        response = client.delete("/api/auth/sessions")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.me(self.phone), 200)


class SessionColumnsTest(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x")

    def test_ip_and_browser(self):
        log_in(self.ana, user_agent="Firefox", x_forwarded_for="203.0.113.7")
        row = Session.objects.get()
        self.assertEqual(
            (row.user, row.ip, row.user_agent), (self.ana, "203.0.113.7", "Firefox")
        )
        self.assertIsNotNone(row.logged_in_at)

    async def test_async_save_fills_the_columns(self):
        user = await User.objects.acreate_user(email="bob@example.com", password="x")
        store = sessions.SessionStore()
        await store.aupdate({SESSION_KEY: str(user.pk), sessions.IP: "203.0.113.7"})
        await store.asave()
        row = await Session.objects.aget(session_key=store.session_key)
        self.assertEqual((row.user_id, row.ip), (user.pk, "203.0.113.7"))

    def test_str_without_a_login(self):
        self.assertEqual(str(Session()), "Anonymous")

    def test_not_an_ip(self):
        request = RequestFactory().get("/", headers={"x-forwarded-for": "not-an-ip"})
        self.assertIsNone(sessions.client_ip(request))

    def test_logout_deletes_it(self):
        client = log_in(self.ana)
        client.post("/api/auth/logout")
        self.assertFalse(Session.objects.filter(user=self.ana).exists())

    def test_deleting_the_user_deletes_their_sessions(self):
        log_in(self.ana)
        self.ana.delete()
        self.assertFalse(Session.objects.exists())
