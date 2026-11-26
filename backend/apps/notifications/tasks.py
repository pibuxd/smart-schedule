"""Push notifications to the apps (queue `default`): see `apps/notifications/push.py`."""

import logging

from procrastinate.contrib.django import app

from apps.notifications import push

logger = logging.getLogger(__name__)


@app.task(queue="default", name="notifications.send_push")
def send_push(notification_ids: list[str]) -> int:
    sent = push.deliver(notification_ids)
    logger.info("push: %s of %s notifications sent to phones", sent, len(notification_ids))
    return sent
