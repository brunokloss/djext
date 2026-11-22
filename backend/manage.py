#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

# `manage.py test` runs with these, whatever the local .env says, so the
# suite gives the same result on every machine and never reaches a real
# service. They are set here, before Django loads, because settings.py acts
# on them while it loads (Sentry starts, S3 adds its app), too early for the
# test runner (config/test_runner.py); the --parallel workers inherit them.
# python-decouple reads the environment before the .env. A test that wants
# another value uses override_settings. See docs/development.md.
TEST_ENV = {
    # The database cache: each TestCase rolls it back, so counts (rate
    # limits, cached responses) don't leak into the next test, and a Redis
    # gets none of the tests' keys.
    "CACHE_URL": "",
    # Files on disk, never a bucket.
    "STORAGE_URL": "",
    # Nothing sent to Sentry.
    "SENTRY_DSN": "",
    # The login switches as they ship.
    "AUTH_PASSWORD": "True",
    "AUTH_SIGNUP": "False",
    "AUTH_PASSWORD_RESET": "False",
    "AUTH_MAGIC_LINK": "False",
}


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    if sys.argv[1:2] == ["test"]:
        os.environ.update(TEST_ENV)
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
