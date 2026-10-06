"""Sending work to the Celery workers by task name, so the API never imports worker code.

Enqueueing is best-effort: callers get False when the queue is off or unreachable and
then do the work by hand or inline. Nothing in the report loop depends on the queue.
"""

import logging
from functools import lru_cache

from celery import Celery

from jamii_api.config import get_settings

log = logging.getLogger("jamii.tasks")


@lru_cache
def _client() -> Celery:
    app = Celery("jamii-api", broker=get_settings().redis_url)
    app.conf.update(
        broker_connection_timeout=2,
        broker_connection_retry=False,
        broker_connection_max_retries=0,
        task_publish_retry=False,
        broker_transport_options={"socket_connect_timeout": 2, "socket_timeout": 2},
    )
    return app


def enqueue_many(name: str, arg_lists: list[list]) -> bool:
    if not get_settings().queue_enabled:
        return False
    try:
        app = _client()
        with app.producer_or_acquire() as producer:
            for args in arg_lists:
                app.send_task(name, args=args, producer=producer)
        return True
    except Exception as e:  # the broker is down: fall back to doing it by hand
        log.warning("enqueue %s failed: %s", name, e)
        return False


def enqueue(name: str, *args) -> bool:
    return enqueue_many(name, [list(args)])
