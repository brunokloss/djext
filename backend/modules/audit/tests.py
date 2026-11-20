import re
from contextlib import contextmanager
from datetime import timedelta
from io import StringIO
from unittest import skipUnless
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import get_user_model, login
from django.contrib.auth.models import AnonymousUser, Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.db import ProgrammingError, connection, transaction
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils.crypto import salted_hmac
from django.utils.functional import SimpleLazyObject
from django.utils.timezone import now
from post_office.models import Email, EmailTemplate

from modules.audit import log, signals
from modules.audit.admin import CHANGED
from modules.audit.checks import undecided_models
from modules.audit.middleware import current_request
from modules.audit.models import AuditLog
from modules.signals.signals import action_performed

User = get_user_model()


@contextmanager
def acting_as(user, request_id="abcd1234"):
    """What AuditMiddleware does for a request made by `user`."""
    request = RequestFactory().get("/")
    request.user = user
    request.request_id = request_id
    token = current_request.set(request)
    try:
        yield
    finally:
        current_request.reset(token)


def logs_of(obj):
    return AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(obj), object_id=str(obj.pk)
    )


def subjects(entry):
    return set(entry.subjects)


# Skipped when the folder stays but the app is out of INSTALLED_APPS.
@skipUnless(apps.is_installed("modules.audit"), "audit is off")
class AuditTest(TestCase):
    def test_create(self):
        user = User.objects.create_user(email="ana@example.com", password="password")
        entry = logs_of(user).get()
        self.assertEqual(entry.action, AuditLog.Action.CREATE)
        self.assertEqual(entry.object_repr, "ana@example.com")
        self.assertIsNone(entry.old_values)
        self.assertEqual(entry.new_values["email"], "ana@example.com")
        self.assertIsNone(entry.actor)
        self.assertEqual(subjects(entry), {f"authd.user:{user.pk}"})

    def test_masks_the_password(self):
        user = User.objects.create_user(email="ana@example.com", password="password")
        before = logs_of(user).get().new_values["password"]
        self.assertRegex(before, r"^pbkdf2….{4}$")
        user.set_password("another password")
        user.save()
        entry = logs_of(user).get(action="update")
        self.assertEqual(entry.old_values["password"], before)
        self.assertNotEqual(entry.new_values["password"], before)

    def test_update_logs_the_whole_row(self):
        user = User.objects.create_user(email="ana@example.com")
        user.first_name = "Ana"
        user.save()
        user.save()  # Nothing changed: no log.
        entry = logs_of(user).get(action="update")
        self.assertEqual(entry.old_values["first_name"], "")
        self.assertEqual(entry.new_values["first_name"], "Ana")
        self.assertEqual(entry.new_values["email"], "ana@example.com")
        self.assertNotIn("last_login", entry.new_values)  # Excluded.
        self.assertNotIn("updated_at", entry.new_values)  # Excluded.

    def test_phone_number_change(self):
        user = User.objects.create_user(email="ana@example.com")
        user.phone_number = "+5511912345678"
        user.save()
        entry = logs_of(user).get(action="update")
        self.assertEqual(entry.old_values["phone_number"], "")
        self.assertEqual(entry.new_values["phone_number"], "+5511912345678")

    def test_excluded_fields_alone_cost_no_query(self):
        user = User.objects.create_user(email="ana@example.com")
        user.last_login = user.date_joined
        with self.assertNumQueries(1):  # Only the UPDATE.
            user.save(update_fields=["last_login"])
        self.assertFalse(logs_of(user).filter(action="update").exists())

    def test_many_to_many(self):
        user = User.objects.create_user(email="ana@example.com")
        group = Group.objects.create(name="staff")
        user.groups.add(group)
        user.groups.clear()
        payloads = [e.new_values for e in logs_of(user).filter(action="m2m")]
        common = {"field": "groups", "related_model": "Group"}
        self.assertCountEqual(
            payloads,
            [
                {**common, "operation": "add", "related_ids": [str(group.pk)]},
                {**common, "operation": "clear", "related_ids": []},
            ],
        )

    def test_actor_and_request_id_from_a_request(self):
        admin = User.objects.create_superuser(email="admin@example.com")
        self.client.force_login(admin)
        headers = {"X-Request-Id": "from-next-1234"}
        url = reverse("admin:auth_group_add")
        self.client.post(url, {"name": "staff"}, headers=headers)
        entry = logs_of(Group.objects.get(name="staff")).get()
        self.assertEqual(entry.actor, admin)
        self.assertEqual(entry.ip_address, "127.0.0.1")
        session_key = self.client.session.session_key
        self.assertEqual(
            entry.session_hash,
            salted_hmac(admin.username, session_key, algorithm="sha256").hexdigest(),
        )
        # Salted with the user: the same session key, another user, another hash.
        other = User.objects.create_user(email="other@example.com")
        self.assertNotEqual(
            entry.session_hash,
            salted_hmac(other.username, session_key, algorithm="sha256").hexdigest(),
        )
        self.assertEqual(str(entry), f"create Group {entry.object_id} by {admin}")
        if apps.is_installed("modules.log"):
            self.assertEqual(entry.request_id, "from-next-1234")

    def test_rollback_drops_the_log(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            User.objects.create_user(email="ana@example.com")
            raise RuntimeError
        self.assertFalse(AuditLog.objects.exists())

    def test_other_models_keep_fast_deletes(self):
        Session.objects.create(session_key="x" * 32, session_data="", expire_date=now())
        with self.assertNumQueries(1):  # One DELETE, no SELECT of each row.
            Session.objects.all().delete()

    def test_login_and_logout_share_the_session_hash(self):
        ana = User.objects.create_user(email="ana@example.com", password="password")
        self.client.post(
            "/api/auth/login",
            {"email": "ana@example.com", "password": "password"},
            content_type="application/json",
        )
        group = Group.objects.create(name="staff")
        with acting_as(ana):
            ana.groups.add(group)
        self.client.post("/api/auth/logout")

        login = logs_of(ana).get(action="login")
        logout = logs_of(ana).get(action="logout")
        self.assertEqual(login.actor, ana)
        self.assertEqual(subjects(login), {f"authd.user:{ana.pk}"})
        self.assertEqual(login.new_values["method"], "password")
        self.assertIn("EmailBackend", login.new_values["backend"])
        self.assertEqual(len(login.session_hash), 64)
        self.assertEqual(logout.session_hash, login.session_hash)

    def test_login_with_a_forwarded_for_that_is_not_an_ip(self):
        # Anyone can send the header: the login must not fail on Postgres's inet.
        ana = User.objects.create_user(email="ana@example.com", password="password")
        response = self.client.post(
            "/api/auth/login",
            {"email": "ana@example.com", "password": "password"},
            content_type="application/json",
            headers={"X-Forwarded-For": "not-an-ip"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(logs_of(ana).get(action="login").ip_address)

    def test_login_with_a_provider(self):
        # What modules/oauth does, without depending on it (the contract is in
        # modules/signals/signals.py; oauth's tests check its side).
        ana = User.objects.create_user(email="ana@example.com")
        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.auth_provider = "google"
        login(request, ana, backend=settings.AUTHENTICATION_BACKENDS[0])
        entry = logs_of(ana).get(action="login")
        self.assertEqual(entry.new_values["method"], "google")

    def test_failed_login(self):
        self.client.post(
            "/api/auth/login",
            {"email": " Ana@Example.com ", "password": "wrong"},
            content_type="application/json",
        )
        entry = AuditLog.objects.get(action="login_failed")
        self.assertEqual(entry.object_repr, "ana@example.com")
        self.assertEqual(
            entry.new_values, {"method": "password", "reason": "invalid_credentials"}
        )
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.subjects, [])

    @override_settings(AUTH_LOGIN_THROTTLE_EMAIL="1/15min")
    def test_throttled_login_writes_nothing(self):
        # Attackers hammer it: no row per try.
        def login():
            return self.client.post(
                "/api/auth/login",
                {"email": "ana@example.com", "password": "wrong"},
                content_type="application/json",
            )

        login()
        count = AuditLog.objects.count()
        self.assertEqual(login().status_code, 429)
        self.assertEqual(AuditLog.objects.count(), count)

    def test_search_by_the_actor_uuid(self):
        ana = User.objects.create_user(email="ana@example.com", password="password")
        with acting_as(ana):
            Group.objects.create(name="Staff")
        admin = User.objects.create_superuser(email="admin@example.com")
        self.client.force_login(admin)
        url = reverse("admin:audit_auditlog_changelist")
        found = self.client.get(url, {"q": ana.username})
        self.assertContains(found, "Staff")

    def test_failed_login_page_shows_the_email_typed(self):
        self.client.post(
            "/api/auth/login",
            {"email": "ghost@example.com", "password": "wrong"},
            content_type="application/json",
        )
        entry = AuditLog.objects.get(action="login_failed")
        admin = User.objects.create_superuser(email="admin@example.com")
        self.client.force_login(admin)
        response = self.client.get(
            reverse("admin:audit_auditlog_change", args=[entry.pk])
        )
        self.assertContains(response, "ghost@example.com")
        self.assertEqual(str(entry), "login_failed User ghost@example.com by -")

    def test_deleting_a_user_keeps_their_logins(self):
        ana = User.objects.create_user(email="ana@example.com", password="password")
        self.client.login(email="ana@example.com", password="password")
        self.client.login(email="ana@example.com", password="wrong")
        ana.delete()
        self.assertEqual(AuditLog.objects.filter(action__startswith="login").count(), 2)

    def test_logs_are_never_changed(self):
        user = User.objects.create_user(email="ana@example.com")
        entry = logs_of(user).get()
        with self.assertRaises(ValueError):
            entry.save()

    def test_deleting_a_subject_keeps_its_logs(self):
        admin = User.objects.create_superuser(email="admin@example.com")
        ana = User.objects.create_user(email="ana@example.com")
        with acting_as(admin):
            ana.first_name = "Ana"
            ana.save()
        ana_pk = ana.pk
        with acting_as(admin):
            ana.delete()

        entries = AuditLog.objects.filter(subject_1=f"authd.user:{ana_pk}")
        self.assertEqual(
            sorted(entries.values_list("action", flat=True)),
            ["create", "delete", "update"],
        )
        entry = entries.get(action="delete")
        self.assertEqual(entry.old_values["email"], "ana@example.com")
        self.assertEqual(entry.actor, admin)

    def test_deleting_an_actor_keeps_what_they_did_to_others(self):
        admin = User.objects.create_superuser(email="admin@example.com")
        ana = User.objects.create_user(email="ana@example.com")
        with acting_as(admin):
            ana.first_name = "Ana"
            ana.save()
        admin.delete()
        entry = logs_of(ana).get(action="update")
        self.assertIsNone(entry.actor)  # The row is gone (SET_NULL).

    def test_deleting_your_own_account(self):
        ana = User.objects.create_user(email="ana@example.com")
        with acting_as(ana):
            ana.delete()
        entry = AuditLog.objects.get(action="delete")
        self.assertIsNone(entry.actor)


class ForgetTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="root@example.com", password="x"
        )
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.bia = User.objects.create_user(email="bia@example.com", password="x")

    def request(self, user):
        request = RequestFactory().post(
            "/", HTTP_USER_AGENT="Firefox", REMOTE_ADDR="10.0.0.1"
        )
        request.user = user
        return request

    def anonymize(self):
        # What User.anonymize() does, for the logs: the action, then forget.
        action_performed.send(
            None,
            request=self.request(self.admin),
            name="user.anonymize",
            target=self.ana,
        )
        log.forget(self.ana.pk, self.ana.email)

    def test_masks_their_logs(self):
        self.ana.first_name = "Ana"
        self.ana.save()
        action_performed.send(
            None, request=self.request(self.ana), name="x.y", values={"a": "1"}
        )
        self.anonymize()
        logs = AuditLog.objects.filter(subject_1=log.subject_key(User, self.ana.pk))
        # The first_name change.
        update = logs.filter(action=AuditLog.Action.UPDATE).order_by("pk").first()
        self.assertEqual(update.old_values["first_name"], "***")
        self.assertEqual(update.new_values["first_name"], "***")
        self.assertEqual(update.object_repr, "***")
        mine = logs.get(name="x.y")
        self.assertEqual(mine.new_values, {"a": "***"})
        # What they did, from where: forgotten. Who did it stays.
        self.assertEqual((mine.ip_address, mine.user_agent), (None, ""))
        self.assertEqual(mine.actor, self.ana)
        done = logs.get(name="user.anonymize")
        self.assertEqual((done.actor, done.object_id), (self.admin, str(self.ana.pk)))
        # The admin's IP is the admin's.
        self.assertEqual(done.ip_address, "10.0.0.1")
        self.assertFalse(logs.exclude(object_repr="***").exists())

    def test_masks_failed_logins_with_their_email(self):
        for email in ("ANA@example.com", "bia@example.com"):
            self.client.post(
                "/api/auth/login",
                {"email": email, "password": "wrong"},
                content_type="application/json",
            )
        self.anonymize()
        failed = AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED)
        self.assertCountEqual(
            failed.values_list("object_repr", flat=True), ["***", "bia@example.com"]
        )

    def test_keeps_the_others(self):
        self.bia.first_name = "Bia"
        self.bia.save()
        self.anonymize()
        update = AuditLog.objects.get(
            action=AuditLog.Action.UPDATE, object_id=str(self.bia.pk)
        )
        self.assertEqual(update.new_values["first_name"], "Bia")
        self.assertEqual(update.object_repr, "bia@example.com")


