import json
import uuid
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.authd.api.users import ME_CACHE
from apps.authd.models import new_username
from modules.cache import decorators as cache_decorators

User = get_user_model()


class UserTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="ana@example.com", password="s3cret-pass"
        )

    def test_custom_user_model(self):
        self.assertEqual(User._meta.label, "authd.User")

    def test_username_is_a_uuid7(self):
        self.assertEqual(uuid.UUID(self.user.username).version, 7)

    def test_login_with_email(self):
        # Login forms send the email as `username`.
        self.assertEqual(
            authenticate(username="ANA@example.com", password="s3cret-pass"),
            self.user,
        )
        self.assertIsNone(authenticate(username="ana@example.com", password="nope"))
        self.assertIsNone(authenticate(username="bob@example.com", password="x"))
        self.assertIsNone(
            authenticate(username=self.user.username, password="s3cret-pass")
        )

    def test_email_is_normalized(self):
        user = User.objects.create_user(email="  Bob@Example.COM ", password="x")
        self.assertEqual(user.email, "bob@example.com")
        self.assertEqual(authenticate(username=" BOB@example.com", password="x"), user)

    def test_email_is_unique_whatever_the_case(self):
        # Even when it skips normalize_email, like a raw update.
        user = User.objects.create_user(email="bob@example.com", password="x")
        with self.assertRaises(IntegrityError):
            User.objects.filter(pk=user.pk).update(email="ANA@example.com")

    def test_createsuperuser(self):
        # What `make superuser` does: pass a fresh UUID as the username.
        call_command(
            "createsuperuser",
            username=new_username(),
            email="root@example.com",
            interactive=False,
            verbosity=0,
        )
        admin = User.objects.get(email="root@example.com")
        self.assertTrue(admin.is_superuser)
        self.assertEqual(uuid.UUID(admin.username).version, 7)

    def test_admin_login_and_add_user(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            f"{reverse('admin:login')}?next={reverse('admin:index')}",
            {"username": "ana@example.com", "password": "s3cret-pass"},
        )
        self.assertRedirects(response, reverse("admin:index"))

        response = self.client.post(
            reverse("admin:authd_user_add"),
            {
                "email": "bob@example.com",
                "usable_password": "true",
                "password1": "an0ther-pass!",
                "password2": "an0ther-pass!",
            },
        )
        self.assertEqual(response.status_code, 302)
        bob = User.objects.get(email="bob@example.com")
        self.assertEqual(uuid.UUID(bob.username).version, 7)

    def test_admin_cannot_change_the_username(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        url = reverse("admin:authd_user_change", args=[self.user.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        original = self.user.username
        response = self.client.post(
            url,
            {
                "username": "hacked",
                "email": "ana@example.com",
                "is_active": "on",
                "is_staff": "on",
                "is_superuser": "on",
                # The sessions, bearer key and keyset inlines, left as they are.
                "sessions-TOTAL_FORMS": "0",
                "sessions-INITIAL_FORMS": "0",
                "bearer_key-TOTAL_FORMS": "0",
                "bearer_key-INITIAL_FORMS": "0",
                "crypto-keyset-owner_type-owner_id-TOTAL_FORMS": "0",
                "crypto-keyset-owner_type-owner_id-INITIAL_FORMS": "0",
            },
        )
        self.assertEqual(response.status_code, 302)  # saved, not a form error
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, original)

    def test_short_name_falls_back_to_email(self):
        self.assertEqual(self.user.get_short_name(), "ana@example.com")
        self.user.first_name = "Ana"
        self.assertEqual(self.user.get_short_name(), "Ana")

    def test_updated_at_changes_on_save(self):
        before = self.user.updated_at
        self.user.first_name = "Ana"
        self.user.save()
        self.user.refresh_from_db()
        self.assertGreater(self.user.updated_at, before)

    def test_admin_shows_updated_at(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        url = reverse("admin:authd_user_change", args=[self.user.pk])
        self.assertContains(self.client.get(url), "Last updated")


class PhoneNumberTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@example.com", password="x"
        )
        self.ana = User.objects.create_user(
            email="ana@example.com", password="x", first_name="Ana"
        )
        self.client.force_login(self.admin)
        self.url = reverse("admin:authd_user_change", args=[self.ana.pk])

    def change(self, phone_number):
        return self.client.post(
            self.url,
            {
                "email": "ana@example.com",
                "first_name": "Ana",
                "phone_number": phone_number,
                "is_active": "on",
                # The sessions, bearer key and keyset inlines, left as they are.
                "sessions-TOTAL_FORMS": "0",
                "sessions-INITIAL_FORMS": "0",
                "bearer_key-TOTAL_FORMS": "0",
                "bearer_key-INITIAL_FORMS": "0",
                "crypto-keyset-owner_type-owner_id-TOTAL_FORMS": "0",
                "crypto-keyset-owner_type-owner_id-INITIAL_FORMS": "0",
            },
        )

    def test_invalid_number_fails(self):
        response = self.change("123")
        self.assertEqual(response.status_code, 200)
        self.assertIn("phone_number", response.context["adminform"].form.errors)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.phone_number, "")

    def test_admin_saves_e164(self):
        # Without a country code it is PHONENUMBER_DEFAULT_REGION's (BR).
        self.assertEqual(self.change("(11) 91234-5678").status_code, 302)
        self.ana.refresh_from_db()
        self.assertEqual(str(self.ana.phone_number), "+5511912345678")
        self.assertEqual(self.change("+1 202 555 0123").status_code, 302)
        self.ana.refresh_from_db()
        self.assertEqual(str(self.ana.phone_number), "+12025550123")

    def test_admin_can_clear_it(self):
        self.ana.phone_number = "+5511912345678"
        self.ana.save()
        self.assertEqual(self.change("").status_code, 302)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.phone_number, "")

    def test_admin_add_form_takes_it(self):
        response = self.client.post(
            reverse("admin:authd_user_add"),
            {
                "email": "bob@example.com",
                "phone_number": "+5511912345678",
                "usable_password": "false",
            },
        )
        self.assertEqual(response.status_code, 302)
        bob = User.objects.get(email="bob@example.com")
        self.assertEqual(str(bob.phone_number), "+5511912345678")

    def test_admin_loads_the_widget(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn('class="intl-tel"', page)
        self.assertIn('data-initial-country="br"', page)
        self.assertIn("phone/vendor/intl-tel-input/js/intlTelInputWithUtils", page)
        self.assertIn("phone/js/phone_intl_tel.js", page)

    def test_admin_searches_by_phone(self):
        self.ana.phone_number = "+5511912345678"
        self.ana.save()
        response = self.client.get(
            reverse("admin:authd_user_changelist"), {"q": "+5511912345678"}
        )
        self.assertEqual(list(response.context["cl"].result_list), [self.ana])

    def test_me_returns_it(self):
        self.ana.phone_number = "+5511912345678"
        self.ana.save()
        self.client.force_login(self.ana)
        data = self.client.get("/api/users/me").json()
        self.assertEqual(data["phone_number"], "+5511912345678")


class UsersEndpointTest(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user(
            email="ana@example.com", password="x", first_name="Ana", last_name="Lima"
        )
        self.bob = User.objects.create_user(email="bob@example.com", password="x")
        self.root = User.objects.create_superuser(
            email="root@example.com", password="x"
        )

    def get(self, path):
        return self.client.get(f"/api/users/{path}")

    def test_requires_login(self):
        self.assertEqual(self.get("me").status_code, 401)
        self.assertEqual(self.get(self.ana.username).status_code, 401)

    def test_me(self):
        self.client.force_login(self.ana)
        response = self.get("me")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.pop("refreshed_at"))
        self.assertEqual(
            data,
            {
                "id": self.ana.username,
                "email": "ana@example.com",
                "first_name": "Ana",
                "last_name": "Lima",
                "full_name": "Ana Lima",
                "phone_number": "",
                "is_staff": False,
                "is_superuser": False,
                "groups": [],
                "permissions": [],
            },
        )

    def test_me_has_groups_and_permissions(self):
        group = Group.objects.create(name="sales")
        group.permissions.add(Permission.objects.get(codename="view_group"))
        self.ana.groups.add(group)
        self.ana.user_permissions.add(Permission.objects.get(codename="add_group"))
        self.client.force_login(self.ana)
        body = self.get("me").json()
        self.assertEqual(body["groups"], ["sales"])
        # Their own and their groups'.
        self.assertEqual(body["permissions"], ["auth.add_group", "auth.view_group"])

    def test_user_can_only_see_themselves(self):
        self.client.force_login(self.ana)
        me = self.get("me").json()
        own = self.get(self.ana.username).json()
        self.assertEqual(own, {k: me[k] for k in own})
        # Permissions only on /me.
        self.assertNotIn("permissions", own)
        self.assertEqual(self.get(self.bob.username).status_code, 404)

    def test_superuser_can_see_anyone(self):
        self.client.force_login(self.root)
        response = self.get(self.bob.username)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], "bob@example.com")
        self.assertEqual(self.get(new_username()).status_code, 404)

    def test_invalid_uuid(self):
        self.client.force_login(self.root)
        self.assertEqual(self.get("not-a-uuid").status_code, 422)


