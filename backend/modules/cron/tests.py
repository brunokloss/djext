import os
import signal
from contextlib import contextmanager
from datetime import UTC, timedelta
from unittest import skipUnless
from unittest.mock import call, patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection
from django.tasks import task
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from django_tasks_db.models import DBTaskResult

from . import registry
from .admin import CronScheduleAdmin
from .models import CronRun, CronSchedule

# 05:00 UTC: when `prune_task_results` ("0 5 * * *") is due.
DUE = timezone.datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
NAME = "prune_task_results"


@registry.scheduled("0 4 * * *")
@task
def sample_job():
    """A job that starts disabled, like yours."""


SAMPLE = "sample_job"


class SyncTest(TestCase):
    def test_new_jobs_start_disabled_unless_they_ask(self):
        registry.sync_schedules()
        self.assertFalse(CronSchedule.objects.get(name=SAMPLE).enabled)
        self.assertTrue(CronSchedule.objects.get(name=NAME).enabled)

    @override_settings(CRON_AUTO_ENABLE_NEW_TASKS=True)
    def test_auto_enable_only_sets_new_rows(self):
        registry.sync_schedules()
        self.assertTrue(CronSchedule.objects.get(name=SAMPLE).enabled)
        CronSchedule.objects.filter(name=SAMPLE).update(enabled=False)
        registry.sync_schedules()
        self.assertFalse(CronSchedule.objects.get(name=SAMPLE).enabled)


class TickTest(TestCase):
    def setUp(self):
        registry.sync_schedules()
        # Only prune_task_results: the other shipped job is due at the same time.
        CronSchedule.objects.exclude(name=NAME).update(enabled=False)
        self.schedule = CronSchedule.objects.get(name=NAME)

    def tick(self, when=DUE):
        registry.cron_tick(when)

    def test_disabled_job_is_not_enqueued(self):
        CronSchedule.objects.filter(pk=self.schedule.pk).update(enabled=False)
        self.tick()
        self.assertEqual(DBTaskResult.objects.count(), 0)

    def test_due_job_is_enqueued_once_and_linked(self):
        CronSchedule.objects.filter(pk=self.schedule.pk).update(enabled=True)
        self.tick()
        self.assertEqual(DBTaskResult.objects.count(), 1)
        run = CronRun.objects.get()
        self.assertEqual(run.schedule_id, self.schedule.pk)
        self.assertEqual(run.task_result_id, DBTaskResult.objects.get().id)
        self.schedule.refresh_from_db()
        self.assertTrue(self.schedule.is_last_enqueue_ok)

    def test_job_not_due_is_skipped(self):
        CronSchedule.objects.filter(pk=self.schedule.pk).update(enabled=True)
        self.tick(DUE + timedelta(minutes=1))
        self.assertEqual(DBTaskResult.objects.count(), 0)

    def test_a_job_not_due_does_not_hold_back_the_next(self):
        CronSchedule.objects.filter(name__in=[NAME, SAMPLE]).update(enabled=True)
        # In this order: the one not due at 04:00 comes first.
        jobs = {name: registry.SCHEDULE_REGISTRY[name] for name in (NAME, SAMPLE)}
        with patch.object(registry, "SCHEDULE_REGISTRY", jobs):
            self.tick(DUE.replace(hour=4))
        self.assertEqual(
            list(CronRun.objects.values_list("schedule__name", flat=True)), [SAMPLE]
        )

    def test_expression_override_wins_over_code(self):
        CronSchedule.objects.filter(pk=self.schedule.pk).update(
            enabled=True, expression="30 9 * * *"
        )
        self.tick()
        self.assertEqual(DBTaskResult.objects.count(), 0)
        self.tick(DUE.replace(hour=9, minute=30))
        self.assertEqual(DBTaskResult.objects.count(), 1)

    def test_paused_job_is_skipped(self):
        CronSchedule.objects.filter(pk=self.schedule.pk).update(
            enabled=True, paused_until=timezone.now() + timedelta(hours=1)
        )
        self.tick()
        self.assertEqual(DBTaskResult.objects.count(), 0)

    def test_enqueue_failure_is_recorded_and_does_not_stop_the_tick(self):
        CronSchedule.objects.filter(pk=self.schedule.pk).update(enabled=True)
        with patch.object(registry, "enqueue_for_schedule", side_effect=OSError("db")):
            self.tick()
        self.schedule.refresh_from_db()
        self.assertFalse(self.schedule.is_last_enqueue_ok)
        self.assertIn("OSError", self.schedule.last_enqueue_error)