@skipUnless(apps.is_installed("modules.audit"), "audit is off")
class AuditAdminTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@example.com")
        self.client.force_login(self.admin)
        self.ana = User.objects.create_user(email="ana@example.com")

    def test_history_page_shows_the_audit_log(self):
        with acting_as(self.admin):
            self.ana.first_name = "Ana"
            self.ana.save()
        url = reverse("admin:authd_user_history", args=[self.ana.pk])
        response = self.client.get(url)
        self.assertTemplateUsed(response, "audit/object_history.html")
        self.assertContains(response, ">first_name</th>")
        self.assertContains(response, CHANGED)  # The first_name row.
        self.assertContains(response, "admin@example.com")

    def test_history_page_filters(self):
        with acting_as(self.admin):
            self.ana.first_name = "Ana"
            self.ana.save()
        url = reverse("admin:authd_user_history", args=[self.ana.pk])
        response = self.client.get(url, {"action": "update"})
        self.assertContains(response, "<td>Update</td>")
        self.assertNotContains(response, "<td>Create</td>")
        response = self.client.get(url, {"action": ["create", "update"]})
        self.assertContains(response, "<td>Update</td>")
        self.assertContains(response, "<td>Create</td>")
        response = self.client.get(url, {"actor": self.admin.pk})
        self.assertNotContains(response, "<td>Create</td>")  # No actor there.

    def test_history_page_checks_every_action_at_first(self):
        url = reverse("admin:authd_user_history", args=[self.ana.pk])
        response = self.client.get(url)
        self.assertContains(response, " selected>", count=len(AuditLog.Action))

    def test_history_page_shows_only_changes(self):
        with acting_as(self.admin):
            self.ana.first_name = "Ana"
            self.ana.save()
        url = reverse("admin:authd_user_history", args=[self.ana.pk])
        response = self.client.get(url, {"action": "update", "changed": "1"})
        self.assertContains(response, ">first_name</th>")
        self.assertNotContains(response, ">email</th>")

    def test_history_page_is_paginated(self):
        for i in range(100):  # 101 logs with the create.
            self.ana.first_name = f"Ana {i}"
            self.ana.save()
        url = reverse("admin:authd_user_history", args=[self.ana.pk])
        # Links to each log's page, not the sidebar's to the list.
        log_link = re.compile(
            re.escape(reverse("admin:audit_auditlog_changelist")) + r"\d+/change/"
        )
        response = self.client.get(url)
        self.assertEqual(len(log_link.findall(response.text)), 100)
        self.assertContains(response, 'href="?p=2"')
        self.assertContains(response, "101 entries")
        response = self.client.get(url, {"p": 2})
        self.assertEqual(len(log_link.findall(response.text)), 1)

    def test_log_page_groups_the_session(self):
        url = reverse("admin:auth_group_add")
        self.client.post(url, {"name": "staff"})
        self.client.post(url, {"name": "sales"})
        entry = AuditLog.objects.filter(action="create").first()
        response = self.client.get(
            reverse("admin:audit_auditlog_change", args=[entry.pk])
        )
        self.assertContains(response, f"session_hash={entry.session_hash}")
        self.assertContains(response, "(2 logs)")
        changelist = reverse("admin:audit_auditlog_changelist")
        response = self.client.get(changelist, {"session_hash": entry.session_hash})
        self.assertEqual(response.context["cl"].result_count, 2)

    def test_m2m_shows_the_permission_tag(self):
        perm = Permission.objects.get(codename="add_group")
        self.ana.user_permissions.add(perm)
        entry = logs_of(self.ana).get(action="m2m")
        response = self.client.get(
            reverse("admin:audit_auditlog_change", args=[entry.pk])
        )
        self.assertContains(response, "<code>auth.add_group</code>")

    def test_log_page_links_what_still_exists(self):
        group = Group.objects.create(name="staff")
        self.ana.groups.add(group)
        entry = logs_of(self.ana).get(action="m2m")
        url = reverse("admin:audit_auditlog_change", args=[entry.pk])
        user_url = reverse("admin:authd_user_change", args=[self.ana.pk])

        response = self.client.get(url)
        self.assertContains(response, f'href="{user_url}"')  # Object and subject.
        self.assertContains(response, "staff")

        group.delete()
        response = self.client.get(url)
        self.assertContains(response, "❌")


