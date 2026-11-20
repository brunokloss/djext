"""Writes the audit log (called from signals.py).

A log names up to three subjects (AuditLog.subject_1..3). A model is
audited when it has an `Audit` class, which needs no import
(and is inherited, so an abstract model can audit all its children):

    class Order(models.Model):
        class Audit:
            subjects = ["user", "tenant"]  # whose data it is: "self" or a path
            exclude = ["updated_at"]       # never logged
            mask = ["card_token"]          # logged as "abc123…wxyz"

Models you can't edit (Django's, a package's) go in settings.AUDIT_MODELS
instead, with the same options: {"auth.Group": {"subjects": [...]}}.

Auditing is opt-in, so a model nobody decided about would go unlogged without
anyone noticing. `manage.py check` warns (audit.W001) about each one, until it
is audited or says it isn't, with `skip = True` in either place.

A subject is whose data it is (a user, a tenant), to find their logs. A path
follows foreign keys like a lookup: "order__user".

Deleting a subject deletes none of its logs: they may be someone else's record
too (a company's orders, made by an employee who left). Anonymizing a user
(User.anonymize()) keeps them too, but masks their values (forget below).
"""

from dataclasses import dataclass, field

from django.apps import apps
from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email
from django.db.models import Q

from modules.signals.context import current_actor, current_request, request_user

from .middleware import request_info
from .models import AuditLog


@dataclass(frozen=True)
class Config:
    subjects: tuple[str, ...] = ()
    exclude: frozenset[str] = field(default_factory=frozenset)
    mask: frozenset[str] = field(default_factory=frozenset)


# Filled when the app is ready.
AUDITED: dict[type, Config] = {}
# Models that said `skip = True`: decided, and not audited.
SKIPPED: set[type] = set()
# Django's own noise, never worth a warning.
IGNORED = {
    "admin.logentry",
    "audit.auditlog",
    "auth.permission",
    "contenttypes.contenttype",
    "sessions.session",
}


def load():
    AUDITED.clear()
    SKIPPED.clear()
    for model in apps.get_models():
        # A plain attribute to Django: it only reads Meta and the fields.
        if audit := getattr(model, "Audit", None):
            if getattr(audit, "skip", False):
                SKIPPED.add(model)
                continue
            add(
                model,
                subjects=getattr(audit, "subjects", ()),
                exclude=getattr(audit, "exclude", ()),
                mask=getattr(audit, "mask", ()),
            )
    for label, options in getattr(settings, "AUDIT_MODELS", {}).items():
        model = apps.get_model(label)
        if options.get("skip"):
            SKIPPED.add(model)
            continue
        add(model, **options)


def undecided():
    """Models that are neither audited nor skipped, nor Django's noise."""
    return [
        model
        for model in apps.get_models()
        if model not in AUDITED
        and model not in SKIPPED
        and model._meta.label_lower not in IGNORED
    ]


# A column each in AuditLog: subject_1, subject_2, subject_3.
MAX_SUBJECTS = 3


def add(model, subjects=(), exclude=(), mask=()):
    if len(subjects) > MAX_SUBJECTS:
        raise ImproperlyConfigured(
            f"{model._meta.label}: at most {MAX_SUBJECTS} audit subjects."
        )
    config = Config(tuple(subjects), frozenset(exclude), frozenset(mask))
    AUDITED[model] = config
    for path in config.subjects:
        subject_model(model, path)  # A wrong path fails here, at startup.


def subject_model(model, path):
    if path == "self":
        return model
    for name in path.split("__"):
        model = model._meta.get_field(name).related_model
    return model


def subject_key(model, pk) -> str:
    """How a log names a subject: "authd.user:6"."""
    return f"{model._meta.label_lower}:{pk}"


def subject_columns(keys) -> dict:
    return {f"subject_{i}": key for i, key in enumerate(keys, start=1)}


