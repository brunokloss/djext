"""`manage.py test` keeps logs out of its output, its --parallel workers
included: every request logs a line and some tests cause errors on purpose
(a failing cron job, a 500). A failing test still shows its traceback in the
report; modules/log/tests.py turns logging back on for its own checks.

What the tests read from the environment (the cache, storage, Sentry, the
login switches) is set in manage.py (TEST_ENV), before the settings load."""

import logging

from django.test.runner import DiscoverRunner, ParallelTestSuite


def silence_logs():
    logging.disable(logging.CRITICAL)


class ParallelSuite(ParallelTestSuite):
    # Each worker starts its own Django.
    process_setup = silence_logs


class TestRunner(DiscoverRunner):
    parallel_test_suite = ParallelSuite

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        silence_logs()
