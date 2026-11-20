from datetime import datetime
from typing import Literal

from django.db import connection
from django.db.utils import OperationalError
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router, Schema

router = Router()


class HealthOut(Schema):
    status: Literal["ok"]
    # Server clock (UTC): spots clock drift and cached responses.
    time: datetime


class HealthDbOut(Schema):
    status: Literal["ok", "error"]


# No rate limit: load balancers and Playwright poll it, and it must answer
# without the database (the throttles count in the cache table, which may not
# exist yet before the first migrate).
@router.get("/health", response=HealthOut, tags=["health"], throttle=[])
def health(request: HttpRequest):
    return {"status": "ok", "time": timezone.now()}


# Readiness: 200 only when the database answers, so a load balancer stops
# sending traffic to an instance that lost it. /health stays the liveness check.
@router.get(
    "/health-db",
    response={200: HealthDbOut, 503: HealthDbOut},
    tags=["health"],
    throttle=[],
)
def health_db(request: HttpRequest):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return 503, {"status": "error"}
    return {"status": "ok"}
