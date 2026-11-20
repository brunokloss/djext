"""Run the scheduler loop — ticks `cron_tick` once per minute.

Thin wrapper around `registry.run_scheduler` (the bare loop). The autoreloader
is a dev-runtime concern, so it lives here: on by default (keeps stdout flushed
so logs appear live, like django-tasks' `db_worker`); pass `--no-reload` in
production.
"""

from django.core.management.base import BaseCommand
from django.utils.autoreload import run_with_reloader

from modules.cron.registry import run_scheduler


class Command(BaseCommand):
    help = (
        "Run the scheduler loop — ticks once per minute "
        "(single active instance via a Postgres advisory lock)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-reload",
            action="store_false",
            dest="reload",
            help="Disable the autoreloader (use in production).",
        )

    def handle(self, *args, reload=True, **options):
        if reload:
            run_with_reloader(run_scheduler)
        else:
            run_scheduler()