def subject_id(instance, path):
    """The subject's pk, reading the last foreign key's id column (no query
    for a direct one like "user")."""
    if path == "self":
        return instance.pk
    *parents, last = path.split("__")
    for name in parents:
        instance = getattr(instance, name)
        if instance is None:
            return None
    return getattr(instance, instance._meta.get_field(last).attname)


def subject_keys(instance, config) -> list[str]:
    """Whose data `instance` is, from its model's Audit.subjects."""
    keys = []
    for path in config.subjects if config else ():
        pk = subject_id(instance, path)
        if pk is not None:
            # _meta.model, not type(): it may be request.user, a lazy object.
            model = subject_model(instance._meta.model, path)
            keys.append(subject_key(model, pk))
    return keys


def mask(value) -> str:
    """The head and tail, so a diff still shows that a secret changed (they
    often share a prefix, like "pbkdf2_sha256$"). Short ones are hidden."""
    text = str(value)
    if len(text) < 16:
        return "***"
    return f"{text[:6]}…{text[-4:]}"


def snapshot(instance, config) -> dict:
    """The whole row as text, without the empty fields."""
    data = {}
    for f in instance._meta.concrete_fields:
        value = f.value_from_object(instance)
        if value is None or f.name in config.exclude:
            continue
        data[f.name] = mask(value) if f.name in config.mask else str(value)
    return data


def write(action, instance, old_values=None, new_values=None, config=None):
    info = request_info(current_request.get())
    actor = info.get("actor")
    if action == AuditLog.Action.DELETE and isinstance(instance, type(actor)):
        if actor.pk == instance.pk:
            # Deleting your own account: the actor row is gone with it.
            info = {**info, "actor": None}
    keys = subject_keys(instance, config)
    AuditLog.objects.create(
        action=action,
        content_type=ContentType.objects.get_for_model(instance),
        object_id=str(instance.pk),
        object_repr=str(instance)[:200],
        old_values=old_values,
        new_values=new_values,
        **subject_columns(keys),
        **info,
    )


def before_save(instance, update_fields):
    """Keeps the row as it is in the database, to diff after the save."""
    config = AUDITED.get(type(instance))
    if config is None or instance._state.adding or instance.pk is None:
        return
    # A save of excluded fields only (like last_login on each login) costs
    # nothing and logs nothing.
    if update_fields and set(update_fields) <= config.exclude:
        return
    current = type(instance)._base_manager.filter(pk=instance.pk).first()
    instance._audit_before = snapshot(current, config) if current else {}


def saved(instance, created):
    config = AUDITED.get(type(instance))
    if config is None:
        return
    before = vars(instance).pop("_audit_before", None)
    after = snapshot(instance, config)
    if created:
        write(AuditLog.Action.CREATE, instance, None, after, config)
    elif before is not None and before != after:
        write(AuditLog.Action.UPDATE, instance, before, after, config)


def deleted(instance):
    config = AUDITED.get(type(instance))
    if config is not None:
        old_values = snapshot(instance, config)
        write(AuditLog.Action.DELETE, instance, old_values, None, config)


def m2m_changed(instance, through, action, pk_set):
    """add, remove and clear on a many-to-many field of an audited model,
    like User.groups. Only from that side: group.user_set.add() isn't."""
    config = AUDITED.get(type(instance))
    if config is None or action not in ("post_add", "post_remove", "post_clear"):
        return
    field = next(
        f for f in instance._meta.many_to_many if f.remote_field.through is through
    )
    payload = {
        "field": field.name,
        "operation": action.removeprefix("post_"),
        "related_model": field.related_model.__name__,
        "related_ids": sorted(str(pk) for pk in pk_set or ()),
    }
    write(AuditLog.Action.M2M, instance, None, payload, config)


def login(request, user):
    """Who logged in, how (`method`: "password" or the provider) and the
    session it got: the same session_hash as everything they do until they
    log out."""
    values = {
        # Set by modules/oauth: every login goes through the same backend.
        "method": getattr(request, "auth_provider", None) or "password",
        # login() saves it in the session; user.backend may be unset.
        "backend": request.session.get(BACKEND_SESSION_KEY),
    }
    auth_event(AuditLog.Action.LOGIN, request, user, values)


