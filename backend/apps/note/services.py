"""What can be done with notes. Every entry point (the API, the admin, a task,
a command, an MCP tool) calls these functions, so the rules live in one place.

Each takes the user it acts for, never the HTTP request, and only ever reaches
that user's notes: a note that isn't theirs is None (or False), the same as one
that doesn't exist. Outside a request, call them inside `acting_as(user)`
(modules/signals/context.py) so the audit log and the logs know who did it."""

import logging
from datetime import timedelta
from uuid import UUID

from django.core.mail import send_mail
from django.utils import timezone

from modules.signals.signals import action_performed

from .models import Note

logger = logging.getLogger(__name__)


def list_notes(user):
    return Note.objects.filter(owner=user)


def get_note(user, note_id: UUID) -> Note | None:
    return Note.objects.filter(owner=user, public_id=note_id).first()


def create_note(user, *, title: str, body: str = "") -> Note:
    return Note.objects.create(owner=user, title=title.strip(), body=body)


def update_note(
    user, note_id: UUID, *, title: str | None = None, body: str | None = None
) -> Note | None:
    """Changes the fields given (None leaves one as it is)."""
    note = get_note(user, note_id)
    if note is None:
        return None
    if title is not None:
        note.title = title.strip()
    if body is not None:
        note.body = body
    note.save()
    return note


def delete_note(user, note_id: UUID) -> bool:
    note = get_note(user, note_id)
    if note is None:
        return False
    note.delete()
    return True


def email_note(user, note_id: UUID) -> bool:
    """Emails the note to its owner. Stock `send_mail`: with modules/mail it
    goes to the queue and a worker sends it, with retries. Not a model change,
    so it is sent as an action: the receivers find who asked themselves."""
    note = get_note(user, note_id)
    if note is None:
        return False
    send_mail(note.title, note.body, None, [user.email])
    action_performed.send(
        None, name="note.email", values={"note": str(note.public_id)}, target=note
    )
    return True


def delete_old_notes(days: int) -> int:
    """Deletes the notes last changed more than `days` ago. Returns how many.
    A system job: it acts for nobody."""
    cutoff = timezone.now() - timedelta(days=days)
    count, _ = Note.objects.filter(updated_at__lt=cutoff).delete()
    logger.info("note.delete_old", extra={"count": count, "days": days})
    return count
