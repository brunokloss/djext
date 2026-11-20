from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_save,
)

from modules.signals.signals import action_performed

from . import log

# Connected per model (connect), not for every model: a delete receiver for
# all of them would turn every QuerySet.delete() in the project into one
# query per row. `raw` is loaddata, which saves fixtures as they are.


def on_pre_save(sender, instance, raw, update_fields, **kwargs):
    if not raw:
        log.before_save(instance, update_fields)


def on_post_save(sender, instance, created, raw, **kwargs):
    if not raw:
        log.saved(instance, created)


def on_post_delete(sender, instance, **kwargs):
    log.deleted(instance)


def on_m2m_changed(sender, instance, action, pk_set, **kwargs):
    log.m2m_changed(instance, sender, action, pk_set)


def on_login(sender, request, user, **kwargs):
    log.login(request, user)


def on_logout(sender, request, user, **kwargs):
    log.logout(request, user)


def on_login_failed(sender, credentials, request=None, **kwargs):
    log.login_failed(request, credentials)


def on_action(sender, name, request=None, values=None, target=None, **kwargs):
    log.action(request, name, values, target)


def connect():
    """For the models log.load() found. Connecting twice is a no-op."""
    for model in log.AUDITED:
        pre_save.connect(on_pre_save, sender=model)
        post_save.connect(on_post_save, sender=model)
        for field in model._meta.many_to_many:
            m2m_changed.connect(on_m2m_changed, sender=field.remote_field.through)
        post_delete.connect(on_post_delete, sender=model)
    # Every login sends these: the API, the admin's form and the providers.
    user_logged_in.connect(on_login)
    user_logged_out.connect(on_logout)
    user_login_failed.connect(on_login_failed)
    action_performed.connect(on_action, dispatch_uid="audit.on_action")
