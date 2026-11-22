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
def on_inactive_login(sender, request, user, **kwargs):
    # The right password before the link: say so instead of "invalid", and
    # send a new link (the first may have expired), within the email limits.
    if not services.waiting(user):
        return None
    from .api import mail_wait, site

    if mail_wait(request, user.email):
        return "Your email isn't confirmed yet. Open the link we sent you."
    services.resend_verification(site(request), user.email)
    return f"Your email isn't confirmed yet. We sent a new link to {user.email}."
