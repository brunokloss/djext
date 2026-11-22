from django.dispatch import Signal

# Something a person did that is not a model change (clear the cache, ...).
# Sent as `action_performed.send(sender, request=request, name="cache.clear",
# values={...}, target=obj)`. A service leaves `request` out: the receivers
# take the request being handled, or `acting_as`'s user (context.py).
# `target` is what it was done to, when anything (the user whose sessions
# were ended): the log names it, so it is in that user's history. Who asked
# for it is the actor (`context.current_actor()`). The apps and the modules
# don't import each other for this: they all send and receive it here, and
# modules/audit and modules/log log it, if they are installed.
action_performed = Signal()

# A login refused before the password is checked: too many failures for that
# email or from that IP. Sent as `login_throttled.send(sender, request=request,
# email=email, limit="email" | "ip", retry_after=seconds)`. modules/log
# logs it in the auth channel. Nothing writes it to the database: an attacker
# hammering the login gets here on every try.
login_throttled = Signal()

# Ways to log in besides the password, for the login page (/auth/providers, in
# authd). Sent as `login_options_requested.send(sender)`: a module that adds
# some (like modules/oauth) returns the ones that are on, as a list of
# {"name", "label", "url"}. authd doesn't know any of them.
login_options_requested = Signal()

# A login with the right password for a user who is not active. Sent as
# `inactive_login.send(sender, request=request, user=user)`: a module that
# knows why returns the message the login shows (modules/signup: the email is
# not confirmed yet, and a new link goes), else None. Without one, the login
# says "Invalid email or password", as for a wrong password. Only the
# password's owner gets here, so it tells nothing to whoever is guessing
# emails.
inactive_login = Signal()

# Not a signal: a login that is not by password sets `request.auth_provider`
# ("google", "microsoft", ...) before calling login() (modules/oauth does).
# modules/audit logs it as the login's method; without it, "password".