class ShippedJobsTest(TestCase):
    def test_housekeeping_runs_at_5_utc_and_starts_on(self):
        registry.sync_schedules()
        for name in ("prune_task_results", "audit_purge"):
            with self.subTest(name):
                self.assertEqual(registry.SCHEDULE_REGISTRY[name][0], "0 5 * * *")
                self.assertTrue(CronSchedule.objects.get(name=name).enabled)

    def test_audit_purge_calls_the_command_by_name(self):
        from .tasks import audit_purge

        with patch("modules.cron.tasks.call_command") as call:
            audit_purge.func()
        call.assert_called_once_with("audit_purge")

    def test_audit_purge_does_nothing_without_the_audit_module(self):
        from .tasks import audit_purge

        with (
            patch("modules.cron.tasks.get_commands", return_value={}),
            patch("modules.cron.tasks.call_command") as call,
        ):
            audit_purge.func()
        call.assert_not_called()


class RetentionTest(TestCase):
    def setUp(self):
        registry.sync_schedules()
        self.schedule = CronSchedule.objects.first()

    @override_settings(TASK_RESULT_RETENTION_DAYS=7)
    def test_prune_task_results_drops_old_runs_too(self):
        import uuid

        from .tasks import prune_task_results

        old = CronRun.objects.create(
            schedule=self.schedule, task_result_id=uuid.uuid4()
        )
        new = CronRun.objects.create(
            schedule=self.schedule, task_result_id=uuid.uuid4()
        )
        CronRun.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=8)
        )
        with patch("modules.cron.tasks.call_command") as command:
            prune_task_results.func()
        command.assert_called_once_with(
            "prune_db_task_results", min_age_days=7, queue_name="*"
        )
        self.assertEqual(list(CronRun.objects.all()), [new])


@contextmanager
def development_jobs():
    """modules/cron/tasks.py with DEBUG on, so test_heartbeat and test_always_fails
    exist; the registry is put back as it was after."""
    import importlib

    from . import tasks

    names = ("test_heartbeat", "test_always_fails")
    try:
        with override_settings(DEBUG=True):
            importlib.reload(tasks)
        yield tasks
    finally:
        for name in names:
            registry.SCHEDULE_REGISTRY.pop(name, None)
            registry.STARTS_ENABLED.pop(name, None)
        importlib.reload(tasks)


class DevelopmentJobsTest(TestCase):
    def test_they_are_not_registered_without_debug(self):
        self.assertNotIn("test_always_fails", registry.SCHEDULE_REGISTRY)
        self.assertNotIn("test_heartbeat", registry.SCHEDULE_REGISTRY)

    def test_test_always_fails_fails_on_purpose(self):
        with development_jobs() as tasks:
            with self.assertRaisesMessage(RuntimeError, "on purpose"):
                tasks.test_always_fails.func()

    def test_the_heartbeat_waits_a_little_and_says_it_is_alive(self):
        with (
            development_jobs() as tasks,
            patch("modules.cron.tasks.time.sleep") as sleep,
        ):
            tasks.test_heartbeat.func()
        [(seconds,), _] = sleep.call_args
        self.assertTrue(0.05 <= seconds <= 0.4)

    @override_settings(CRON_AUTO_ENABLE_NEW_TASKS=True)
    def test_both_start_off_even_when_new_jobs_start_on(self):
        with development_jobs():
            registry.sync_schedules()
            for name in ("test_heartbeat", "test_always_fails"):
                self.assertFalse(CronSchedule.objects.get(name=name).enabled, name)

    def test_the_heartbeat_runs_every_minute(self):
        with development_jobs():
            self.assertEqual(
                registry.SCHEDULE_REGISTRY["test_heartbeat"][0], "* * * * *"
            )


