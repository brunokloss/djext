from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_tasks_db.models import DBTaskResult, get_date_max

from modules.signals.signals import action_performed

from .stats import stats
from .tasks import ping

User = get_user_model()

# The email tests are skipped, not broken, when django-post-office is removed.
HAS_EMAIL = apps.is_installed("post_office")
if HAS_EMAIL:
    from post_office import mail as post_office
    from post_office.models import STATUS, Email


def make_email(status=None, age=0, **fields) -> Email:
    """An email created `age` seconds ago (and last changed then too)."""
    email = Email.objects.create(
        from_email="a@example.com",
        to=["b@example.com"],
        status=STATUS.queued if status is None else status,
        **fields,
    )
    when = timezone.now() - timedelta(seconds=age)
    Email.objects.filter(pk=email.pk).update(created=when, last_updated=when)
    return email


def make_task(age=0, **fields) -> DBTaskResult:
    """A ready task enqueued `age` seconds ago, with no `run_after`."""
    task = DBTaskResult.objects.create(
        args_kwargs={"args": [], "kwargs": {}},
        task_path="modules.mail.tasks.send_email",
        queue_name="default",
        backend_name="default",
        run_after=get_date_max(),
        **fields,
    )
    DBTaskResult.objects.filter(pk=task.pk).update(
        enqueued_at=timezone.now() - timedelta(seconds=age)
    )
    return task


class StatsTest(TestCase):
    def test_empty(self):
        data = stats()
        self.assertEqual(data["tasks"]["due"], 0)
        self.assertIsNone(data["tasks"]["oldest_wait"])
        self.assertFalse(data["stalled"])

    def test_something_due_for_long_is_stalled(self):
        make_task(age=5)
        self.assertFalse(stats()["stalled"])
        make_task(age=90)
        data = stats()
        self.assertTrue(data["stalled"])
        self.assertEqual(data["tasks"]["due"], 2)
        self.assertGreaterEqual(data["tasks"]["oldest_wait"], 90)

    def test_failed_tasks_are_not_reported(self):
        self.assertNotIn("failed_24h", stats()["tasks"])


@skipUnless(HAS_EMAIL, "django-post-office is off")
class EmailStatsTest(TestCase):
    def test_empty(self):
        self.assertEqual(stats()["emails"]["due"], 0)

    def test_an_old_email_is_stalled_too(self):
        make_email(age=120)
        data = stats()
        self.assertTrue(data["stalled"])
        self.assertEqual(data["emails"]["due"], 1)

    def test_emails_for_later_and_expired_are_not_due(self):
        now = timezone.now()
        make_email(age=500, scheduled_time=now + timedelta(hours=1))
        make_email(age=500, expires_at=now - timedelta(minutes=1))
        data = stats()
        self.assertEqual(data["emails"]["due"], 0)
        self.assertEqual(data["emails"]["later"], 1)
        self.assertFalse(data["stalled"])

    def test_email_latency_of_the_last_hour(self):
        # Created `waited` seconds before being sent (now).
        for waited in (10, 30):
            email = make_email(STATUS.sent, age=waited)
            Email.objects.filter(pk=email.pk).update(last_updated=timezone.now())
        # Sent before the last hour: not counted.
        make_email(STATUS.sent, age=7200)
        emails = stats()["emails"]
        self.assertAlmostEqual(emails["avg_latency"], 20, delta=1)
        self.assertAlmostEqual(emails["max_latency"], 30, delta=1)

    def test_failed_and_requeued_counts_by_window(self):
        make_email(STATUS.failed, age=60)
        make_email(STATUS.failed, age=3 * 86400)
        make_email(STATUS.failed, age=40 * 86400)
        make_email(
            STATUS.requeued, age=60, scheduled_time=timezone.now() + timedelta(hours=1)
        )
        emails = stats()["emails"]
        self.assertEqual(emails["failed_24h"], 1)
        self.assertEqual(emails["failed_30d"], 2)
        self.assertEqual(emails["requeued_24h"], 1)
        self.assertEqual(emails["requeued_30d"], 1)


