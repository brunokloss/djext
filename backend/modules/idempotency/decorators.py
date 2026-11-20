"""`@idempotent`: a retry that sends the same `Idempotency-Key` gets the first
response back instead of running the endpoint again.

    @router.post("/invoices", response={201: InvoiceOut}, auth=user_auth)
    @idempotent
    def create_invoice(request, data: InvoiceIn): ...

Put it under the router's decorator. It follows the IETF draft
(draft-ietf-httpapi-idempotency-key-header):

- No header: the endpoint runs as usual, or 400 with `required=True`.
- Same key, other method, path or body: 422 (the client has a bug).
- Same key while the first request still runs: 409 (retry later).
- Same key after it finished: its response again, with `Idempotent-Replayed: true`.

Keys belong to the user who sent them, so it needs an authenticated endpoint;
anonymous requests run as if there were no header. They last
IDEMPOTENCY_TTL_HOURS (purged by `manage.py idempotency_purge`).

The user is `request.user`, which the session and `user_auth` (bearer keys) set;
an auth that doesn't set it counts as anonymous.

Stored: 2xx, 3xx and 4xx responses, as the endpoint's result (status, body and
Content-Type; other headers, like Location, don't come back). Not stored: 5xx
and crashes (the key is freed, so a retry runs again) and Ninja's own 422 on a
bad body (the endpoint never ran). Keep secrets out of these responses: they
sit in the database until the key expires.
"""

import hashlib
import inspect
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from ninja.decorators import decorate_view
from ninja.utils import contribute_operation_callback

from .models import IdempotencyKey

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
MAX_KEY_LENGTH = 255
# A key still processing after this is taken over: its request died midway
# (a killed worker never frees it). Longer than any request should last.
STALE_AFTER = timedelta(minutes=5)

# Where the claimed key waits, between the view and the response.
_REQUEST_ATTR = "_idempotency_key"


def idempotent(view=None, *, required: bool = False):
    """See the module docstring. `@idempotent` or `@idempotent(required=True)`."""

    def decorator(view):
        if hasattr(view, "_ninja_operation"):
            raise TypeError("@idempotent goes under the router's decorator, not above.")
        if inspect.iscoroutinefunction(view):
            raise TypeError("@idempotent works on sync views only.")

        @wraps(view)
        def claim(request: HttpRequest, *args, **kwargs):
            key = _read_key(request)
            if not key:
                if required:
                    return _error(400, f"This endpoint needs an {HEADER} header.")
                return view(request, *args, **kwargs)
            if len(key) > MAX_KEY_LENGTH:
                return _error(400, f"{HEADER} is longer than {MAX_KEY_LENGTH}.")
            user = getattr(request, "user", None)
            if user is None or not user.is_authenticated:
                return view(request, *args, **kwargs)

            row, response = _claim(user, key, _fingerprint(request))
            if response is not None:
                return response
            setattr(request, _REQUEST_ATTR, row)
            return view(request, *args, **kwargs)

        # `claim` runs after the auth and the body's validation; `_store` wraps
        # the whole operation, so it sees the final response.
        decorate_view(_store)(claim)
        contribute_operation_callback(claim, lambda op: _document(op, required))
        return claim

    return decorator(view) if view is not None else decorator


def _read_key(request: HttpRequest) -> str:
    # The draft sends it as a structured-field string ("..."); most clients
    # send it bare. Both are the same key.
    return request.headers.get(HEADER, "").strip().strip('"')


def _fingerprint(request: HttpRequest) -> str:
    digest = hashlib.sha256(f"{request.method} {request.get_full_path()}\n".encode())
    if request.content_type != "multipart/form-data":
        digest.update(request.body)
        return digest.hexdigest()
    # Multipart: Ninja already read the stream (so `request.body` raises), and
    # each retry has a new boundary anyway. Its fields and files are the request.
    for name in sorted(request.POST):
        for value in request.POST.getlist(name):
            digest.update(f"\n{name}={value}".encode())
    for name in sorted(request.FILES):
        for file in request.FILES.getlist(name):
            digest.update(f"\n{name}:{file.name}:{file.size}:".encode())
            for chunk in file.chunks():
                digest.update(chunk)
            file.seek(0)
    return digest.hexdigest()


def _claim(user, key: str, fingerprint: str):
    """(the key, None) when this request may run; (None, a response) when not."""
    # A few tries: a key can vanish between the INSERT and the SELECT (its
    # request failed and freed it, or it expired).
    for _ in range(3):
        try:
            with transaction.atomic():
                row = IdempotencyKey.objects.create(
                    user=user, key=key, fingerprint=fingerprint
                )
            return row, None
        except IntegrityError:
            pass

        row = IdempotencyKey.objects.filter(user=user, key=key).first()
        if row is None:
            continue
        now = timezone.now()
        if row.created_at < now - timedelta(hours=settings.IDEMPOTENCY_TTL_HOURS):
            # Expired but not purged yet: as if it were never sent.
            IdempotencyKey.objects.filter(pk=row.pk, created_at=row.created_at).delete()
            continue
        if row.fingerprint != fingerprint:
            return None, _error(
                422, f"This {HEADER} was already used for a different request."
            )
        if row.state == IdempotencyKey.State.DONE:
            return None, _replay(row)
        if row.updated_at < now - STALE_AFTER:
            # Conditional: of two retries taking over, only one wins.
            taken = IdempotencyKey.objects.filter(
                pk=row.pk,
                state=IdempotencyKey.State.PROCESSING,
                updated_at=row.updated_at,
            ).update(updated_at=now)
            if taken:
                row.updated_at = now
                return row, None
        break
    return None, _error(
        409, f"A request with this {HEADER} is still running. Retry later."
    )


def _store(run):
    """Wraps the operation: saves its response under the claimed key, or frees
    the key when it failed."""

    @wraps(run)
    def wrapper(request: HttpRequest, *args, **kwargs):
        try:
            response = run(request, *args, **kwargs)
        except BaseException:
            _free(request)
            raise
        row = getattr(request, _REQUEST_ATTR, None)
        if row is None:
            return response
        if response.status_code >= 500 or response.streaming:
            _free(request)
            return response
        row.state = IdempotencyKey.State.DONE
        row.status = response.status_code
        row.content_type = response.get("Content-Type", "")
        row.body = response.content
        row.save(
            update_fields=["state", "status", "content_type", "body", "updated_at"]
        )
        return response

    return wrapper


def _free(request: HttpRequest) -> None:
    if (row := getattr(request, _REQUEST_ATTR, None)) is not None:
        IdempotencyKey.objects.filter(pk=row.pk).delete()


def _replay(row: IdempotencyKey) -> HttpResponse:
    response = HttpResponse(
        bytes(row.body or b""), status=row.status, content_type=row.content_type
    )
    response[REPLAYED_HEADER] = "true"
    return response


def _error(status: int, detail: str) -> JsonResponse:
    # Same shape as Ninja's own errors.
    return JsonResponse({"detail": detail}, status=status)


def _document(operation, required: bool) -> None:
    """Shows the header in /api/docs (and in the frontend's schema.ts)."""
    extra = operation.openapi_extra or {}
    extra.setdefault("parameters", []).append(
        {
            "in": "header",
            "name": HEADER,
            "required": required,
            "schema": {"type": "string", "maxLength": MAX_KEY_LENGTH},
            "description": (
                "A new random value (a UUID) per action. Retries of the same "
                "action send the same value and get the first response back."
            ),
        }
    )
    operation.openapi_extra = extra
