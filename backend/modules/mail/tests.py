import os
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.core import mail
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django_tasks_db.models import DBTaskResult
from post_office import mail as post_office
from post_office.models import STATUS, Email, EmailTemplate, Log

from modules.mail.emails import delete_emails_to
from modules.mail.mailers import mailers_from_url
from modules.mail.tasks import send_email


class DeleteEmailsToTest(TestCase):
    def test_deletes_the_emails_sent_to_them(self):
        address = "ana@example.com"

        def email(**recipients):
            return Email.objects.create(from_email="app@example.com", **recipients)

        mine = [
            email(to=[address.upper()]),
            email(to=["bob@example.com"], cc=[address]),
            email(bcc=[address]),
        ]
        others = email(to=["bob.ana@example.com"])
        Log.objects.create(email=mine[0], status=STATUS.sent)
        delete_emails_to(address)
        self.assertQuerySetEqual(Email.objects.all(), [others])
        self.assertFalse(Log.objects.exists())


class MailerFromUrlTest(SimpleTestCase):
    def test_empty_prints_to_the_console(self):
        self.assertIn("console", mailers_from_url("")["direct"]["BACKEND"])

    def test_default_is_the_queue(self):
        self.assertEqual(
            mailers_from_url("")["default"]["BACKEND"], "post_office.EmailBackend"
        )

    def test_smtp_url(self):
        options = mailers_from_url("smtp://me:p%40ss@smtp.example.com:2525?tls=true")[
            "direct"
        ]["OPTIONS"]
        self.assertEqual(options["host"], "smtp.example.com")
        self.assertEqual(options["port"], 2525)
        self.assertEqual(options["password"], "p@ss")
        self.assertTrue(options["use_tls"])
        self.assertFalse(options["use_ssl"])

    def test_smtps_is_ssl(self):
        options = mailers_from_url("smtps://u:p@smtp.example.com")["direct"]["OPTIONS"]
        self.assertEqual(options["port"], 465)
        self.assertTrue(options["use_ssl"])

    def test_plain_smtp(self):
        # A relay inside the network: no TLS, no login, port 25.
        direct = mailers_from_url("smtp://relay.internal")["direct"]
        self.assertIn("smtp.EmailBackend", direct["BACKEND"])
        options = direct["OPTIONS"]
        self.assertEqual(options["port"], 25)
        self.assertFalse(options["use_tls"])
        self.assertFalse(options["use_ssl"])
        self.assertEqual((options["username"], options["password"]), ("", ""))

    def test_tls_without_a_port_is_587(self):
        options = mailers_from_url("smtp://u:p@smtp.example.com?tls=1")["direct"][
            "OPTIONS"
        ]
        self.assertEqual(options["port"], 587)
        self.assertTrue(options["use_tls"])

    def test_ssl_wins_over_tls(self):
        # Both at once is an error in Django's SMTP backend.
        options = mailers_from_url("smtps://u:p@smtp.example.com?tls=true")["direct"][
            "OPTIONS"
        ]
        self.assertTrue(options["use_ssl"])
        self.assertFalse(options["use_tls"])

    def test_provider(self):
        direct = mailers_from_url("resend://re_abc123@")["direct"]
        self.assertEqual(direct["BACKEND"], "anymail.backends.resend.EmailBackend")
        self.assertEqual(direct["OPTIONS"], {"api_key": "re_abc123"})

    def test_provider_options_come_from_the_query(self):
        options = mailers_from_url("mailgun://key@?sender_domain=mg.example.com")[
            "direct"
        ]["OPTIONS"]
        self.assertEqual(options, {"sender_domain": "mg.example.com", "api_key": "key"})

    def test_provider_needs_a_key(self):
        with self.assertRaises(ValueError):
            mailers_from_url("resend://")

    def test_bad_url(self):
        with self.assertRaises(ValueError):
            mailers_from_url("http://example.com")


LOCMEM = {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}


