import json
import logging
from contextlib import contextmanager
from unittest import skipUnless
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.contrib.auth.signals import user_login_failed
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils.crypto import salted_hmac

from modules.log.config import dev_columns, formatter
from modules.signals.signals import action_performed

User = get_user_model()

# The production format, whatever DEBUG the local .env sets.
FORMATTER = formatter(debug=False)


@contextmanager
def capture(name):
    """The lines `name` logs, rendered as they are written: during the
    request, while its request_id is still bound."""
    lines = []
    handler = logging.Handler()
    handler.setFormatter(FORMATTER)
    handler.emit = lambda record: lines.append(json.loads(handler.format(record)))
    logger = logging.getLogger(name)
    # Not on the test output too: not up to the root, and not through the handlers
    # the logger has itself (`django` has the console one).
    others = logger.handlers[:]
    logger.handlers = [handler]
    logger.propagate = False
    # config/test_runner.py silences logging for the other tests.
    disabled = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    try:
        yield lines
    finally:
        logging.disable(disabled)
        logger.handlers = others
        logger.propagate = True


# Skipped when the folder stays but the app is out of INSTALLED_APPS.
@skipUnless(apps.is_installed("modules.log"), "log is off")
class LoggingTest(TestCase):
    def setUp(self):
        # What a test doesn't capture itself stays off the test output.
        self.enterContext(capture("request"))
        self.enterContext(capture("auth"))

    def test_new_request_id_in_the_response(self):
        response = self.client.get("/api/health")
        self.assertRegex(response["X-Request-Id"], r"^[0-9a-f]{8}$")

    def test_keeps_the_request_id_from_the_proxy(self):
        headers = {"X-Request-Id": "from-next-1234"}
        response = self.client.get("/api/health", headers=headers)
        self.assertEqual(response["X-Request-Id"], "from-next-1234")

    def test_replaces_a_request_id_that_does_not_look_like_one(self):
        headers = {"X-Request-Id": "evil id\nwith a newline"}
        response = self.client.get("/api/health", headers=headers)
        self.assertRegex(response["X-Request-Id"], r"^[0-9a-f]{8}$")

    def test_one_line_per_request(self):
        user = User.objects.create_user("ana@example.com", "x")
        self.client.force_login(user)
        headers = {"X-Request-Id": "abcd1234", "X-Forwarded-For": "1.1.1.1, 2.2.2.2"}
        with capture("request") as lines:
            self.client.get("/api/users/me", headers=headers)
        [line] = lines
        self.assertEqual(line["event"], "200 GET /api/users/me")
        self.assertEqual(line["level"], "info")
        self.assertEqual(line["channel"], "request")
        self.assertEqual(line["service"], "backend")
        self.assertEqual(line["request_id"], "abcd1234")
        self.assertEqual(line["usr"], user.username)
        # The start of the hash the audit log saves, never the session key.
        key = self.client.session.session_key
        full = salted_hmac(user.username, key, algorithm="sha256").hexdigest()
        self.assertEqual(line["ses"], full[:12])
        self.assertNotIn(key, str(line))
        # The last hop (the Next proxy) is the one to trust.
        self.assertEqual(line["xip"], "2.2.2.2")
        self.assertIn("dur", line)

    def test_anonymous_requests_have_no_session(self):
        with capture("request") as lines:
            self.client.get("/api/health")
        [line] = lines
        self.assertIsNone(line["ses"])

    def test_api_errors_are_warnings_with_the_body(self):
        self.client.force_login(User.objects.create_user("ana@example.com", "x"))
        with capture("request") as lines:
            self.client.get("/api/users/not-a-uuid")
        [line] = lines
        self.assertEqual(line["level"], "warning")
        self.assertEqual(line["error"]["detail"][0]["type"], "uuid_parsing")

    def test_401_logs_no_body(self):
        with capture("request") as lines:
            self.client.get("/api/users/me")
        [line] = lines
        self.assertEqual(line["event"], "401 GET /api/users/me")
        self.assertNotIn("error", line)

    def failed_login(self, email):
        self.client.get("/api/auth/csrf")
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        with capture("auth") as lines:
            self.client.post(
                "/api/auth/login",
                {"email": email, "password": "wrong"},
                content_type="application/json",
                headers={
                    "X-CSRFToken": token,
                    "X-Request-Id": "abcd1234",
                    "X-Forwarded-For": "2.2.2.2",
                    "User-Agent": "x" * 1000,
                },
            )
        [line] = lines
        return line

    def test_failed_login_with_email_and_ip(self):
        line = self.failed_login(" Ana@Example.com ")
        self.assertEqual(line["event"], "login failed")
        self.assertEqual(line["channel"], "auth")
        self.assertEqual(line["request_id"], "abcd1234")
        self.assertEqual(line["email"], "ana@example.com")
        self.assertEqual(line["xip"], "2.2.2.2")
        # Cut, so a huge header can't blow up the line.
        self.assertEqual(line["uag"], "x" * 256)

    def test_failed_login_leaves_out_what_is_not_an_email(self):
        # Maybe a password typed in the wrong field.
        line = self.failed_login("hunter2-not-an-email")
        self.assertIsNone(line["email"])
        self.assertNotIn("hunter2", json.dumps(line))

    @override_settings(AUTH_LOGIN_THROTTLE_EMAIL="1/15min")
    def test_throttled_login_with_email_limit_and_ip(self):
        self.failed_login("ana@example.com")
        with capture("auth") as lines:
            self.client.post(
                "/api/auth/login",
                {"email": "ANA@example.com", "password": "wrong"},
                content_type="application/json",
                headers={"X-Forwarded-For": "3.3.3.3"},
            )
        # No "login failed": the password wasn't checked.
        [line] = lines
        self.assertEqual(line["event"], "login throttled")
        self.assertEqual(line["level"], "warning")
        self.assertEqual(line["email"], "ana@example.com")
        self.assertEqual(line["limit"], "email")
        self.assertGreater(line["retry_after"], 0)
        self.assertEqual(line["xip"], "3.3.3.3")

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_failed_admin_login_logs_the_email(self):
        # The admin's form sends the email as `username`.
        with capture("auth") as lines:
            self.client.post(
                reverse("admin:login"),
                {"username": "Ana@Example.com", "password": "wrong"},
                headers={"User-Agent": "Firefox/140"},
            )
        [line] = lines
        self.assertEqual(line["event"], "login failed")
        self.assertEqual(line["email"], "ana@example.com")
        self.assertEqual(line["uag"], "Firefox/140")

    def test_login_and_logout_with_where_they_came_from(self):
        user = User.objects.create_user("ana@example.com", "x")
        self.client.get("/api/auth/csrf")
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        headers = {
            "X-CSRFToken": token,
            "X-Forwarded-For": "2.2.2.2",
            "User-Agent": "Firefox/140",
            "Accept-Language": "pt-BR",
        }
        with capture("auth") as lines:
            self.client.post(
                "/api/auth/login",
                {"email": "ana@example.com", "password": "x"},
                content_type="application/json",
                headers=headers,
            )
            token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
            headers["X-CSRFToken"] = token
            self.client.post("/api/auth/logout", headers=headers)
        login, logout = lines
        self.assertEqual(
            (login["event"], login["usr"], login["xip"]),
            ("login", user.username, "2.2.2.2"),
        )
        self.assertEqual((login["uag"], login["lng"]), ("Firefox/140", "pt-BR"))
        self.assertNotIn(token, json.dumps(login))
        self.assertEqual(
            (logout["event"], logout["usr"], logout["xip"]),
            ("logout", user.username, "2.2.2.2"),
        )

    def test_provider_failure_logs_the_provider_and_the_reason(self):
        # What modules/oauth sends when a login through a provider fails.
        request = RequestFactory().get("/", headers={"X-Forwarded-For": "2.2.2.2"})
        with capture("auth") as lines:
            user_login_failed.send(
                sender="modules.oauth.api",
                credentials={
                    "provider": "google",
                    "reason": "inactive",
                    "email": "Ana@Example.com",
                    "secret": "never logged",
                },
                request=request,
            )
        [line] = lines
        self.assertEqual(line["event"], "login failed")
        self.assertEqual(line["provider"], "google")
        self.assertEqual(line["reason"], "inactive")
        self.assertEqual(line["email"], "ana@example.com")
        self.assertEqual(line["xip"], "2.2.2.2")
        # Only the keys it knows: credentials may hold anything.
        self.assertNotIn("never logged", json.dumps(line))

    def action(self, logger, name, by=None, **kwargs):
        request = RequestFactory().post(
            "/", headers={"X-Forwarded-For": "2.2.2.2", "User-Agent": "Firefox/140"}
        )
        request.user = by or AnonymousUser()
        with capture(logger) as lines:
            action_performed.send(None, request=request, name=name, **kwargs)
        [line] = lines
        return line

    def test_an_auth_action_says_whose_who_asked_and_where_from(self):
        admin = User.objects.create_user("admin@example.com", "x")
        ana = User.objects.create_user("ana@example.com", "x")
        line = self.action(
            "auth", "auth.end_sessions", by=admin, target=ana, values={"count": 2}
        )
        self.assertEqual(line["channel"], "auth")
        self.assertEqual(line["event"], "auth.end_sessions")
        self.assertEqual(
            (line["usr"], line["by"], line["count"]),
            (ana.username, admin.username, 2),
        )
        self.assertEqual((line["xip"], line["uag"]), ("2.2.2.2", "Firefox/140"))

    def test_other_actions_are_on_the_app_channel(self):
        admin = User.objects.create_user("admin@example.com", "x")
        line = self.action("modules.log", "cache.reveal", by=admin, values={"key": "k"})
        self.assertEqual(line["channel"], "app")
        # No target: it is the asker's.
        self.assertEqual(
            (line["usr"], line["by"], line["key"]), (admin.username,) * 2 + ("k",)
        )

    def test_a_target_that_is_not_a_user_is_nobody_s(self):
        group = Group.objects.create(name="staff")
        line = self.action("modules.log", "x.y", target=group)
        self.assertNotIn("usr", line)
        self.assertIsNone(line["by"])

    def test_values_named_like_record_fields_are_left_out(self):
        line = self.action("auth", "auth.x", values={"name": "no", "count": 1})
        self.assertEqual((line["count"], line.get("name")), (1, None))

    def test_without_a_request_who_asked_is_the_actor(self):
        # A service called outside HTTP (a task, an MCP tool) inside acting_as.
        from modules.signals.context import acting_as

        ana = User.objects.create_user("ana@example.com", "x")
        with acting_as(ana), capture("modules.log") as lines:
            action_performed.send(None, name="note.email")
        [line] = lines
        self.assertEqual((line["usr"], line["by"]), (ana.username, ana.username))
        self.assertIsNone(line["xip"])

    def test_without_a_request_inside_one_it_takes_the_current_request(self):
        from modules.signals.context import current_request

        ana = User.objects.create_user("ana@example.com", "x")
        request = RequestFactory().post("/x", headers={"User-Agent": "Firefox/140"})
        request.user = ana
        token = current_request.set(request)
        try:
            with capture("modules.log") as lines:
                action_performed.send(None, name="note.email")
        finally:
            current_request.reset(token)
        [line] = lines
        self.assertEqual((line["by"], line["uag"]), (ana.username, "Firefox/140"))

    def test_app_code_is_on_the_app_channel(self):
        with capture("apps.authd") as lines:
            logging.getLogger("apps.authd.something").info("hello")
        [line] = lines
        self.assertEqual(line["channel"], "app")


