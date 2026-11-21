from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from modules.signals.signals import inactive_login

from . import services

# Receivers only call functions, as in modules/audit/signals.py.


@receiver(post_save, sender=get_user_model(), dispatch_uid="signup.on_user_saved")
def on_user_saved(sender, instance, update_fields, **kwargs):
    # Activated another way (the team, in the admin): no longer waiting, so a
    # link can't activate them again after they are blocked.
    if instance.is_active and (update_fields is None or "is_active" in update_fields):
        services.stop_waiting(instance)


@receiver(inactive_login, dispatch_uid="signup.on_inactive_login")
def on_inactive_login(sender, user, **kwargs):
    # The right password before the link: say so instead of "invalid".
    if services.waiting(user):
        return "Confirm your email first: open the link we sent you."
    return None
