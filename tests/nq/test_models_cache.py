from datetime import date

import pytest

from backend.nq import cache
from backend.nq.models import NQUnavailable, parse_id_list, task_from_row


@pytest.mark.parametrize("raw,expected", [
    ("3", [3]), ("3,4", [3, 4]), ("4, 5", [4, 5]), (None, []), ("", []), ("a,7, ,x", [7]),
])
def test_parse_id_list(raw, expected):
    assert parse_id_list(raw) == expected


def _row(**kw):
    base = dict(id=1, project_id=1, task_status=1, is_complete="0",
                end_date=date(2026, 10, 9), assigned_to="3")
    base.update(kw)
    return base


def test_overdue_only_when_open_and_past_end():
    today = date(2026, 10, 14)
    assert task_from_row(_row(), today).is_overdue
    assert not task_from_row(_row(task_status=4, is_complete="1"), today).is_overdue
    assert not task_from_row(_row(end_date=date(2026, 10, 20)), today).is_overdue
    assert not task_from_row(_row(end_date=None), today).is_overdue


def test_done_is_status_4_or_is_complete():
    assert task_from_row(_row(task_status=4)).is_complete
    assert task_from_row(_row(is_complete="1")).is_complete
    assert not task_from_row(_row()).is_complete


def test_cache_hit_within_ttl_and_stale_fallback():
    cache.clear()
    calls = []
    now = [0.0]

    def loader():
        calls.append(1)
        return "v1"

    assert cache.cached("k", 60, loader, clock=lambda: now[0]) == "v1"
    now[0] = 30
    assert cache.cached("k", 60, loader, clock=lambda: now[0]) == "v1"
    assert len(calls) == 1                      # second call served from cache

    def broken():
        raise NQUnavailable("down")

    now[0] = 120                                # expired -> reload fails -> stale value
    assert cache.cached("k", 60, broken, clock=lambda: now[0]) == "v1"
    assert cache.data_may_be_stale()

    with pytest.raises(NQUnavailable):          # nothing cached for this key
        cache.cached("other", 60, broken, clock=lambda: now[0])
    cache.clear()