@skipUnless(apps.is_installed("modules.audit"), "audit is off")
@override_settings(
    # The admin's own log stands in for a model with a user and a tenant.
    AUDIT_MODELS={"admin.LogEntry": {"subjects": ["user", "content_type"]}}
)
class SeveralSubjectsTest(TestCase):
    def setUp(self):
        log.load()
        signals.connect()
        self.addCleanup(log.load)  # Back to the project's AUDIT_MODELS.
        self.ana = User.objects.create_user(email="ana@example.com")
        self.group_type = ContentType.objects.get_for_model(Group)
        self.entry = LogEntry.objects.create(
            user=self.ana,
            content_type=self.group_type,
            object_id="1",
            object_repr="staff",
            action_flag=ADDITION,
        )

    def test_names_every_subject(self):
        entry = logs_of(self.entry).get()
        self.assertEqual(
            subjects(entry),
            {
                f"authd.user:{self.ana.pk}",
                f"contenttypes.contenttype:{self.group_type.pk}",
            },
        )

    def test_deleting_a_subject_keeps_the_log(self):
        self.ana.delete()  # Deletes the LogEntry too, by cascade.
        self.assertEqual(
            sorted(logs_of(self.entry).values_list("action", flat=True)),
            ["create", "delete"],
        )


@skipUnless(apps.is_installed("modules.audit"), "audit is off")
@override_settings(
    # Two foreign keys deep: an email's template is a translation of another
    # one, which stands in for the owner.
    AUDIT_MODELS={"post_office.Email": {"subjects": ["template__default_template"]}}
)
class NestedSubjectTest(TestCase):
    def setUp(self):
        log.load()
        signals.connect()
        self.addCleanup(log.load)  # Back to the project's AUDIT_MODELS.
        self.base = EmailTemplate.objects.create(name="welcome")
        self.translation = EmailTemplate.objects.create(
            language="pt", default_template=self.base
        )

    def email(self, template):
        return Email.objects.create(
            from_email="a@example.com", to=["b@example.com"], template=template
        )

    def test_follows_the_path(self):
        email = self.email(self.translation)
        self.assertEqual(
            subjects(logs_of(email).get()),
            {f"post_office.emailtemplate:{self.base.pk}"},
        )

    def test_a_missing_link_is_no_subject(self):
        self.assertEqual(subjects(logs_of(self.email(None)).get()), set())


