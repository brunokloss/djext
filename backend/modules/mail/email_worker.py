"""A separate process for TwoWorkersTest (tests.py): sends every email it is
given with the real send_email task, at the same time as another one.

    EMAIL_WORKER_DIR=<dir> python modules/mail/email_worker.py <ids, comma separated>

DATABASE_URL points it at the test database. Each email "sent" is a line in
<dir>/sent-<pid> (the mail server is a slow fake), so the test can count
them. It starts when <dir>/go exists, after writing <dir>/ready-<pid>, so both
processes really run at once instead of one after the other.
"""

import os
import sys
import time
from pathlib import Path

from django.core.mail.backends.base import BaseEmailBackend

# From the environment: the backend below is imported again by its dotted
# path (modules.mail.email_worker), a module apart from this __main__.
OUT = Path(os.environ.get("EMAIL_WORKER_DIR", "."))


class SlowBackend(BaseEmailBackend):
    """Takes a while per email, as a real server does, so the other process
    meets the row lock."""

    def send_messages(self, messages):
        with (OUT / f"sent-{os.getpid()}").open("a") as out:
            for message in messages:
                time.sleep(0.05)
                out.write(f"{message.subject}\n")
        return len(messages)


def main(ids: list[int]) -> None:
    import django

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    from django.test import override_settings

    from modules.mail.tasks import send_email

    mailers = {
        "default": {"BACKEND": "post_office.EmailBackend"},
        "direct": {"BACKEND": "modules.mail.email_worker.SlowBackend"},
    }
    with override_settings(MAILERS=mailers):
        (OUT / f"ready-{os.getpid()}").touch()
        while not (OUT / "go").exists():
            time.sleep(0.01)
        for email_id in ids:
            send_email.call(email_id)


if __name__ == "__main__":
    main([int(i) for i in sys.argv[1].split(",")])
