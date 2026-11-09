# backend/nq/health.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from backend.auth import get_current_user
from backend.nq import cache, repository
from backend.nq.models import NQUnavailable

router = APIRouter(prefix="/api/health", tags=["Health"])


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None


@router.get("/nq")
async def nq_health(current_user: str = Depends(get_current_user)):
    """Is Nexus Quant reachable? Returns latency and the last successful read."""
    try:
        latency_ms = round(repository.ping() * 1000, 1)
        reachable = True
    except NQUnavailable:
        latency_ms, reachable = None, False
    return {
        "reachable": reachable,
        "latency_ms": latency_ms,
        "last_success": _iso(repository.last_success()),
        "data_may_be_stale": cache.data_may_be_stale(),
    }
