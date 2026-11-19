"""Background jobs of the assistant (queue `default`): calls to Claude never run inside an HTTP request."""

import logging

from procrastinate.contrib.django import app

from apps.assistant import services

logger = logging.getLogger(__name__)


@app.task(queue="default", name="assistant.interpret_text_request")
def interpret_text_request(request_id: str, text: str | None = None) -> str:
    status = services.interpret_request(request_id, text)
    logger.info("text request %s: %s", request_id, status)
    return status


@app.task(queue="default", name="assistant.plan_assistant_command")
def plan_assistant_command(command_id: str) -> str:
    status = services.run_command(command_id)
    logger.info("assistant command %s: %s", command_id, status)
    return status


@app.periodic(cron="*/10 * * * *")
@app.task(queue="default", name="assistant.fail_stale_messages")
def fail_stale_messages(timestamp: int) -> int:
    """Messages whose job was lost (worker down, deploy) never stay "being read": see `services.fail_stale_messages`."""
    count = services.fail_stale_messages()
    if count:
        logger.warning("assistant: %s stale messages failed", count)
    return count
