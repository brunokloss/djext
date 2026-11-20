from datetime import timedelta
from io import StringIO
from unittest import skipUnless

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from modules.session import sessions
from modules.session.models import Session
from modules.session.tests import log_in
from modules.signals.signals import action_performed

User = get_user_model()


@override_settings(ALLOWED_HOSTS=["testserver"])
class SessionsAdminTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com", password="x"
        )
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.client.force_login(self.admin)
        self.change_url = reverse("admin:authd_user_change", args=[self.ana.pk])
        self.list_url = reverse("admin:authd_user_changelist")

    def log_out_everywhere(self, *users):
        return self.client.post(
            self.list_url,
            {"action": "log_out_everywhere", "_selected_action": [u.pk for u in users]},
        )

    def test_inline_lists_sessions(self):
        log_in(self.ana, user_agent="Phone", x_forwarded_for="203.0.113.7")
        page = self.client.get(self.change_url).content.decode()
        self.assertIn("203.0.113.7", page)
        self.assertIn("Phone", page)
        self.assertIn('<option value="log_out_everywhere">', page)

    def test_log_out_everywhere(self):
        phone, laptop = log_in(self.ana), log_in(self.ana)
        sent = []
        action_performed.connect(lambda **kw: sent.append(kw), weak=False)
        try:
            response = self.log_out_everywhere(self.ana)
        finally:
            action_performed.receivers.pop()
        self.assertRedirects(response, self.list_url)
        for client in (phone, laptop):
            self.assertEqual(client.get("/api/users/me").status_code, 401)
        self.assertEqual(sent[0]["values"], {"which": "all", "count": 2})
        self.assertEqual(sent[0]["target"], self.ana)
        # The admin's own session is another user's: untouched.
        self.assertEqual(self.client.get(self.change_url).status_code, 200)

    def test_log_out_everywhere_counts_live_sessions(self):
        log_in(self.ana)
        expired = log_in(self.ana).session.session_key
        Session.objects.filter(session_key=expired).update(
            expire_date=timezone.now() - timedelta(seconds=1)
        )
        response = self.log_out_everywhere(self.ana)
        self.assertContains(
            self.client.get(response.url), "was logged out of 1 session."
        )

    def test_log_out_everywhere_from_the_user_page(self):
        phone = log_in(self.ana)
        bob = User.objects.create_user(email="bob@example.com", password="x")
        theirs = log_in(bob)
        response = self.client.post(
            self.change_url,
            {
                "CHANGE_FORM-action": "log_out_everywhere",
                "_selected_action": self.ana.pk,
            },
        )
        self.assertRedirects(response, self.change_url)
        self.assertEqual(phone.get("/api/users/me").status_code, 401)
        # Only that user.
        self.assertEqual(theirs.get("/api/users/me").status_code, 200)

    def test_deleting_one_in_the_inline_ends_it(self):
        phone, laptop = log_in(self.ana), log_in(self.ana)
        row = Session.objects.get(session_key=phone.session.session_key)
        sent = []
        action_performed.connect(lambda **kw: sent.append(kw), weak=False)
        try:
            response = self.client.post(
                self.change_url,
                {
                    "email": self.ana.email,
                    "is_active": "on",
                    "sessions-TOTAL_FORMS": "2",
                    "sessions-INITIAL_FORMS": "2",
                    "sessions-0-session_key": row.session_key,
                    "sessions-0-user": self.ana.pk,
                    "sessions-0-DELETE": "on",
                    "sessions-1-session_key": laptop.session.session_key,
                    "sessions-1-user": self.ana.pk,
                    "bearer_key-TOTAL_FORMS": "0",
                    "bearer_key-INITIAL_FORMS": "0",
                    "crypto-keyset-owner_type-owner_id-TOTAL_FORMS": "0",
                    "crypto-keyset-owner_type-owner_id-INITIAL_FORMS": "0",
                },
            )
        finally:
            action_performed.receivers.pop()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(phone.get("/api/users/me").status_code, 401)
        self.assertEqual(laptop.get("/api/users/me").status_code, 200)
        # Through end_sessions, so the audit log has it.
        self.assertEqual(sent[0]["values"]["which"], "one")

    def test_log_out_everywhere_yourself_keeps_this_session(self):
        phone = log_in(self.admin)
        self.log_out_everywhere(self.admin)
        self.assertEqual(phone.get("/api/users/me").status_code, 401)
        self.assertEqual(self.client.get(self.change_url).status_code, 200)

    @skipUnless(apps.is_installed("modules.audit"), "needs modules.audit")
    def test_the_audit_log_names_the_user_and_who_asked(self):
        from modules.audit.models import AuditLog

        log_in(self.ana)
        self.log_out_everywhere(self.ana)
        log = AuditLog.objects.get(name="auth.end_sessions")
        self.assertEqual((log.object_id, log.actor), (str(self.ana.pk), self.admin))
        self.assertEqual(log.subjects, [f"authd.user:{self.ana.pk}"])

    def test_staff_without_change_permission(self):
        phone = log_in(self.ana)
        staff = User.objects.create_user(
            email="staff@example.com", password="x", is_staff=True
        )
        self.client.force_login(staff)
        self.log_out_everywhere(self.ana)
        self.assertEqual(phone.get("/api/users/me").status_code, 200)


@override_settings(DEBUG=True)
class ClearExampleSessionsTest(TestCase):
    """The e2e teardown: only what the run created goes."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.other = User.objects.create_user(email="me@other.com", password="x")

    def clear(self, since):
        call_command(
            "clear_example_sessions", since=since.isoformat(), stdout=StringIO()
        )

    def test_deletes_the_runs_sessions_only(self):
        before = log_in(self.ana)
        since = timezone.now()
        log_in(self.ana)
        mine = log_in(self.other)
        anonymous = sessions.SessionStore()
        anonymous["_messages"] = "[]"
        anonymous.save()
        self.assertEqual(Session.objects.filter(user=None).count(), 1)
        self.clear(since)
        left = set(Session.objects.values_list("session_key", flat=True))
        self.assertEqual(
            left,
            {before.session.session_key, mine.session.session_key},
        )

    @override_settings(DEBUG=False)
    def test_refuses_without_debug(self):
        log_in(self.ana)
        with self.assertRaises(CommandError):
            self.clear(timezone.now() - timedelta(days=1))
        self.assertTrue(Session.objects.exists())
