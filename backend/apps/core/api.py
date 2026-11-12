from django.db import connection
from ninja import Router, Schema
from ninja.responses import Status

router = Router(tags=["system"])


class HealthOut(Schema):
    status: str
    database: str


@router.get("/health", response={200: HealthOut, 503: HealthOut}, auth=None)
def health(request):
    """Liveness + database check, used by Docker Compose and Caddy."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return Status(503, HealthOut(status="error", database="unavailable"))
    return Status(200, HealthOut(status="ok", database="ok"))
