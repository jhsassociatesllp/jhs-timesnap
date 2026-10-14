"""KRA Manager → Partner approval workflow — API-level tests on an in-memory Mongo.

Run:  python -m pytest tests/test_kra_approval.py -q
"""
import os

# Never touch a real DB: set before backend.database is imported (load_dotenv doesn't override).
os.environ["MONGO_CONNECTION_STRING"] = "mongodb://localhost:1/?serverSelectionTimeoutMS=100"

import mongomock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.appraisal import router as R
from backend.auth import get_current_user

QID = "KRA_TEST_Q"


@pytest.fixture()
def env(monkeypatch):
    db = mongomock.MongoClient()["t"]
    for name in ("employee_details_collection", "appraisal_collection", "appraisal_admin_collection",
                 "appraisal_cycles_collection", "appraisal_eligibility_collection",
                 "reporting_managers_collection"):
        monkeypatch.setattr(R, name, db[name])
    db.appraisal_cycles_collection.insert_one({"quarter_id": QID, "quarter_label": "Q", "status": "live"})

    def emp(eid, mgr, partner, grade="Staff"):
        return {"EmpID": eid, "Emp Name": eid, "Designation Name": "Associate", "Grade Name": grade,
                "ReportingEmpCode": mgr, "PartnerEmpCode": partner}
    db.employee_details_collection.insert_many([
        emp("E1", "M1", "P1"),            # different manager & partner
        emp("E2", "X", "X"),              # manager == partner
        emp("E3", "M1", "P2"),            # outside P1's hierarchy
        emp("M1", "P1", "P1"),            # manager whose own manager is the partner
        emp("P1", "", "", "PnD"), emp("P2", "", "", "PnD"), emp("X", "", "", "PnD"),
    ])
    db.reporting_managers_collection.insert_many([{"ReportingEmpCode": c} for c in ("M1", "X", "P1")])

    app = FastAPI()
    app.include_router(R.router)
    user = {"id": "E1"}
    app.dependency_overrides[get_current_user] = lambda: user["id"]
    client = TestClient(app)

    def as_(uid):
        user["id"] = uid
        return client

    def submit(eid):
        r = db.appraisal_collection.insert_one({
            "employeeId": eid, "employeeName": eid, "quarter_id": QID, "status": "submitted",
            "answers": {}, "selfScore": 1, "selfMaxScore": 2, "selfPercentage": 50})
        return str(r.inserted_id)

    def status(rid):
        from bson import ObjectId
        return db.appraisal_collection.find_one({"_id": ObjectId(rid)})["status"]

    return as_, submit, status


def ids(resp):
    d = resp.json()
    return sorted(r["employeeId"] for r in d.get("data", []) + d.get("employees", []) + d.get("tls", []))


def act(c, kind, rid, action="approve"):
    return c.post(f"/appraisal/{kind}/action/{rid}", json={"action": action})


def test_normal_flow_manager_then_partner(env):
    as_, submit, status = env
    rid = submit("E1")
    assert ids(as_("M1").get("/appraisal/tl/pending")) == ["E1"]
    assert ids(as_("P1").get("/appraisal/pnd/pending")) == []          # partner cannot see yet
    assert act(as_("M1"), "tl", rid).status_code == 200
    assert status(rid) == "TL_approved"
    assert ids(as_("P1").get("/appraisal/pnd/pending")) == ["E1"]
    assert as_("P1").get(f"/appraisal/pnd/record/{rid}").status_code == 200
    assert act(as_("P1"), "pnd", rid).status_code == 200
    assert status(rid) == "PnD_approved"


def test_partner_blocked_before_manager_approval_api(env):
    as_, submit, status = env
    rid = submit("E1")
    c = as_("P1")
    assert c.get(f"/appraisal/pnd/record/{rid}").status_code == 403
    assert act(c, "pnd", rid).status_code == 403
    assert act(c, "pnd", rid, "reject").status_code == 403
    assert c.get("/appraisal/analysis/kra/E1").status_code == 403
    assert c.get("/appraisal/review/E1").status_code == 403
    assert status(rid) == "submitted"


def test_manager_rejects_partner_cannot_act(env):
    as_, submit, status = env
    rid = submit("E1")
    assert act(as_("M1"), "tl", rid, "reject").status_code == 200
    assert status(rid) == "TL_rejected"
    assert ids(as_("P1").get("/appraisal/pnd/pending")) == []
    assert act(as_("P1"), "pnd", rid).status_code == 403
    assert as_("P1").get(f"/appraisal/pnd/record/{rid}").status_code == 403


def test_manager_equals_partner_single_approval(env):
    as_, submit, status = env
    rid = submit("E2")
    c = as_("X")
    assert ids(c.get("/appraisal/pnd/pending")) == ["E2"]
    assert ids(c.get("/appraisal/tl/pending")) == []                   # shown only once
    assert act(c, "pnd", rid).status_code == 200
    assert status(rid) == "PnD_approved"                               # completed, no 2nd step
    assert ids(c.get("/appraisal/pnd/pending")) == []
    assert ids(c.get("/appraisal/tl/pending")) == []


def test_manager_equals_partner_via_manager_endpoint_is_final(env):
    as_, submit, status = env
    rid = submit("E2")
    assert act(as_("X"), "tl", rid).status_code == 200
    assert status(rid) == "PnD_approved"


def test_unauthorized_partner_and_manager(env):
    as_, submit, status = env
    r3 = submit("E3")
    assert act(as_("M1"), "tl", r3).status_code == 200                 # E3 manager approves
    assert status(r3) == "TL_approved"
    c = as_("P1")                                                      # P1 is not E3's partner
    assert ids(c.get("/appraisal/pnd/pending")) == []
    assert c.get(f"/appraisal/pnd/record/{r3}").status_code == 403
    assert act(c, "pnd", r3).status_code == 403
    assert c.get("/appraisal/analysis/kra/E3").status_code == 403
    r1 = submit("E1")
    assert act(as_("P2"), "tl", r1).status_code == 403                 # not E1's manager
    assert as_("P2").get(f"/appraisal/tl/record/{r1}").status_code == 403


def test_partner_role_cannot_bypass_manager_check(env):
    """Old code skipped the hierarchy check for partner/admin roles on /tl/*."""
    as_, submit, status = env
    rid = submit("E1")
    assert act(as_("P1"), "tl", rid).status_code == 403
    assert as_("P1").get(f"/appraisal/tl/record/{rid}").status_code == 403
    assert status(rid) == "submitted"


def test_manager_who_is_also_employee_partner_stage(env):
    """M1 (a manager) has own KRA; their manager P1 is also their partner → single approval."""
    as_, submit, status = env
    rid = submit("M1")
    assert ids(as_("P1").get("/appraisal/pnd/pending")) == ["M1"]
    assert act(as_("P1"), "pnd", rid).status_code == 200
    assert status(rid) == "PnD_approved"


def test_review_endpoint_no_longer_open_to_everyone(env):
    as_, submit, _ = env
    submit("E1")
    assert as_("E1").get("/appraisal/review/E1").status_code == 200
    assert as_("M1").get("/appraisal/review/E1").status_code == 200
    assert as_("E3").get("/appraisal/review/E1").status_code == 403
