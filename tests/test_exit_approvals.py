"""Exit approval workflow tests: Reporting Manager -> IT -> HR -> Form Complete.

The Reporting Manager stage now completes in two steps (approve the application, then submit the project handover
form - see test_exit_manager.py). IT and HR still approve with one click each, in order.

Shares the fixtures of test_exit_management.py (throwaway database zz_exit_test, stubbed employee records:
T001 reports to M001; T002 has no manager on record; IT01 is an IT approver; HR01 an HR approver;
JHS1191 is an owner; X999 is an ordinary colleague).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.exit_management import repository as repo
from backend.exit_management.routes import router
from tests.test_exit_management import PDF, PNG, U, api, full_form, upload  # noqa: F401  (api is a pytest fixture)

ROWS = ["confidential_files", "project_handover", "induction", "other_comments"]
M = f"{U}/manager/applications"


def submit_as(api, who="T001"):
    api.as_user(who)
    assert upload(api).status_code == 201
    r = api.post(f"{U}/submit", json=full_form())
    assert r.status_code == 201, r.text
    return str(api.col.find_one({"employee_id": who})["_id"])


def manager_pass(api, fid, mgr="M001"):
    """The whole Reporting Manager stage: approve the application, fill the handover form, upload 4 signatures, submit."""
    api.as_user(mgr)
    assert api.post(f"{M}/{fid}/approve").status_code == 200
    for key in ROWS:
        r = api.post(f"{M}/{fid}/handover/signature/{key}", files={"file": (f"{key}.png", PNG, "image/png")})
        assert r.status_code == 201, r.text
    items = [{"key": k, "option": "Yes", "remarks": "done"} for k in ROWS]
    r = api.post(f"{M}/{fid}/handover/submit", json={"items": items})
    assert r.status_code == 201, r.text


IT_KEYS = ['jhs_laptop', 'jhs_email_disabled', 'client_laptop', 'client_email_disabled', 'nexus_quant_id', 'msb_portal_id', 'work_data_handover', 'personal_email_removed', 'mobile_sim', 'biometric_access', 'hardware_devices', 'other_it_assets']


def it_pass(api, fid, mgr="JHS722"):
    """The IT stage: the IT manager (JHS722) fills in the IT Clearance form with signatures and submits it."""
    api.as_user(mgr)
    base = f"{U}/it/applications/{fid}/clearance"
    assert api.get(base).status_code == 200
    for k in IT_KEYS:
        assert api.post(f"{base}/signature/{k}", files={"file": (f"{k}.png", PNG, "image/png")}).status_code == 201
    r = api.post(f"{base}/submit", json={"items": [{"key": k, "option": "Yes", "remarks": "ok"} for k in IT_KEYS]})
    assert r.status_code == 201, r.text
    return r


HR_KEYS = ["notice_period", "cash_adjustment", "erp_deletion"]


def hr_pass(api, fid, mgr="JHS1423"):
    """The HR stage: the HR manager (JHS1423) fills in the HR Clearance form with signatures and submits it."""
    api.as_user(mgr)
    base = f"{U}/hr/applications/{fid}/clearance"
    assert api.get(base).status_code == 200
    for k in HR_KEYS + ["hr_sign"]:
        assert api.post(f"{base}/signature/{k}", files={"file": (f"{k}.png", PNG, "image/png")}).status_code == 201
    r = api.post(f"{base}/submit", json={"items": [{"key": k, "option": "Yes", "remarks": "ok"} for k in HR_KEYS], "hr_comments": "All clear"})
    assert r.status_code == 201, r.text
    return r


def approve(api, who, form_id):
    """IT / HR one-click approval of the current stage."""
    api.as_user(who)
    return api.post(f"{U}/approvals/{form_id}/approve")


def stage_states(api, who="T001"):
    api.as_user(who)
    return [(s["key"], s["status"], s["state"]) for s in api.get(f"{U}/tracker").json()["stages"]]


def test_submit_creates_approval_in_the_same_document(api):
    assert api.get(f"{U}/tracker").json() == {"submitted": False}
    submit_as(api)
    assert api.col.count_documents({}) == 1                                    # still ONE exist_form document
    a = api.col.find_one({})["approval"]
    assert a["current_stage"] == "reporting_manager"
    rm = a["reporting_manager"]
    assert rm["status"] == "pending" and rm["decision"] == "pending" and rm["expected_approver_code"] == "M001"
    assert rm["pending_since"] and a["it"]["pending_since"] is None
    assert a["it"]["status"] == a["hr"]["status"] == a["form_complete"]["status"] == "pending"


def test_tracker_shows_four_stages_in_order(api):
    submit_as(api)
    t = api.get(f"{U}/tracker").json()
    assert [s["label"] for s in t["stages"]] == ["Reporting Manager", "IT Clearance", "HR Clearance", "Form Complete"]
    assert stage_states(api) == [("reporting_manager", "pending", "active"), ("it", "pending", "waiting"),
                                 ("hr", "pending", "waiting"), ("form_complete", "pending", "waiting")]
    assert t["complete"] is False and t["rejected"] is False and t["submitted_at"]
    assert t["stages"][0]["expected_approver_name"] == "Boss One"


def test_full_workflow_in_order(api):
    fid = submit_as(api)
    manager_pass(api, fid)
    assert stage_states(api) == [("reporting_manager", "approved", "done"), ("it", "pending", "active"),
                                 ("hr", "pending", "waiting"), ("form_complete", "pending", "waiting")]
    assert approve(api, "IT01", fid).status_code == 403
    assert it_pass(api, fid).json()["next_stage"] == "hr"
    assert approve(api, "JHS1423", fid).status_code == 409                       # the HR stage is completed from the HR Clearance form
    r = hr_pass(api, fid).json()
    assert r["submitted"] is True and r["next_stage"] == "complete"
    assert stage_states(api) == [("reporting_manager", "approved", "done"), ("it", "approved", "done"),
                                 ("hr", "approved", "done"), ("form_complete", "approved", "done")]
    t = api.get(f"{U}/tracker").json()
    assert t["complete"] is True
    s = {x["key"]: x for x in t["stages"]}
    assert s["reporting_manager"]["approver_code"] == "M001" and s["reporting_manager"]["approver_name"] == "Manager One"
    assert s["it"]["approver_code"] == "JHS722" and s["hr"]["approver_code"] == "JHS1423"
    assert all(s[k]["approved_at"] for k in s) and s["it"]["pending_since"] and s["hr"]["pending_since"]
    doc = api.col.find_one({})
    assert doc["status"] == "submitted" and doc["signature_file"]["gridfs_file_id"]
    assert api.files.count_documents({}) == 1 + 4 + 12 + 4                                # employee signature + 4 handover rows + 12 IT rows + 4 HR signatures
    assert approve(api, "HR01", fid).status_code == 409                          # nothing more to approve


def test_it_and_hr_cannot_jump_ahead_of_the_manager_stage(api):
    fid = submit_as(api)
    assert approve(api, "IT01", fid).status_code == 409                          # manager stage is not finished
    assert approve(api, "HR01", fid).status_code == 409
    assert approve(api, "M001", fid).status_code == 409                          # the manager does not use this endpoint
    assert stage_states(api)[0] == ("reporting_manager", "pending", "active")
    assert api.col.find_one({})["approval"]["current_stage"] == "reporting_manager"
    manager_pass(api, fid)
    assert approve(api, "HR01", fid).status_code == 403                          # HR before IT
    assert approve(api, "M001", fid).status_code == 403                          # manager has no say at the IT stage
    assert stage_states(api)[1:3] == [("it", "pending", "active"), ("hr", "pending", "waiting")]


def test_employee_cannot_approve_own_form(api):
    fid = submit_as(api)
    api.as_user("T001")
    assert api.post(f"{M}/{fid}/approve").status_code == 403                     # not even the manager endpoints
    manager_pass(api, fid)
    repo.approvers.insert_one({"stage": "it", "empid": "T001"})                  # even an IT approver cannot approve own form
    r = approve(api, "T001", fid)
    assert r.status_code == 403
    assert stage_states(api)[1] == ("it", "pending", "active")


def test_owner_account_can_approve_it_and_hr(api):
    fid = submit_as(api)
    manager_pass(api, fid)
    assert approve(api, "JHS1191", fid).status_code == 403                       # only the IT manager completes the IT stage
    it_pass(api, fid)
    assert approve(api, "JHS1191", fid).status_code == 403                       # nor do the owners approve HR any more
    hr_pass(api, fid)
    api.as_user("T001")
    assert api.get(f"{U}/tracker").json()["complete"] is True


def test_queue_roles_and_visibility(api):
    fid = submit_as(api)
    api.as_user("M001")
    assert api.get(f"{U}/approver-status").json() == {
        "is_reporting_manager": True, "team_size": 2, "pending_applications": 1, "is_it": False, "is_hr": False, "is_approver": False,
        "is_it_manager": False, "it_team_size": 0, "is_hr_manager": False}
    assert api.get(f"{U}/approvals").status_code == 403                          # managers use the manager dashboard
    api.as_user("IT01")
    assert api.get(f"{U}/approvals").json()["items"] == []                       # not IT's turn yet
    manager_pass(api, fid)
    api.as_user("IT01")
    assert api.get(f"{U}/approvals").json()["items"] == []                       # IT stage is JHS722's (IT Clearance dashboard)
    api.as_user("HR01")
    assert api.get(f"{U}/approvals").json()["items"] == []
    api.as_user("X999")
    assert api.get(f"{U}/approver-status").json()["is_approver"] is False
    assert api.get(f"{U}/approvals").status_code == 403
    api.as_user("T001")                                                          # the employee is not an approver of their own form
    assert api.get(f"{U}/approver-status").json()["is_approver"] is False


def test_review_hides_feedback_from_manager_but_not_from_hr(api):
    fid = submit_as(api)
    manager_pass(api, fid)
    api.as_user("M001")
    r = api.get(f"{U}/approvals/{fid}").json()
    assert r["employee_name"] == "Test One" and r["employee_details"]["last_working_date"] == "2026-12-01"
    assert r["feedback_visible"] is False and "exit_interview" not in r and "manager_feedback" not in r
    assert r["can_approve_now"] is False
    api.as_user("HR01")
    r = api.get(f"{U}/approvals/{fid}").json()
    assert r["feedback_visible"] is True and r["exit_interview"]["resignation_reason"] == "c"
    assert r["can_approve_now"] is False                                         # HR can look, but it is not HR's turn
    assert [i["option"] for i in r["project_handover"]["items"]] == ["Yes"] * 4  # IT / HR can read the handover form
    assert all(i["signature"]["filename"] for i in r["project_handover"]["items"])
    for who in ("X999", "T001"):
        api.as_user(who)
        assert api.get(f"{U}/approvals/{fid}").status_code == 403
    api.as_user("HR01")
    assert api.get(f"{U}/approvals/not-an-id").status_code == 404


def test_no_manager_on_record_falls_back_to_hr(api):
    fid = submit_as(api, "T002")
    assert api.col.find_one({"employee_id": "T002"})["approval"]["reporting_manager"]["expected_approver_code"] == ""
    api.as_user("M001")
    assert api.post(f"{M}/{fid}/approve").status_code == 403
    api.as_user("IT01")
    assert api.post(f"{M}/{fid}/approve").status_code == 403
    api.as_user("HR01")
    assert api.post(f"{M}/{fid}/approve").status_code == 200


def test_approval_endpoints_require_login():
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    for method, path in (("get", "/tracker"), ("get", "/approver-status"), ("get", "/approvals"),
                         ("get", "/approvals/abc"), ("post", "/approvals/abc/approve"), ("get", "/manager/dashboard"),
                         ("post", "/manager/applications/abc/approve"), ("get", "/manager/applications/abc/handover")):
        assert getattr(c, method)(U + path).status_code in (401, 403), path


def test_draft_forms_have_no_approval_and_cannot_be_approved(api):
    api.as_user("T001")
    api.post(f"{U}/draft", json={})
    fid = str(api.col.find_one({})["_id"])
    assert "approval" not in api.col.find_one({})
    assert approve(api, "IT01", fid).status_code == 404
    api.as_user("M001")
    assert api.post(f"{M}/{fid}/approve").status_code == 404
