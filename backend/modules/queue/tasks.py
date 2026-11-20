import logging
import time

from django.tasks import task

logger = logging.getLogger(__name__)


@task()
def ping(message: str = "pong", delay_seconds: float = 0) -> str:
    """A task that does nothing, to see the worker pick one up: Tasks › Queue
    enqueues it. Waits `delay_seconds` (to see it running), logs and returns
    `message`."""
    time.sleep(delay_seconds)
    logger.info("ping: %s", message)
    return message
