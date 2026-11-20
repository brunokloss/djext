from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.note import services

User = get_user_model()


class NoteServicesTest(TestCase):
    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.bob = User.objects.create_user(email="bob@example.com", password="x")

    def test_create_trims_the_title(self):
        note = services.create_note(self.ana, title="  Groceries ", body="milk")
        self.assertEqual(note.title, "Groceries")
        self.assertEqual(note.owner, self.ana)

    def test_list_only_your_own_newest_first(self):
        first = services.create_note(self.ana, title="First")
        second = services.create_note(self.ana, title="Second")
        services.create_note(self.bob, title="Bob's")
        self.assertEqual(list(services.list_notes(self.ana)), [second, first])

    def test_get_someone_elses_is_none(self):
        note = services.create_note(self.bob, title="Bob's")
        self.assertIsNone(services.get_note(self.ana, note.public_id))
        self.assertEqual(services.get_note(self.bob, note.public_id), note)

    def test_update_changes_only_what_is_given(self):
        note = services.create_note(self.ana, title="Old", body="keep")
        services.update_note(note, title="New")
        note.refresh_from_db()
        self.assertEqual((note.title, note.body), ("New", "keep"))

    def test_delete(self):
        note = services.create_note(self.ana, title="Gone")
        services.delete_note(note)
        self.assertFalse(services.list_notes(self.ana).exists())

    def test_delete_old_notes_keeps_the_recent_ones(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.note.models import Note

        old = services.create_note(self.ana, title="Old")
        new = services.create_note(self.ana, title="New")
        Note.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - timedelta(days=31)
        )
        self.assertEqual(services.delete_old_notes(30), 1)
        self.assertEqual(list(services.list_notes(self.ana)), [new])

    def test_changes_go_to_the_audit_log_under_the_owner(self):
        from django.apps import apps

        if not apps.is_installed("modules.audit"):
            self.skipTest("modules/audit is not installed")
        from modules.audit.models import AuditLog

        note = services.create_note(self.ana, title="Logged")
        log = AuditLog.objects.filter(object_id=str(note.pk)).latest("id")
        self.assertIn(f":{self.ana.pk}", log.subject_1)
