from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.note import services

User = get_user_model()


class NoteApiTest(TestCase):
    """The views only call services.py: these tests check the HTTP side
    (status codes, the shape of the answer, who may reach what)."""

    def setUp(self):
        self.ana = User.objects.create_user(email="ana@example.com", password="x")
        self.client.force_login(self.ana)

    def test_needs_login(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/notes").status_code, 401)

    def test_create_and_list(self):
        response = self.client.post(
            "/api/notes",
            {"title": "Groceries", "body": "milk"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        created = response.json()
        note = services.list_notes(self.ana).get()
        # The public id, never the integer one.
        self.assertEqual(created["id"], str(note.public_id))
        self.assertEqual(self.client.get("/api/notes").json(), [created])

    def test_empty_title_is_rejected(self):
        response = self.client.post(
            "/api/notes", {"title": ""}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 422)

    def test_patch_and_delete(self):
        note = services.create_note(self.ana, title="Old", body="keep")
        url = f"/api/notes/{note.public_id}"
        response = self.client.patch(
            url, {"title": "New"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["body"], "keep")
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_someone_elses_note_is_not_found(self):
        bob = User.objects.create_user(email="bob@example.com", password="x")
        url = f"/api/notes/{services.create_note(bob, title='Bob').public_id}"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.patch(
                url, {"title": "Mine"}, content_type="application/json"
            ).status_code,
            404,
        )
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_create_with_the_same_key_twice_makes_one_note(self):
        def create():
            return self.client.post(
                "/api/notes",
                {"title": "Once"},
                content_type="application/json",
                headers={"Idempotency-Key": "a-retry"},
            )

        first, second = create(), create()
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(second.headers["Idempotent-Replayed"], "true")
        self.assertEqual(services.list_notes(self.ana).count(), 1)

    def test_email_sends_it_once_per_key(self):
        from django.core import mail

        note = services.create_note(self.ana, title="Groceries", body="milk")
        url = f"/api/notes/{note.public_id}/email"
        for _ in range(2):
            response = self.client.post(url, headers={"Idempotency-Key": "k"})
            self.assertEqual(response.status_code, 204)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ana@example.com"])