def logout(request, user):
    if user is not None:
        auth_event(AuditLog.Action.LOGOUT, request, user)


def login_failed(request, credentials):
    """A wrong password (`email` from the API, `username` from the admin's
    form) or a provider that didn't log anyone in (modules/oauth adds
    `provider` and `reason`). Only these keys: credentials may hold more.
    No query: failed logins are what an attacker hammers."""
    email = email_or_none(credentials.get("email") or credentials.get("username"))
    values = {
        "method": credentials.get("provider") or "password",
        # Django doesn't say why a password login failed: no such user,
        # wrong password or inactive look the same, on purpose.
        "reason": credentials.get("reason") or "invalid_credentials",
    }
    auth_event(AuditLog.Action.LOGIN_FAILED, request, None, values, email or "")


def action(request, name, values=None, target=None):  # request may be None
    """A person did something that is not a model change (modules/signals'
    `action_performed`). The object is `target`, what it was done to (a user
    whose sessions were ended), and its subjects are the log's, so it shows in
    that user's history and goes with them. With no target, the object and
    subject is the actor. The actor is always who asked for it. Sent without a
    request (from a service), it takes the request being handled, or
    `acting_as`'s user outside one."""
    if request is None:
        request = current_request.get()
    user = request_user(request) or current_actor()
    obj = target if target is not None else user
    # _meta.model, not type(): request.user is a lazy object.
    model = obj._meta.model if obj is not None else get_user_model()
    if target is not None:
        keys = subject_keys(target, AUDITED.get(model))
    else:
        keys = [subject_key(model, user.pk)] if user else []
    AuditLog.objects.create(
        action=AuditLog.Action.ACTION,
        content_type=ContentType.objects.get_for_model(model),
        object_id=str(obj.pk) if obj else "",
        object_repr=str(obj)[:200] if obj else "",
        name=name[:100],
        new_values=values or None,
        **subject_columns(keys),
        **request_info(request),
    )


def auth_event(action, request, user, values=None, email=""):
    model = get_user_model()
    keys = [subject_key(model, user.pk)] if user else []
    AuditLog.objects.create(
        action=action,
        content_type=ContentType.objects.get_for_model(model),
        object_id=str(user.pk) if user else "",
        object_repr=(str(user) if user else email)[:200],
        new_values=values or None,
        **subject_columns(keys),
        **request_info(request),
    )


def email_or_none(value) -> str | None:
    """The email, normalized, or None when it isn't one (a password typed in
    the wrong field, or garbage)."""
    email = get_user_model().objects.normalize_email(value)
    try:
        validate_email(email)
    except ValidationError:
        return None
    return email


def forget(user_pk, email):
    """After a user is anonymized: their logs keep what was done, when and by
    whom, but not the values. Where they are a subject, the values (each
    field as "***") and the object; where they did it, their IP and browser;
    and the failed logins with their email. Logs are never edited otherwise.
    """
    key = subject_key(get_user_model(), user_pk)
    logs = AuditLog.objects.filter(
        Q(subject_1=key) | Q(subject_2=key) | Q(subject_3=key)
    ).only("old_values", "new_values")
    batch = []
    for row in logs.iterator(chunk_size=500):
        row.old_values = masked(row.old_values)
        row.new_values = masked(row.new_values)
        row.object_repr = "***"
        batch.append(row)
    AuditLog.objects.bulk_update(
        batch, ["old_values", "new_values", "object_repr"], batch_size=500
    )
    AuditLog.objects.filter(actor_id=user_pk).update(ip_address=None, user_agent="")
    AuditLog.objects.filter(
        action=AuditLog.Action.LOGIN_FAILED, object_repr__iexact=email
    ).update(object_repr="***", ip_address=None, user_agent="")


def masked(values):
    # The keys stay: they say which fields changed.
    return {k: "***" for k in values} if values else values
