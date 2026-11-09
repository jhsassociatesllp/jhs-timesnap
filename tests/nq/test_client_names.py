"""Real NQ stores the client's tbl_client id in tbl_projects.client_name; the name itself is company_name."""
from tests.nq.conftest import nq_db  # noqa: F401  (fixture)


def test_numeric_client_ids_resolve_to_the_client_name_and_text_is_kept(nq_db):
    assert nq_db.get_project("PL-T001").client_name == "Test Client A"        # stored as '1'
    assert nq_db.get_project("PL-T003").client_name == "Test Client B"        # stored as '2'
    assert nq_db.get_project("PL-T002").client_name == "Test Client A"        # plain text row keeps working


def test_task_and_bulk_reads_carry_the_resolved_client_name(nq_db):
    tasks = nq_db.get_tasks_for_employee("JHS9101", __import__("datetime").date(2026, 10, 14))
    assert tasks and all(t.client_name in ("Test Client A", "Test Client B") for t in tasks)
    assert {p.client_name for p in nq_db.list_active_projects()} <= {"Test Client A", "Test Client B"}
