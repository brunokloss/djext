"""The notes API. Each view only reads the request, calls services.py and
shapes the answer: no rules here."""

from datetime import datetime
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Router, Schema

from modules.bearer.security import user_auth
from modules.idempotency.decorators import idempotent

from . import services

router = Router(auth=user_auth, tags=["notes"])


class NoteIn(Schema):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""


class NotePatch(Schema):
    title: str | None = Field(None, min_length=1, max_length=200)
    body: str | None = None


class NoteOut(Schema):
    id: UUID = Field(alias="public_id")
    title: str
    body: str
    created_at: datetime
    updated_at: datetime


class NotFoundOut(Schema):
    detail: str


NOT_FOUND = 404, {"detail": "Not found"}


@router.get("/notes", response=list[NoteOut])
def list_notes(request: HttpRequest):
    """Your notes, newest first."""
    return services.list_notes(request.auth)


# @idempotent: a retry with the same Idempotency-Key (a timeout, a double
# click) gets the first answer back instead of a second note.
@router.post("/notes", response={201: NoteOut})
@idempotent
def create_note(request: HttpRequest, data: NoteIn):
    """Adds a note. Send an `Idempotency-Key` header to make retries safe."""
    return 201, services.create_note(request.auth, **data.dict())


@router.get("/notes/{uuid:note_id}", response={200: NoteOut, 404: NotFoundOut})
def get_note(request: HttpRequest, note_id: UUID):
    """One of your notes (404 for anyone else's)."""
    note = services.get_note(request.auth, note_id)
    return note if note else NOT_FOUND


@router.patch("/notes/{uuid:note_id}", response={200: NoteOut, 404: NotFoundOut})
def update_note(request: HttpRequest, note_id: UUID, data: NotePatch):
    """Changes the fields you send."""
    note = services.get_note(request.auth, note_id)
    if note is None:
        return NOT_FOUND
    return services.update_note(note, **data.dict(exclude_unset=True))


@router.delete("/notes/{uuid:note_id}", response={204: None, 404: NotFoundOut})
def delete_note(request: HttpRequest, note_id: UUID):
    """Deletes one of your notes."""
    note = services.get_note(request.auth, note_id)
    if note is None:
        return NOT_FOUND
    services.delete_note(note)
    return 204, None


@router.post("/notes/{uuid:note_id}/email", response={204: None, 404: NotFoundOut})
@idempotent
def email_note(request: HttpRequest, note_id: UUID):
    """Emails the note to you. With modules/mail it is queued and a worker sends it."""
    note = services.get_note(request.auth, note_id)
    if note is None:
        return NOT_FOUND
    services.email_note(request, note)
    return 204, None
