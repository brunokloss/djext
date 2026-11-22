"""`manage.py test` with the login switches as they ship, whatever the local
.env says, so the suite gives the same result on every machine (a .env with
AUTH_PASSWORD=False to try the login link would fail every test that logs in
with a password). A test that wants a switch on turns it on with
override_settings."""

import os

from django.test.runner import DiscoverRunner, ParallelTestSuite
from django.test.utils import override_settings

LOGIN_DEFAULTS = {
    "AUTH_PASSWORD": True,
    "AUTH_SIGNUP": False,
    "AUTH_PASSWORD_RESET": False,
    "AUTH_MAGIC_LINK": False,
}


def login_defaults_in_env():
    """Each worker of --parallel loads the settings again, after this:
    python-decouple reads the environment before the .env."""
    os.environ.update({name: str(value) for name, value in LOGIN_DEFAULTS.items()})


class ParallelSuite(ParallelTestSuite):
    process_setup = login_defaults_in_env


class TestRunner(DiscoverRunner):
    parallel_test_suite = ParallelSuite

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        # This process loaded the settings already.
        self.login_defaults = override_settings(**LOGIN_DEFAULTS)
        self.login_defaults.enable()

    def teardown_test_environment(self, **kwargs):
        self.login_defaults.disable()
        super().teardown_test_environment(**kwargs)
