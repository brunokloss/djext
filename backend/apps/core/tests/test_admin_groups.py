from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings


@override_settings(ALLOWED_HOSTS=["testserver"])
class AdminGroupsTest(TestCase):
    def setUp(self):
        self.client.force_login(
            get_user_model().objects.create_superuser(
                email="admin@example.com", password="s3cret-pass"
            )
        )

    def groups(self):
        return {
            app["app_label"]: [model["name"] for model in app["models"]]
            for app in self.client.get("/admin/").context["app_list"]
        }

    def test_apps_sit_inside_the_group_the_settings_name(self):
        groups = self.groups()
        for label in ("authd", "oauth", "cron", "system"):
            self.assertNotIn(label, groups)
        self.assertIn("Users", groups["auth"])
        self.assertIn("Groups", groups["auth"])
        self.assertIn("User identities", groups["auth"])
        self.assertIn("Cron Schedules", groups["django_tasks_database"])
        self.assertIn("Task Results", groups["django_tasks_database"])
        self.assertIn("Runtime", groups["audit"])
        self.assertIn("Audit logs", groups["audit"])

    @override_settings(ADMIN_APP_GROUPS={})
    def test_without_settings_every_app_has_its_group(self):
        groups = self.groups()
        for label in ("authd", "oauth", "cron", "system"):
            self.assertIn(label, groups)

    @override_settings(ADMIN_APP_GROUPS={"authd": "nothing", "nothing": "auth"})
    def test_a_missing_app_or_group_is_skipped(self):
        groups = self.groups()
        self.assertIn("authd", groups)
        self.assertIn("auth", groups)