class NoResultIdTest(TestCase):
    def test_an_enqueue_that_returns_no_id_is_a_failure_not_a_success(self):
        from types import SimpleNamespace

        registry.sync_schedules()
        schedule = CronSchedule.objects.get(name=NAME)
        no_id = SimpleNamespace(enqueue=lambda: SimpleNamespace(id=None))
        with self.assertRaisesMessage(RuntimeError, "no result id"):
            registry.enqueue_for_schedule(schedule, no_id)
        self.assertEqual(CronRun.objects.count(), 0)


class ModelTest(TestCase):
    def test_invalid_expression_is_rejected(self):
        with self.assertRaises(ValidationError):
            CronSchedule(name="x", expression="not a cron").save()

    def test_invalid_expression_in_decorator_fails_at_import(self):
        with self.assertRaises(ValueError):
            registry.scheduled("not a cron")

    def test_scheduled_on_a_plain_function_is_an_error(self):
        def plain():
            pass

        with self.assertRaisesMessage(TypeError, "Put @task under it"):
            registry.scheduled("0 4 * * *")(plain)

    def test_two_jobs_with_the_same_function_name_is_an_error(self):
        # Schedules are keyed by the function name: the second would replace
        # the first, which would then never run.
        def job_in(module):
            def cleanup():
                pass

            # As if defined at the top of that module (@task wants that).
            cleanup.__module__, cleanup.__qualname__ = module, "cleanup"
            return task(cleanup)

        self.addCleanup(registry.SCHEDULE_REGISTRY.pop, "cleanup", None)
        registry.scheduled("0 1 * * *")(job_in("apps.billing.tasks"))
        # Importing the same module again (the autoreloader) is fine.
        registry.scheduled("0 1 * * *")(job_in("apps.billing.tasks"))
        with self.assertRaisesMessage(ImproperlyConfigured, "apps.billing.tasks"):
            registry.scheduled("0 2 * * *")(job_in("apps.reports.tasks"))
        self.assertEqual(registry.SCHEDULE_REGISTRY["cleanup"][0], "0 1 * * *")

    def test_the_task_is_left_as_it_was(self):
        from . import tasks

        self.assertIs(registry.SCHEDULE_REGISTRY[NAME][1], tasks.prune_task_results)