@override_settings(
    MAILERS={"default": {"BACKEND": "post_office.EmailBackend"}, "direct": LOCMEM}
)
class QueueTest(TestCase):
    def test_each_email_gets_its_own_task(self):
        with self.captureOnCommitCallbacks(execute=True):
            mail.send_mail("Hi", "Hello", None, ["ana@example.com"])
            mail.send_mail("Hi", "Hello", None, ["bia@example.com"])
        self.assertEqual(mail.outbox, [])  # Saved, not sent.
        emails = list(Email.objects.order_by("id"))
        self.assertEqual([e.status for e in emails], [STATUS.queued] * 2)
        tasks = DBTaskResult.objects.order_by("enqueued_at")
        self.assertEqual(
            [t.args_kwargs["args"] for t in tasks], [[e.pk] for e in emails]
        )

    def test_the_task_sends_only_its_email(self):
        first = post_office.send(
            "ana@example.com", "a@localhost", subject="1", message="x"
        )
        second = post_office.send(
            "bia@example.com", "a@localhost", subject="2", message="x"
        )
        send_email.call(first.pk)
        self.assertEqual([m.to for m in mail.outbox], [["ana@example.com"]])
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, STATUS.sent)
        self.assertEqual(second.status, STATUS.queued)

    def test_a_second_task_for_the_same_email_sends_nothing(self):
        email = post_office.send(
            "ana@example.com", "a@localhost", subject="1", message="x"
        )
        send_email.call(email.pk)
        send_email.call(email.pk)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_retry_in_the_future_waits(self):
        email = post_office.send(
            "ana@example.com",
            "a@localhost",
            subject="1",
            message="x",
            scheduled_time=timezone.now() + timedelta(hours=1),
        )
        send_email.call(email.pk)
        self.assertEqual(mail.outbox, [])

    def test_the_last_failure_is_final(self):
        email = post_office.send(
            "ana@example.com", "a@localhost", subject="1", message="x"
        )
        Email.objects.filter(pk=email.pk).update(number_of_retries=3)  # MAX_RETRIES
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages",
            side_effect=OSError("down"),
        ):
            send_email.call(email.pk)
        email.refresh_from_db()
        self.assertEqual(email.status, STATUS.failed)
        self.assertEqual(email.number_of_retries, 3)

    def test_a_failure_is_requeued_for_a_retry(self):
        email = post_office.send(
            "ana@example.com", "a@localhost", subject="1", message="x"
        )
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages",
            side_effect=OSError("down"),
        ):
            send_email.call(email.pk)
        email.refresh_from_db()
        self.assertEqual(email.status, STATUS.requeued)
        self.assertEqual(email.number_of_retries, 1)
        self.assertTrue(email.logs.exists())


