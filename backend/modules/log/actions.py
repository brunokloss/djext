"""Every action a person did that is not a model change (modules/signals'
`action_performed`): one line each, named after it ("auth.unlock_login").

Actions named `auth.*` go to the auth channel, the rest to app. Each line says
whose it was (`usr`: the target, when it is a user, or else who asked), who
asked (`by`) and from where (`xip`, `uag`, `lng`), plus the action's values.
A target that isn't a user is in the audit log, not here.
"""

import logging

from django.contrib.auth import get_user_model

from .auth import client

CHANNELS = {"auth"}
# Keys a log record has already: logging refuses them as extra fields.
RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def action(request, name, values=None, target=None):
    prefix = name.split(".", 1)[0]
    logger = logging.getLogger(prefix if prefix in CHANNELS else __name__)
    user = getattr(request, "user", None)
    by = user.username if user is not None and user.is_authenticated else None
    fields = {k: v for k, v in (values or {}).items() if k not in RESERVED}
    if target is None:
        fields["usr"] = by
    elif isinstance(target, get_user_model()):
        fields["usr"] = target.username
    logger.info(name, extra={**fields, "by": by, **client(request)})
