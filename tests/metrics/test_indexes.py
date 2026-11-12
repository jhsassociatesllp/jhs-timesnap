import logging

from backend import indexes
from tests.metrics.conftest import mdb  # noqa: F401  (fixture)


def keys(coll):
    return {tuple(v["key"]) for v in coll.index_information().values()}


def test_ensure_all_creates_the_indexes_and_is_idempotent(mdb):
    indexes.ensure_all()
    indexes.ensure_all()
    assert (("employee_id", 1), ("date", 1)) in keys(mdb["c_entries"])
    assert (("employee_id", 1), ("cycle_id", 1)) in keys(mdb["c_entries"])
    assert (("project_code", 1),) in keys(mdb["c_entries"])
    sub = [v for v in mdb["c_submissions"].index_information().values() if v["key"] == [("employee_id", 1), ("date", 1)]]
    assert sub and sub[0].get("unique") is True
    assert (("job", 1), ("date", 1)) in keys(mdb["c_job_runs"]) and (("date", 1), ("employee_id", 1)) in {k[:2] for k in keys(mdb["m_team"])}


def test_a_blocked_unique_index_is_logged_not_raised(mdb, caplog):
    mdb["c_submissions"].insert_many([{"employee_id": "JHS9101", "date": "2026-10-12"},
                                      {"employee_id": "JHS9101", "date": "2026-10-12"}])     # duplicates
    with caplog.at_level(logging.WARNING, logger="indexes"):
        indexes.ensure_all()                                                                # must not raise
    assert any("not created" in r.message for r in caplog.records)
    unique = [v for v in mdb["c_submissions"].index_information().values() if v.get("unique") and v["key"] == [("employee_id", 1), ("date", 1)]]
    assert not unique                                                                       # the blocked unique index was not created