@skipUnless(apps.is_installed("modules.audit"), "audit is off")
class PurgeTest(TestCase):
    def make(self, days_old):
        # Insert it already old: backdating later is an UPDATE, which the
        # Postgres trigger refuses.
        field = AuditLog._meta.get_field("created_at")
        with patch.object(field, "auto_now_add", False):
            return AuditLog.objects.create(
                created_at=now() - timedelta(days=days_old),
                action=AuditLog.Action.LOGIN,
                content_type=ContentType.objects.get_for_model(User),
                object_id="1",
            )

    @override_settings(AUDIT_RETENTION_DAYS=30)
    def test_deletes_only_the_older_ones(self):
        old = self.make(31)
        recent = self.make(29)
        call_command("audit_purge", stdout=StringIO())
        self.assertFalse(AuditLog.objects.filter(pk=old.pk).exists())
        self.assertTrue(AuditLog.objects.filter(pk=recent.pk).exists())

    @override_settings(AUDIT_RETENTION_DAYS=0)
    def test_zero_keeps_everything(self):
        old = self.make(10_000)
        call_command("audit_purge", stdout=StringIO())
        self.assertTrue(AuditLog.objects.filter(pk=old.pk).exists())


@skipUnless(
    apps.is_installed("modules.audit") and connection.vendor == "postgresql",
    "the trigger is Postgres only",
)
class ImmutableTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="ana@example.com", password="password"
        )
        self.entry = AuditLog.objects.create(
            action=AuditLog.Action.UPDATE,
            content_type=ContentType.objects.get_for_model(User),
            object_id=str(self.user.pk),
            object_repr="ana@example.com",
            new_values={"first_name": "Ana"},
            actor=self.user,
            ip_address="10.0.0.1",
            user_agent="Firefox",
            session_hash="abc",
        )

    def update(self, **fields):
        with transaction.atomic():
            return AuditLog.objects.filter(pk=self.entry.pk).update(**fields)

    def test_what_was_logged_cannot_change(self):
        for fields in (
            {"action": AuditLog.Action.DELETE},
            {"new_values": {"email": "x@example.com"}},
            {"object_repr": "someone else"},
            {"name": "auth.unlock_login"},
            {"created_at": now()},
            {"ip_address": "10.0.0.2"},
        ):
            with self.subTest(fields), self.assertRaises(ProgrammingError):
                self.update(**fields)

    def test_the_actor_can_be_forgotten_but_not_set(self):
        self.update(actor=None, ip_address=None, user_agent="", session_hash="")
        with self.assertRaises(ProgrammingError):
            self.update(actor=self.user)

    def test_can_be_masked_but_not_unmasked(self):
        self.update(object_repr="***", new_values={"first_name": "***"})
        for fields in (
            {"new_values": {"first_name": "Ana"}},
            {"new_values": {"last_name": "***"}},
            {"object_repr": "ana@example.com"},
        ):
            with self.subTest(fields), self.assertRaises(ProgrammingError):
                self.update(**fields)

    def test_deleting_the_user_still_works(self):
        self.user.delete()