@skipUnless(HAS_EMAIL, "django-post-office is off")
@skipUnless(apps.is_installed("modules.mail"), "modules/mail is off")
class RealFailureTest(TestCase):
    """A send that really fails in the task shows up in the email counts."""

    def fail_once(self, email):
        from modules.mail.tasks import send_email

        with patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages",
            side_effect=OSError("down"),
        ):
            send_email.call(email.pk)

    def test_a_failing_send_is_requeued_then_failed(self):
        email = post_office.send(
            "a@example.com", "b@localhost", subject="s", message="m"
        )
        self.fail_once(email)
        emails = stats()["emails"]
        self.assertEqual((emails["requeued_24h"], emails["failed_24h"]), (1, 0))
        # Retrying later, so it is not due now.
        self.assertEqual((emails["due"], emails["later"]), (0, 1))

        # The retries are used up: the last failure is final.
        Email.objects.filter(pk=email.pk).update(
            number_of_retries=3, scheduled_time=None
        )
        self.fail_once(email)
        emails = stats()["emails"]
        self.assertEqual((emails["requeued_24h"], emails["failed_24h"]), (0, 1))
        self.assertEqual(emails["failed_30d"], 1)
        # The task itself ended fine: nothing about failed tasks is reported.
        self.assertNotIn("failed_24h", stats()["tasks"])


class AdminTest(TestCase):
    def setUp(self):
        self.page = reverse("admin:queue")
        self.json = reverse("admin:queue_stats")

    def test_superusers_see_the_page_and_the_json(self):
        self.client.force_login(User.objects.create_superuser(email="root@example.com"))
        response = self.client.get(self.page)
        self.assertContains(response, "Oldest waiting")
        # In the sidebar too.
        self.assertContains(response, f'href="{self.page}"')
        data = self.client.get(self.json).json()
        self.assertEqual(data["tasks"]["due"], 0)
        self.assertIs(data["stalled"], False)

    def test_staff_who_are_not_superusers_dont(self):
        staff = User.objects.create_user(email="staff@example.com", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.page).status_code, 404)
        self.assertEqual(self.client.get(self.json).status_code, 404)
        self.assertNotContains(self.client.get(reverse("admin:index")), "Queue")

    def test_home_warns_when_stalled(self):
        self.client.force_login(User.objects.create_superuser(email="root@example.com"))
        home = reverse("admin:index")
        self.assertNotContains(self.client.get(home), "worker seems stopped")
        make_task(age=300)
        self.assertContains(self.client.get(home), "worker seems stopped")

    def test_staff_get_no_warning(self):
        make_task(age=300)
        staff = User.objects.create_user(email="staff@example.com", is_staff=True)
        self.client.force_login(staff)
        self.assertNotContains(
            self.client.get(reverse("admin:index")), "worker seems stopped"
        )


class PingTest(TestCase):
    def setUp(self):
        self.url = reverse("admin:queue_ping")

    def test_enqueues_and_opens_the_result(self):
        admin = User.objects.create_superuser(email="admin@example.com", password="x")
        self.client.force_login(admin)
        sent = []
        action_performed.connect(lambda **kw: sent.append(kw), weak=False)
        try:
            response = self.client.post(self.url)
        finally:
            action_performed.receivers.pop()
        result = DBTaskResult.objects.get()
        self.assertEqual(result.task_path, "modules.queue.tasks.ping")
        self.assertRedirects(
            response,
            reverse(
                "admin:django_tasks_database_dbtaskresult_change", args=[result.pk]
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(sent[0]["name"], "queue.ping")
        self.assertEqual(sent[0]["values"], {"task": str(result.pk)})

    def test_page_has_the_button(self):
        admin = User.objects.create_superuser(email="admin@example.com", password="x")
        self.client.force_login(admin)
        page = self.client.get(reverse("admin:queue"))
        self.assertContains(page, f'action="{self.url}"')

    def test_get_does_not_enqueue(self):
        admin = User.objects.create_superuser(email="admin@example.com", password="x")
        self.client.force_login(admin)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertFalse(DBTaskResult.objects.exists())

    def test_superusers_only(self):
        staff = User.objects.create_user(
            email="staff@example.com", password="x", is_staff=True
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertFalse(DBTaskResult.objects.exists())

    def test_the_task_returns_its_message(self):
        self.assertEqual(ping.call("hello"), "hello")
