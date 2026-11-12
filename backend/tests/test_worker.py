"""The worker must pick up a job that was saved together with other data in one transaction."""

import pytest
from django.db import transaction
from procrastinate.contrib.django import app
from procrastinate.contrib.django.models import ProcrastinateJob

from apps.core.tasks import ping


@pytest.mark.django_db(transaction=True)
def test_deferred_job_is_executed_by_worker():
    with transaction.atomic():
        job_id = ping.defer(message="dzień dobry")

    assert ProcrastinateJob.objects.get(id=job_id).status == "todo"

    # Same connector as `manage.py procrastinate worker` uses in the worker container.
    worker_app = app.with_connector(app.connector.get_worker_connector())
    worker_app.run_worker(queues=["default"], wait=False, install_signal_handlers=False, listen_notify=False)

    assert ProcrastinateJob.objects.get(id=job_id).status == "succeeded"


@pytest.mark.django_db(transaction=True)
def test_job_is_not_queued_when_transaction_rolls_back():
    class Boom(Exception):
        pass

    jobs_before = ProcrastinateJob.objects.count()

    with pytest.raises(Boom), transaction.atomic():
        ping.defer(message="nie zapisze się")
        raise Boom

    assert ProcrastinateJob.objects.count() == jobs_before