# What the settings decide about other apps' models (cron's task results...):
# the tests below only change the decision about Group.
OTHERS = {k: v for k, v in settings.AUDIT_MODELS.items() if k != "auth.Group"}


@skipUnless(apps.is_installed("modules.audit"), "audit is off")
class UndecidedModelsTest(TestCase):
    def setUp(self):
        # log.load() reads settings and the models' Audit classes: put it back.
        self.addCleanup(log.load)

    def warned(self):
        return {w.obj for w in undecided_models(None)}

    def test_every_model_here_has_a_decision(self):
        self.assertEqual(self.warned(), set())

    @override_settings(AUDIT_MODELS=OTHERS)
    def test_a_model_nobody_decided_about_is_warned(self):
        log.load()
        self.assertEqual(self.warned(), {Group})
        [warning] = undecided_models(None)
        self.assertEqual(warning.id, "audit.W001")

    @override_settings(AUDIT_MODELS={**OTHERS, "auth.Group": {"skip": True}})
    def test_skip_in_the_settings_is_a_decision(self):
        log.load()
        self.assertEqual(self.warned(), set())
        self.assertNotIn(Group, log.AUDITED)

    def test_skip_on_the_model_is_a_decision(self):
        with patch.object(User.Audit, "skip", True, create=True):
            log.load()
            self.assertEqual(self.warned(), set())
            self.assertNotIn(User, log.AUDITED)


