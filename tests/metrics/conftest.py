"""Metrics tests: scratch Mongo (27018, db 'timesnap_test') + the seeded fake NQ MySQL (3308)."""
import pytest

from backend.metrics.store import mstore
from tests.cycle.conftest import cdb, entry          # noqa: F401  (fixtures / helpers re-exported)
from tests.nq.conftest import nq_db, nq_down         # noqa: F401


@pytest.fixture
def mdb(cdb, monkeypatch):
    """cdb (timesheet collections) + scratch aggregate collections."""
    for attr, coll in (("hours", "m_hours"), ("projects", "m_projects"), ("daily", "m_daily"),
                       ("team", "m_team"), ("legacy", "m_legacy"), ("payroll_cycles", "m_payroll_cycles")):
        cdb[coll].drop()
        monkeypatch.setattr(mstore, attr, cdb[coll])
    return cdb
