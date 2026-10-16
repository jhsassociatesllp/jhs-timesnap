# backend/nq/cache.py
"""In-memory TTL cache for NQ reads, with stale fallback when NQ is down."""
import threading
import time
from typing import Callable, Optional

from backend.nq.models import NQUnavailable

_lock = threading.Lock()
_store: dict = {}                       # key -> (stored_at, value)
_state = {"stale_at": None}             # last time stale data was served
MAX_ENTRIES = 5000                      # bound memory; oldest entries are dropped first


def cached(key, ttl: int, loader: Callable, clock: Callable[[], float] = time.monotonic):
    """Return a fresh cached value, else load it. If loading raises NQUnavailable,
    serve the last cached value (marking data as possibly stale) or re-raise."""
    now = clock()
    with _lock:
        hit = _store.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        value = loader()
    except NQUnavailable:
        if hit:
            _state["stale_at"] = time.time()
            return hit[1]
        raise
    with _lock:
        _store[key] = (now, value)
        while len(_store) > MAX_ENTRIES:
            _store.pop(next(iter(_store)))
    return value


def clear() -> None:
    with _lock:
        _store.clear()
    _state["stale_at"] = None


def stale_since() -> Optional[float]:
    """Epoch seconds of the last stale-cache response, or None."""
    return _state["stale_at"]


def data_may_be_stale(window: int = 300) -> bool:
    """True if stale data was served recently -> show the
    'Project data may be out of date' banner."""
    ts = _state["stale_at"]
    return ts is not None and time.time() - ts < window
