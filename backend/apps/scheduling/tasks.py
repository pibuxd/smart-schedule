"""Background jobs of the scheduling app. Solver jobs run on the `solver` queue (a separate worker, 1–2 at once)."""

import logging

from procrastinate.contrib.django import app

from apps.scheduling import generation

logger = logging.getLogger(__name__)


@app.task(queue="solver", name="scheduling.solve_schedule")
def solve_schedule(run_id: str) -> str:
    run = generation.run_generation(run_id)
    if run is None:
        logger.warning("generation run %s does not exist", run_id)
        return "missing"
    logger.info("generation run %s: %s (%s, %s ms)", run.pk, run.status, run.solver_status, run.time_ms)
    return run.status


@app.periodic(cron="*/10 * * * *")
@app.task(queue="default", name="scheduling.fail_stale_runs")
def fail_stale_runs(timestamp: int) -> int:
    count = generation.fail_stale_runs()
    if count:
        logger.warning("marked %s stale generation runs as failed", count)
    return count
