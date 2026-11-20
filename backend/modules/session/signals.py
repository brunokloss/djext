from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from . import sessions

# Receivers only call functions, as in modules/audit/signals.py.


@receiver(user_logged_in, dispatch_uid="session.remember_login")
def on_login(sender, request, user, **kwargs):
    if request is not None:
        sessions.remember_login(request)
