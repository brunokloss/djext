from datetime import timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from apps.note import services
from apps.note.models import Note
from modules.signals.context import acting_as

User = get_user_model()


class NoteServicesTest(TestCase):
    """The rules, without HTTP: what the API, a task or an MCP tool gets."""

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

    def test_someone_elses_note_is_out_of_reach(self):
        note = services.create_note(self.bob, title="Bob's")
        self.assertIsNone(services.get_note(self.ana, note.public_id))
        self.assertIsNone(services.update_note(self.ana, note.public_id, title="x"))
        self.assertFalse(services.delete_note(self.ana, note.public_id))
        self.assertFalse(services.email_note(self.ana, note.public_id))
        note.refresh_from_db()
        self.assertEqual(note.title, "Bob's")
        self.assertEqual(mail.outbox, [])

    def test_update_changes_only_what_is_given(self):
        note = services.create_note(self.ana, title="Old", body="keep")
        services.update_note(self.ana, note.public_id, title="New")
        note.refresh_from_db()
        self.assertEqual((note.title, note.body), ("New", "keep"))

    def test_delete(self):
        note = services.create_note(self.ana, title="Gone")
        self.assertTrue(services.delete_note(self.ana, note.public_id))
        self.assertFalse(services.list_notes(self.ana).exists())

    def test_email_goes_to_the_owner(self):
        note = services.create_note(self.ana, title="Groceries", body="milk")
        self.assertTrue(services.email_note(self.ana, note.public_id))
        [email] = mail.outbox
        self.assertEqual((email.to, email.subject), (["ana@example.com"], "Groceries"))

    def test_delete_old_notes_keeps_the_recent_ones(self):
        old = services.create_note(self.ana, title="Old")
        new = services.create_note(self.ana, title="New")
        Note.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - timedelta(days=31)
        )
        self.assertEqual(services.delete_old_notes(30), 1)
        self.assertEqual(list(services.list_notes(self.ana)), [new])


class NoteAuditTest(TestCase):
    """Outside a request (a task, a command, an MCP tool), acting_as says who
    did it, and the audit log has it like it would from the API."""

    def setUp(self):
        if not apps.is_installed("modules.audit"):
            self.skipTest("modules/audit is not installed")
        self.ana = User.objects.create_user(email="ana@example.com", password="x")

    def logs(self, note):
        from modules.audit.models import AuditLog

        return AuditLog.objects.filter(object_id=str(note.pk)).order_by("id")

    def test_changes_and_actions_name_the_actor_and_the_owner(self):
        with acting_as(self.ana):
            note = services.create_note(self.ana, title="Logged")
            services.email_note(self.ana, note.public_id)
        create, email = self.logs(note)
        self.assertEqual((create.actor, email.actor), (self.ana, self.ana))
        self.assertEqual(email.name, "note.email")
        self.assertEqual(create.subjects, [f"authd.user:{self.ana.pk}"])
