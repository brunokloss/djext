from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver
from django.tasks.signals import (
    log_task_finished,
    log_task_started,
    task_finished,
    task_started,
)

from modules.signals.signals import action_performed, login_throttled

from . import actions, auth, tasks

# Every login sends these: the API, the admin's form and the providers
# (modules/oauth sends user_login_failed itself).


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    auth.login(request, user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    auth.logout(request, user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    auth.login_failed(request, credentials)


@receiver(login_throttled)
def on_login_throttled(sender, request, email, limit, retry_after, **kwargs):
    auth.login_throttled(request, email, limit, retry_after)


# What a person did that is not a model change (unlock a login, ...).
@receiver(action_performed)
def on_action(sender, name, request=None, values=None, target=None, **kwargs):
    actions.action(request, name, values, target)


# The worker sends these around each task, in the thread that runs it.


@receiver(task_started)
def on_task_started(sender, task_result, **kwargs):
    tasks.started(task_result)


@receiver(task_finished)
def on_task_finished(sender, task_result, **kwargs):
    tasks.finished(task_result)


# Django logs "Task ... state=RUNNING" from this same signal, and its receiver
# was connected first, so the line came out before tsk, que and wrk were set.
# Connecting it again puts it after ours.
task_started.disconnect(log_task_started)
task_started.connect(log_task_started)

# The same for the line that says how it ended (it gets `dur`), and what we put
# in the context comes out only after it.
task_finished.disconnect(log_task_finished)
task_finished.connect(log_task_finished)


@receiver(task_finished)
def on_task_finished_cleanup(sender, task_result, **kwargs):
    tasks.cleanup()