class ActionTests(TestCase):
    def send(self, request, **kwargs):
        action_performed.send(
            None, request=request, name="cache.clear", values={"entries": 3}, **kwargs
        )
        return AuditLog.objects.get(action=AuditLog.Action.ACTION)

    def test_action_performed_is_logged(self):
        user = User.objects.create_user(email="root@example.com")
        request = RequestFactory().post("/x")
        request.user = user
        log = self.send(request)
        self.assertEqual(log.name, "cache.clear")
        self.assertEqual(log.new_values, {"entries": 3})
        # Done to nothing: the object and subject are who did it.
        self.assertEqual((log.object_id, log.object_repr), (str(user.pk), str(user)))
        self.assertEqual(log.subjects, [f"authd.user:{user.pk}"])

    def test_the_target_is_the_object_and_the_subject(self):
        admin = User.objects.create_user(email="root@example.com")
        ana = User.objects.create_user(email="ana@example.com")
        request = RequestFactory().post("/x")
        request.user = admin
        log = self.send(request, target=ana)
        self.assertEqual(
            (log.content_type.model_class(), log.object_id, log.object_repr),
            (User, str(ana.pk), str(ana)),
        )
        # In ana's history; who asked is the actor.
        self.assertEqual(log.subjects, [f"authd.user:{ana.pk}"])
        self.assertEqual(log.actor, admin)

    def test_the_target_may_be_the_lazy_request_user(self):
        ana = User.objects.create_user(email="ana@example.com")
        request = RequestFactory().post("/x")
        request.user = SimpleLazyObject(lambda: ana)
        log = self.send(request, target=request.user)
        self.assertEqual(log.subjects, [f"authd.user:{ana.pk}"])

    def test_anonymous_has_no_user(self):
        request = RequestFactory().post("/x")
        request.user = AnonymousUser()
        log = self.send(request)
        self.assertEqual(log.object_id, "")
        self.assertIsNone(log.subject_1)

    def test_no_request_does_not_break_the_sender(self):
        action_performed.send(None, name="cache.clear")
        self.assertEqual(AuditLog.objects.filter(action="action").count(), 1)