@skipUnless(apps.is_installed("modules.log"), "log is off")
class TaskLogTest(TestCase):
    """The worker sends task_started and task_finished around each task."""

    def setUp(self):
        # What a test doesn't capture itself stays off the test output.
        self.enterContext(capture("django"))
        self.enterContext(capture("modules"))

    def result(self, workers=("worker-1",)):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=UUID("729471aa-accb-4725-8843-4cfdc8623b05"),
            task=SimpleNamespace(
                queue_name="scheduled_tasks", module_path="modules.cron.jobs.x"
            ),
            status="RUNNING",
            worker_ids=list(workers),
        )

    def test_lines_during_a_task_say_which_task_and_worker(self):
        from django.tasks.signals import task_finished, task_started

        result = self.result()
        with capture("modules") as lines:
            task_started.send(sender=None, task_result=result)
            logging.getLogger("modules.cron.jobs").info("working")
            task_finished.send(sender=None, task_result=result)
            logging.getLogger("modules.cron.jobs").info("after")
        working, after = lines
        self.assertEqual(working["tsk"], "729471aa-accb-4725-8843-4cfdc8623b05")
        self.assertEqual(working["que"], "scheduled_tasks")
        self.assertEqual(working["wrk"], "worker-1")
        for field in ("tsk", "que", "wrk"):
            self.assertNotIn(field, after)

    def test_djangos_running_line_has_them_too(self):
        from django.tasks.signals import task_finished, task_started

        result = self.result()
        with capture("django") as lines:
            task_started.send(sender=None, task_result=result)
            task_finished.send(sender=None, task_result=result)
        running, done = lines
        for line in (running, done):
            self.assertEqual(line["tsk"], "729471aa-accb-4725-8843-4cfdc8623b05")
            self.assertEqual(line["wrk"], "worker-1")

    def test_the_line_that_ends_a_task_has_its_duration_last(self):
        from unittest.mock import patch

        from django.tasks.signals import task_finished, task_started

        result = self.result()
        with (
            capture("django") as lines,
            patch("modules.log.tasks.time.monotonic", side_effect=[10.0, 10.25]),
        ):
            task_started.send(sender=None, task_result=result)
            task_finished.send(sender=None, task_result=result)
        running, done = lines
        self.assertNotIn("dur", running)
        self.assertEqual(done["dur"], 250)
        # And nothing is left behind for the next line.
        with capture("modules") as after:
            logging.getLogger("modules.x").info("after")
        for field in ("tsk", "que", "wrk", "dur"):
            self.assertNotIn(field, after[0])

    def test_development_puts_the_duration_at_the_end_whatever_the_order(self):
        for fields in (
            ["tsk", "que", "wrk", "dur"],
            ["dur", "wrk", "que", "tsk"],
            ["wrk", "tsk", "dur", "que"],
        ):
            line = {"channel": "worker", "service": "backend", "event": "ended"}
            line.update({key: f"{key}-value" for key in fields})
            line["src"] = "tick"
            out = dev_columns(None, "info", line)
            self.assertEqual(list(out)[-3:], ["que", "wrk", "dur"], fields)

    def test_a_task_nobody_claimed_has_no_worker(self):
        from django.tasks.signals import task_finished, task_started

        result = self.result(workers=())
        with capture("modules") as lines:
            task_started.send(sender=None, task_result=result)
            logging.getLogger("modules.x").info("working")
            task_finished.send(sender=None, task_result=result)
        self.assertIsNone(lines[0]["wrk"])

    def test_development_shows_the_short_task_id_in_the_request_column(self):
        line = {
            "channel": "app",
            "service": "backend",
            "event": "working",
            "tsk": "729471aa-accb-4725-8843-4cfdc8623b05",
        }
        out = dev_columns(None, "info", line)
        self.assertEqual(out["event"], "app        729471aa  working")
        self.assertNotIn("tsk", out)

    @skipUnless(apps.is_installed("modules.cron"), "modules/cron is off")
    def test_cron_enqueue_logs_the_task_id_the_worker_will_log(self):
        from modules.cron import registry
        from modules.cron.models import CronSchedule

        registry.sync_schedules()
        schedule = CronSchedule.objects.get(name="task_result_purge")
        with capture("scheduler") as lines:
            run = registry.enqueue_for_schedule(
                schedule, registry.SCHEDULE_REGISTRY["task_result_purge"][1]
            )
        self.assertEqual(lines[0]["tsk"], str(run.task_result_id))
        self.assertEqual(lines[0]["channel"], "scheduler")
        self.assertEqual(lines[0]["src"], "tick")
        self.assertNotIn("usr", lines[0])

    @skipUnless(apps.is_installed("modules.cron"), "modules/cron is off")
    def test_cron_run_by_hand_says_who(self):
        from modules.cron import registry
        from modules.cron.models import CronSchedule

        registry.sync_schedules()
        schedule = CronSchedule.objects.get(name="task_result_purge")
        admin = User.objects.create_superuser(email="a@example.com", password="x")
        with capture("scheduler") as lines:
            registry.enqueue_for_schedule(
                schedule, registry.SCHEDULE_REGISTRY["task_result_purge"][1], by=admin
            )
        self.assertEqual(lines[0]["src"], "manual")
        self.assertEqual(lines[0]["usr"], admin.username)
        self.assertIn("by hand", lines[0]["event"])


@skipUnless(apps.is_installed("modules.log"), "log is off")
class WorkerChannelTest(TestCase):
    def channel_of(self, logger_name, in_task=False):
        from django.tasks.signals import task_finished, task_started

        result = TaskLogTest.result(self)
        with capture("modules") as app, capture("django") as django:
            if in_task:
                task_started.send(sender=None, task_result=result)
            logging.getLogger(logger_name).info("line")
            if in_task:
                task_finished.send(sender=None, task_result=result)
        [line] = [*app, *django][-1:]
        return line["channel"]

    def test_the_tasks_machinery_is_the_worker_channel(self):
        self.assertEqual(self.channel_of("django.tasks"), "worker")

    def test_our_code_is_the_worker_channel_only_while_a_task_runs(self):
        self.assertEqual(self.channel_of("modules.cron.jobs", in_task=True), "worker")
        self.assertEqual(self.channel_of("modules.cron.registry"), "app")