class SeedUsersTest(TestCase):
    def test_creates_example_users_once(self):
        with self.settings(DEBUG=True):
            call_command("seed_users", stdout=StringIO())
            call_command("seed_users", stdout=StringIO())  # safe to re-run
        self.assertEqual(User.objects.count(), 4)
        self.assertTrue(User.objects.get(email="admin@example.com").is_superuser)
        self.assertIsNotNone(
            authenticate(username="ana@example.com", password="password")
        )

    def test_refuses_without_debug(self):
        with self.assertRaises(CommandError):
            call_command("seed_users", stdout=StringIO())
        self.assertFalse(User.objects.exists())


class MeCacheTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="ana@example.com", password="s3cret-pass"
        )
        self.client.force_login(self.user)

    def me(self):
        return self.client.get("/api/users/me").json()

    def test_second_call_does_not_read_groups_or_permissions(self):
        self.me()
        with CaptureQueriesContext(connection) as queries:
            self.me()
        sql = " ".join(query["sql"] for query in queries)
        self.assertNotIn("auth_group", sql)
        self.assertNotIn("auth_permission", sql)

    def test_lives_ten_minutes(self):
        with patch.object(cache, "set", wraps=cache.set) as cache_set:
            self.me()
        self.assertEqual(cache_set.call_args.args[2], 600)
        self.assertIsNotNone(cache.get(cache_decorators.key(ME_CACHE, self.user.pk)))

    def test_refreshed_at_shows_a_cached_answer(self):
        first = self.me()["refreshed_at"]
        self.assertEqual(self.me()["refreshed_at"], first)
        self.client.force_login(self.user)
        self.assertNotEqual(self.me()["refreshed_at"], first)

    def test_logged_out_still_gets_401(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)

    def test_login_starts_it_over(self):
        self.me()
        stale = json.dumps({**self.me(), "groups": ["stale"]}).encode()
        entry_key = cache_decorators.key(ME_CACHE, self.user.pk)
        cache.set(entry_key, (stale, "application/json"), 600)
        self.assertEqual(self.me()["groups"], ["stale"])
        self.client.force_login(self.user)
        self.assertEqual(self.me()["groups"], [])

    def test_groups_and_permissions_changes_show_at_once(self):
        group = Group.objects.create(name="editors")
        self.assertEqual(self.me()["groups"], [])
        self.user.groups.add(group)
        self.assertEqual(self.me()["groups"], ["editors"])
        group.permissions.add(Permission.objects.get(codename="view_group"))
        self.assertIn("auth.view_group", self.me()["permissions"])
        self.user.groups.remove(group)
        self.assertEqual(self.me()["groups"], [])

    def test_saving_the_user_shows_at_once(self):
        self.assertEqual(self.me()["first_name"], "")
        self.user.first_name = "Ana"
        self.user.save()
        self.assertEqual(self.me()["first_name"], "Ana")