class AdminTest(TestCase):
    def setUp(self):
        registry.sync_schedules()
        self.client.force_login(
            get_user_model().objects.create_superuser(
                email="admin@example.com", password="s3cret-pass"
            )
        )

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_list_detail_and_schedule_now(self):
        schedule = CronSchedule.objects.get(name=NAME)
        for url in (
            "/admin/cron/cronschedule/",
            f"/admin/cron/cronschedule/{schedule.pk}/change/",
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.post(f"/admin/cron/cronschedule/{schedule.pk}/schedule-now/")
        self.assertEqual(DBTaskResult.objects.count(), 1)
        self.assertEqual(CronRun.objects.count(), 1)


class CronListNameTest(TestCase):
    def test_the_list_shows_the_module_and_the_function(self):
        registry.sync_schedules()
        self.client.force_login(
            get_user_model().objects.create_superuser(
                email="admin3@example.com", password="s3cret-pass"
            )
        )
        page = self.client.get("/admin/cron/cronschedule/")
        self.assertContains(page, "modules.cron.tasks.prune_task_results")

    def test_a_job_no_longer_in_code_keeps_its_name(self):
        gone = CronSchedule.objects.create(name="old_job")
        admin_ = CronScheduleAdmin(CronSchedule, admin.site)
        self.assertEqual(admin_.job(gone), "old_job")


class TaskResultAdminTest(TestCase):
    def test_a_failed_run_page_shows_the_cron_job_and_the_traceback(self):
        registry.sync_schedules()
        schedule = CronSchedule.objects.get(name=NAME)
        result = DBTaskResult.objects.create(
            status="FAILED",
            args_kwargs={"args": [], "kwargs": {}},
            task_path="modules.cron.tasks.prune_task_results",
            queue_name="scheduled_tasks",
            backend_name="default",
            exception_class_path="builtins.RuntimeError",
            traceback="Traceback...\nRuntimeError: boom",
        )
        CronRun.objects.create(schedule=schedule, task_result_id=result.id)
        self.client.force_login(
            get_user_model().objects.create_superuser(
                email="admin2@example.com", password="s3cret-pass"
            )
        )
        base = "/admin/django_tasks_database/dbtaskresult/"
        self.assertEqual(self.client.get(base).status_code, 200)
        page = self.client.get(f"{base}{result.pk}/change/")
        self.assertContains(page, "RuntimeError: boom")
        self.assertContains(page, "FAILED")
        self.assertContains(page, f"/cron/cronschedule/{schedule.pk}/change/")

        # Failed: the Failure section is open. Any other status: collapsed.
        def failure_section(page):
            html = page.content.decode()
            end = html.index("Failure</h2>")
            return html[html.rindex("<fieldset", 0, end) : end]

        section = failure_section(page)
        self.assertNotIn("collapse", section)
        self.assertNotIn("<details>", section)
        DBTaskResult.objects.filter(pk=result.pk).update(status="SUCCESSFUL")
        section = failure_section(self.client.get(f"{base}{result.pk}/change/"))
        self.assertIn("collapse", section)
        self.assertIn("<details>", section)


@override_settings(ALLOWED_HOSTS=["testserver"])
class ScheduleNowSafetyTest(TestCase):
    def setUp(self):
        registry.sync_schedules()
        self.schedule = CronSchedule.objects.get(name=NAME)
        self.url = f"/admin/cron/cronschedule/{self.schedule.pk}/schedule-now/"

    def staff(self, *codenames):
        from django.contrib.auth.models import Permission

        user = get_user_model().objects.create_user(
            email=f"staff{len(codenames)}@example.com",
            password="s3cret-pass",
            is_staff=True,
        )
        user.user_permissions.set(Permission.objects.filter(codename__in=codenames))
        return user

    def test_a_get_never_runs_a_job(self):
        self.client.force_login(self.staff("view_cronschedule", "change_cronschedule"))
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(DBTaskResult.objects.count(), 0)

    def test_a_post_without_the_csrf_token_is_refused(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff("view_cronschedule", "change_cronschedule"))
        self.assertEqual(client.post(self.url).status_code, 403)
        self.assertEqual(DBTaskResult.objects.count(), 0)

    def test_someone_who_can_only_view_cannot_run_it(self):
        self.client.force_login(self.staff("view_cronschedule"))
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertEqual(DBTaskResult.objects.count(), 0)

    def test_the_list_actions_need_the_change_permission(self):
        self.client.force_login(self.staff("view_cronschedule"))
        page = self.client.get("/admin/cron/cronschedule/")
        for action in ("action_schedule_now", "action_enable", "action_disable"):
            self.assertNotContains(page, f'value="{action}"')
        self.client.force_login(self.staff("view_cronschedule", "change_cronschedule"))
        page = self.client.get("/admin/cron/cronschedule/")
        self.assertContains(page, 'value="action_schedule_now"')

    def test_someone_who_can_change_runs_it_with_a_post(self):
        self.client.force_login(self.staff("view_cronschedule", "change_cronschedule"))
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.assertEqual(DBTaskResult.objects.count(), 1)

    def test_the_button_is_a_post_form_with_the_token(self):
        self.client.force_login(self.staff("view_cronschedule", "change_cronschedule"))
        page = self.client.get(f"/admin/cron/cronschedule/{self.schedule.pk}/change/")
        self.assertContains(page, f'action="{self.url}"')
        self.assertContains(page, "csrfmiddlewaretoken")


@skipUnless(connection.vendor == "postgresql", "advisory locks are Postgres only")
class SchedulerLockTest(TestCase):
    def setUp(self):
        self.addCleanup(self.release)

    def release(self):
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock_all()")

    def other_session(self):
        import psycopg

        db = connection.settings_dict
        return psycopg.connect(
            host=db["HOST"],
            port=db["PORT"],
            user=db["USER"],
            password=db["PASSWORD"],
            dbname=db["NAME"],
            autocommit=True,
        )

    def test_it_knows_whether_it_holds_the_lock(self):
        self.assertFalse(registry._holds_lock())
        self.assertTrue(registry._try_acquire_lock())
        self.assertTrue(registry._holds_lock())

    def test_a_lock_lost_to_a_new_session_is_noticed(self):
        registry._try_acquire_lock()
        self.release()  # what a dropped and re-opened connection looks like
        self.assertFalse(registry._holds_lock())

    def test_only_one_session_gets_the_lock(self):
        other = self.other_session()
        self.addCleanup(other.close)
        other.execute("SELECT pg_advisory_lock(%s)", [registry.SCHEDULER_LOCK_KEY])
        self.assertFalse(registry._try_acquire_lock())
        self.assertFalse(registry._holds_lock())
        other.execute("SELECT pg_advisory_unlock_all()")
        self.assertTrue(registry._try_acquire_lock())


def stop(*args, **kwargs):
    """What `kill <pid>` does to a running scheduler."""
    os.kill(os.getpid(), signal.SIGTERM)


class SchedulerLoopTest(SimpleTestCase):
    """run_scheduler with the lock, the clock and the tick faked."""

    def setUp(self):
        for signum in (signal.SIGTERM, signal.SIGINT):
            self.addCleanup(signal.signal, signum, signal.getsignal(signum))

    def run_scheduler(self, acquire=(True,), holds=(True,), tick=stop, sleep=None):
        noon = timezone.datetime(2026, 1, 1, 12, 0, 15, 500_000, tzinfo=UTC)
        with (
            patch.object(registry, "_try_acquire_lock", side_effect=acquire),
            patch.object(registry, "_holds_lock", side_effect=holds),
            patch.object(registry, "sync_schedules", return_value=(0, 0)) as sync,
            patch.object(registry, "cron_tick", side_effect=tick) as cron_tick,
            patch.object(registry.time, "sleep", side_effect=sleep) as sleep,
            patch.object(registry.timezone, "now", return_value=noon),
        ):
            registry.run_scheduler()
        return sync, cron_tick, sleep

    def test_ticks_at_the_top_of_the_next_minute(self):
        sync, cron_tick, sleep = self.run_scheduler()
        sync.assert_called_once()
        cron_tick.assert_called_once()
        sleep.assert_called_once_with(44.5)  # From 12:00:15.5 to 12:01:00.

    def test_waits_in_standby_until_it_gets_the_lock(self):
        sync, cron_tick, sleep = self.run_scheduler(acquire=(False, False, True))
        self.assertEqual(
            sleep.call_args_list[:2], [call(registry.STANDBY_RETRY_SECONDS)] * 2
        )
        sync.assert_called_once()
        cron_tick.assert_called_once()

    def test_a_lost_lock_goes_back_to_standby(self):
        # Lost before the first tick: it takes the lock again and syncs again.
        sync, cron_tick, _ = self.run_scheduler(
            acquire=(True, True), holds=(False, True)
        )
        self.assertEqual(sync.call_count, 2)
        cron_tick.assert_called_once()

    def test_a_failing_tick_does_not_stop_it(self):
        ticks = []

        def fail_then_stop():
            ticks.append(1)
            if len(ticks) == 1:
                raise RuntimeError("boom")
            stop()

        self.run_scheduler(holds=(True, True), tick=fail_then_stop)
        self.assertEqual(len(ticks), 2)

    def test_stopped_in_standby_it_never_syncs(self):
        sync, cron_tick, _ = self.run_scheduler(acquire=(False,), sleep=stop)
        sync.assert_not_called()
        cron_tick.assert_not_called()

    def test_stopped_while_waiting_for_the_minute_it_does_not_tick(self):
        with patch.object(registry, "_holds_lock") as holds:
            _, cron_tick, _ = self.run_scheduler(sleep=stop)
        holds.assert_not_called()
        cron_tick.assert_not_called()
