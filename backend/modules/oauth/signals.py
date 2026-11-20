from django.dispatch import receiver

from modules.signals.signals import login_options_requested

from . import api

# Receivers only call functions, as in modules/audit/signals.py.


@receiver(login_options_requested, dispatch_uid="oauth.login_options")
def on_login_options(sender, **kwargs):
    # The providers that are on, on authd's login page.
    return api.login_options()
