from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from modules.cache import decorators as cache
from modules.signals.signals import action_performed
from modules.throttle.throttles import hashed

from .api.auth import email_login_limit
from .api.users import ME_CACHE

User = get_user_model()


# The cached /users/me is dropped when its user logs in or changes.
# Receivers only call functions, as in modules/audit/signals.py.


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    cache.invalidate(ME_CACHE, user.pk)


@receiver(post_save, sender=User)
def on_user_saved(sender, instance, update_fields, **kwargs):
    # Every save but last_login's alone (each login, which drops it anyway), so a
    # field added to MeOut needs nothing here.
    if update_fields is None or set(update_fields) - {"last_login"}:
        cache.invalidate(ME_CACHE, instance.pk)


@receiver(post_delete, sender=User)
def on_user_deleted(sender, instance, **kwargs):
    cache.invalidate(ME_CACHE, instance.pk)


@receiver(m2m_changed, sender=User.groups.through)
@receiver(m2m_changed, sender=User.user_permissions.through)
def on_user_links_changed(sender, instance, action, pk_set, **kwargs):
    if action not in ("post_add", "post_remove"):
        return
    # Forward: `instance` is the user. Reverse: it is the group or permission and
    # `pk_set` the users.
    users = [instance.pk] if isinstance(instance, User) else pk_set
    cache.invalidate(ME_CACHE, *users)


@receiver(m2m_changed, sender=Group.permissions.through)
def on_group_permissions_changed(sender, instance, action, pk_set, **kwargs):
    if action not in ("post_add", "post_remove"):
        return
    # Forward: `instance` is the group. Reverse: it is a permission and `pk_set`
    # the groups.
    groups = [instance.pk] if isinstance(instance, Group) else pk_set
    members = User.objects.filter(groups__in=groups).values_list("pk", flat=True)
    cache.invalidate(ME_CACHE, *members)


# A new password from a reset link (modules/signup) lifts the email's login
# lock: whoever set it owns the inbox.
@receiver(action_performed, dispatch_uid="authd.on_password_reset")
def on_password_reset(sender, name, target=None, **kwargs):
    if name == "auth.password_reset" and (limit := email_login_limit()):
        limit.clear(hashed(target.email))
