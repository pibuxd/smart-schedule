"""Housekeeping for login data."""

import logging
from datetime import timedelta

from django.utils import timezone
from procrastinate.contrib.django import app

from apps.accounts.models import LoginCode

logger = logging.getLogger(__name__)


@app.periodic(cron="17 3 * * *")
@app.task(queue="default", name="accounts.delete_old_login_codes")
def delete_old_login_codes(timestamp: int) -> int:
    """Login codes matter for 5 minutes and for the hourly limits; after a day they are only clutter."""
    deleted, _ = LoginCode.objects.filter(created_at__lt=timezone.now() - timedelta(days=1)).delete()
    logger.info("deleted %s old login codes", deleted)
    return deleted
