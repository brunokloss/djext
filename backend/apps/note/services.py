"""What can be done with notes. The API, the admin and anything else call these
functions, so the rules live in one place: a user only ever reaches their own
notes."""

import logging
from datetime import timedelta
from uuid import UUID

from django.core.mail import send_mail
from django.http import HttpRequest
from django.utils import timezone

from modules.signals.signals import action_performed

from .models import Note

logger = logging.getLogger(__name__)


def list_notes(user):
    return Note.objects.filter(owner=user)


def get_note(user, public_id: UUID) -> Note | None:
    return Note.objects.filter(owner=user, public_id=public_id).first()


def create_note(user, *, title: str, body: str = "") -> Note:
    return Note.objects.create(owner=user, title=title.strip(), body=body)


def update_note(note: Note, *, title: str | None = None, body: str | None = None):
    if title is not None:
        note.title = title.strip()
    if body is not None:
        note.body = body
    note.save()
    return note


def delete_note(note: Note) -> None:
    note.delete()


def email_note(request: HttpRequest | None, note: Note) -> None:
    """Emails the note to its owner. Stock `send_mail`: with modules/mail it
    goes to the queue and a worker sends it, with retries. Not a model change,
    so it is logged as an action (who asked, which note)."""
    send_mail(note.title, note.body, None, [note.owner.email])
    action_performed.send(
        None,
        request=request,
        name="note.email",
        values={"note": str(note.public_id)},
        target=note,
    )


def delete_old_notes(days: int) -> int:
    """Deletes the notes last changed more than `days` ago. Returns how many."""
    cutoff = timezone.now() - timedelta(days=days)
    count, _ = Note.objects.filter(updated_at__lt=cutoff).delete()
    logger.info("note.delete_old", extra={"count": count, "days": days})
    return count
