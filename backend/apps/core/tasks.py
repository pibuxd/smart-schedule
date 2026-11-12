"""Background tasks of the core app. Real work (solver, LLM) arrives in later stages."""

import logging

from procrastinate.contrib.django import app

logger = logging.getLogger(__name__)


@app.task(queue="default", name="core.ping")
def ping(message: str) -> str:
    """Smoke-test task proving that the worker picks up jobs from the queue."""
    logger.info("ping task received: %s", message)
    return message