@override_settings(
    MAILERS={"default": {"BACKEND": "post_office.EmailBackend"}, "direct": LOCMEM}
)
class TemplateAndAttachmentTest(TestCase):
    def deliver(self):
        for email in Email.objects.order_by("id"):
            send_email.call(email.pk)

    def test_a_template_is_rendered_with_its_context(self):
        call_command("seed_email_templates", stdout=StringIO())
        post_office.send(
            "ana@example.com",
            "no-reply@localhost",
            template="welcome",
            context={"name": "Ana", "url": "https://x/start"},
        )
        self.deliver()
        (message,) = mail.outbox
        self.assertEqual(message.subject, "Welcome, Ana!")
        self.assertIn("https://x/start", message.body)
        self.assertIn("<h1>Welcome, Ana!</h1>", message.alternatives[0].content)

    def test_a_broken_template_fails_in_the_worker_not_in_the_request(self):
        EmailTemplate.objects.create(name="broken", subject="Hi", content="{% nope %}")
        # Rendered on delivery: the request that asks for the email does not see it.
        post_office.send(
            "ana@example.com",
            "no-reply@localhost",
            template="broken",
            context={},
            render_on_delivery=True,
        )
        self.deliver()
        email = Email.objects.get()
        self.assertEqual(mail.outbox, [])
        self.assertIn(email.status, (STATUS.failed, STATUS.requeued))
        self.assertIn("TemplateSyntaxError", email.logs.get().exception_type)

    def test_an_unknown_template_fails_in_the_request(self):
        with self.assertRaises(EmailTemplate.DoesNotExist):
            post_office.send("ana@example.com", "no-reply@localhost", template="nope")

    def test_an_attachment_arrives(self):
        with (
            tempfile.TemporaryDirectory() as media,
            override_settings(MEDIA_ROOT=media),
        ):
            post_office.send(
                "ana@example.com",
                "no-reply@localhost",
                subject="Invoice",
                message="See attached.",
                attachments={
                    "invoice.txt": ContentFile(b"total: 10", name="invoice.txt")
                },
            )
            self.deliver()
        (message,) = mail.outbox
        self.assertEqual(message.attachments[0][0], "invoice.txt")
        self.assertIn(message.attachments[0][1], ("total: 10", b"total: 10"))

    def test_send_mail_with_an_attachment_keeps_it_too(self):
        with (
            tempfile.TemporaryDirectory() as media,
            override_settings(MEDIA_ROOT=media),
        ):
            message = EmailMessage(
                "Invoice", "See attached.", None, ["ana@example.com"]
            )
            message.attach("invoice.txt", b"total: 10", "text/plain")
            message.send()
            self.deliver()
        (sent,) = mail.outbox
        self.assertEqual(sent.attachments[0][0], "invoice.txt")


# The other process of TwoWorkersTest, and how many emails both get.
WORKER = Path(__file__).with_name("email_worker.py")
EMAILS = 20


@skipUnless(connection.vendor == "postgresql", "SKIP LOCKED needs Postgres")
class TwoWorkersTest(TransactionTestCase):
    """Two real processes run send_email for the same emails at once: each
    email goes out exactly once (the row lock, SELECT ... FOR UPDATE SKIP
    LOCKED), and both do part of the work. A TransactionTestCase: the other
    processes only see committed rows."""

    def database_url(self) -> str:
        db = connection.settings_dict
        return (
            f"postgres://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db['PORT']}"
            f"/{db['NAME']}"
        )

    def start(self, out: Path, ids: list[int]) -> subprocess.Popen:
        env = {
            **os.environ,
            "DATABASE_URL": self.database_url(),
            "EMAIL_WORKER_DIR": str(out),
        }
        return subprocess.Popen(
            [sys.executable, str(WORKER), ",".join(map(str, ids))],
            env=env,
            cwd=WORKER.parents[2],
        )

    def wait_ready(self, out: Path, workers):
        deadline = time.monotonic() + 60
        while len(list(out.glob("ready-*"))) < len(workers):
            if any(w.poll() is not None for w in workers):
                self.fail("a worker exited before it was ready")
            if time.monotonic() > deadline:
                self.fail("the workers took over 60 s to start")
            time.sleep(0.05)

    def test_each_email_is_sent_once(self):
        emails = Email.objects.bulk_create(
            Email(
                from_email="a@localhost",
                to=[f"user{i}@example.com"],
                subject=f"email {i}",
                message="x",
                status=STATUS.queued,
            )
            for i in range(EMAILS)
        )
        ids = [e.pk for e in emails]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            # Same order for both: they meet on every row.
            workers = [self.start(out, ids), self.start(out, ids)]
            try:
                self.wait_ready(out, workers)
                (out / "go").touch()
                codes = [w.wait(timeout=120) for w in workers]
            finally:
                for w in workers:
                    w.kill()
            self.assertEqual(codes, [0, 0])
            sent = {f.name: f.read_text().splitlines() for f in out.glob("sent-*")}

        everything = [subject for lines in sent.values() for subject in lines]
        self.assertCountEqual(everything, [f"email {i}" for i in range(EMAILS)])
        self.assertEqual(len(sent), 2, f"only one worker sent anything: {sent}")
        self.assertEqual(
            set(Email.objects.values_list("status", flat=True)), {STATUS.sent}
        )
