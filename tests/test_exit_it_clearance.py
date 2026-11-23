"""IT Clearance (IT stage for IT-team employees, done by their IT manager) - throwaway database zz_exit_test.

Stub data: IT manager ITM1 has team [T001, T004] in `exit_approvers` ({stage: it, empid: ITM1, team: [...]}). T001 reports to M001,
T004 to M002, T005 is NOT on the IT team. IT01 is a general IT approver, HR01 an HR approver.
"""
import pytest

from tests.test_exit_approvals import M, approve, manager_pass, stage_states, submit_as  # noqa: F401
from tests.test_exit_management import EMPLOYEES, PNG, PDF, U, api, full_form, upload  # noqa: F401

I = f"{U}/it/applications"
KEYS = ['jhs_laptop', 'jhs_email_disabled', 'client_laptop', 'client_email_disabled', 'nexus_quant_id', 'msb_portal_id', 'work_data_handover', 'personal_email_removed', 'mobile_sim', 'biometric_access', 'hardware_devices', 'other_it_assets']


@pytest.fixture()
def it(api):
    EMPLOYEES["ITM1"] = {"EmpID": "ITM1", "Emp Name": "It Manager", "Designation Name": "Sr IT Executive"}
    api.col.database["it_clearance_approvers"].insert_one({"empid": "ITM1", "active": True})
    yield api
    EMPLOYEES.pop("ITM1", None)


def rows(option="Yes", remarks="ok"):
    return [{"key": k, "option": option, "remarks": remarks} for k in KEYS]


def sig(api, fid, key, data=PNG, name=None, ctype="image/png"):
    return api.post(f"{I}/{fid}/clearance/signature/{key}", files={"file": (name or f"{key}.png", data, ctype)})


def to_it(api, who="T001", mgr="M001"):
    fid = submit_as(api, who)
    manager_pass(api, fid, mgr)
    return fid


def test_it_manager_dashboard_lists_only_the_it_team_submitted_forms(it):
    it.as_user("ITM1")
    d = it.get(f"{U}/it/dashboard").json()
    assert d["manager"]["name"] == "It Manager" and d["applications"] == []
    it.as_user("T005"); it.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "x"}})      # a draft is never listed
    submit_as(it, "T001"); submit_as(it, "T004"); submit_as(it, "T002")  # different Reporting Managers / none at all
    it.as_user("ITM1")
    apps = it.get(f"{U}/it/dashboard").json()["applications"]
    assert sorted(a["employee_id"] for a in apps) == ["T001", "T002", "T004"]
    a = [x for x in apps if x["employee_id"] == "T001"][0]
    assert a["reporting_manager_status"] == "Pending" and a["it_status"] == "Waiting" and a["action"] is None
    assert a["resignation_date"] and a["last_working_date"] and a["designation"] == "Consultant"


def test_nobody_else_has_the_it_dashboard(it):
    for who in ("T001", "IT01", "HR01", "JHS1191", "M001"):
        it.as_user(who)
        assert it.get(f"{U}/it/dashboard").status_code == 403
        assert it.get(f"{U}/approver-status").json()["is_it_manager"] is False
    it.as_user("ITM1")
    r = it.get(f"{U}/approver-status").json()
    assert r["is_it_manager"] is True and r["is_it"] is False and r["is_reporting_manager"] is False


def test_clearance_cannot_open_before_manager_approval_and_handover(it):
    fid = submit_as(it)
    it.as_user("ITM1")
    assert it.get(f"{I}/{fid}/clearance").status_code == 409
    it.as_user("M001")
    assert it.post(f"{M}/{fid}/approve").status_code == 200            # approved, handover NOT submitted yet
    it.as_user("ITM1")
    assert it.get(f"{I}/{fid}/clearance").status_code == 409
    assert it.post(f"{I}/{fid}/clearance/submit", json={"items": rows()}).status_code == 409
    assert it.col.find_one({})["approval"]["current_stage"] == "reporting_manager"


def test_rejected_application_never_reaches_it(it):
    fid = submit_as(it)
    it.as_user("M001")
    assert it.post(f"{M}/{fid}/reject", json={"reason": "Not acceptable at this time"}).status_code == 200
    it.as_user("ITM1")
    assert it.get(f"{I}/{fid}/clearance").status_code == 409
    d = it.get(f"{U}/it/dashboard").json()["applications"][0]
    assert d["it_status"] == "Not applicable" and d["action"] is None and "Rejected" in d["note"]


def test_full_flow_it_manager_completes_clearance_and_hr_becomes_pending(it):
    fid = to_it(it)
    assert stage_states(it) == [("reporting_manager", "approved", "done"), ("it", "pending", "active"),
                                ("hr", "pending", "waiting"), ("form_complete", "pending", "waiting")]
    it.as_user("ITM1")
    d = it.get(f"{U}/it/dashboard").json()["applications"][0]
    assert d["reporting_manager_status"] == "Approved" and d["it_status"] == "Pending" and d["action"] == "fill"
    g = it.get(f"{I}/{fid}/clearance").json()
    assert [i["particular"] for i in g["items"]] == [
        "JHS Laptop Returned", "Official JHS Email ID Disabled", "Client Laptop Returned", "Client Email ID Disabled", "Nexus Quant ID Disabled",
        "MSB Portal ID Disabled", "All Official Work Data Handover", "Personal Email ID & Official Email Removed from JHS Mumbai Advisory",
        "Mobile Number / Official SIM Returned or Deactivated (if applicable)", "JHS Biometric Access Disabled",
        "Hardware Devices Returned (CDs, Hard Disk, Pen Drive, Dongle, Headset, etc.)", "Other IT Assets Returned"]
    assert g["editable"] is True and g["employee"]["employee_id"] == "T001"
    assert it.col.count_documents({}) == 1                              # still ONE document
    # incomplete: no Yes/No, no signature
    r = it.post(f"{I}/{fid}/clearance/submit", json={"items": []})
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 12
    assert it.post(f"{I}/{fid}/clearance/draft", json={"items": rows("No", "later")}).status_code == 200
    r = it.post(f"{I}/{fid}/clearance/submit", json={"items": rows()})
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 12 and "signature is required when the answer is Yes" in r.json()["detail"]["errors"][0]
    assert it.col.find_one({})["approval"]["current_stage"] == "it"
    for k in KEYS:
        assert sig(it, fid, k).status_code == 201
    r = it.post(f"{I}/{fid}/clearance/submit", json={"items": [{"key": k, "option": "Yes" if i % 2 == 0 else "No", "remarks": f"r{i}"} for i, k in enumerate(KEYS)]})
    assert r.status_code == 201 and r.json() == {"submitted": True, "next_stage": "hr"}
    doc = it.col.find_one({})
    ic, a = doc["it_clearance"], doc["approval"]
    assert ic["status"] == "submitted" and ic["approver_id"] == "ITM1" and ic["submitted_at"]
    assert [(i["option"], i["remarks"]) for i in ic["items"]] == [("Yes" if i % 2 == 0 else "No", f"r{i}") for i in range(12)]
    assert all(i["signature_file"]["gridfs_file_id"] for i in ic["items"])
    assert a["it"]["status"] == "approved" and a["it"]["approver_code"] == "ITM1" and a["current_stage"] == "hr" and a["hr"]["pending_since"]
    assert stage_states(it) == [("reporting_manager", "approved", "done"), ("it", "approved", "done"),
                                ("hr", "pending", "active"), ("form_complete", "pending", "waiting")]
    # read-only afterwards
    it.as_user("ITM1")
    assert it.post(f"{I}/{fid}/clearance/draft", json={"items": rows()}).status_code == 409
    assert sig(it, fid, "hardware_devices").status_code == 409
    assert it.post(f"{I}/{fid}/clearance/submit", json={"items": rows()}).status_code == 409
    assert it.get(f"{I}/{fid}/clearance").json()["editable"] is False
    assert it.get(f"{U}/it/dashboard").json()["applications"][0]["action"] == "view"


def test_only_the_it_manager_can_touch_the_clearance(it):
    fid = to_it(it)
    for who in ("T001", "T005", "T004", "IT01", "HR01", "JHS1191", "M001", "M002", "X999"):
        it.as_user(who)
        assert it.get(f"{I}/{fid}/clearance").status_code == 403, who
        assert it.post(f"{I}/{fid}/clearance/draft", json={"items": rows()}).status_code == 403, who
        assert it.post(f"{I}/{fid}/clearance/submit", json={"items": rows()}).status_code == 403, who
        assert sig(it, fid, "hardware_devices").status_code == 403, who
        assert it.delete(f"{I}/{fid}/clearance/signature/hardware_devices").status_code == 403, who
    # the one-click IT approval is not available for IT-team employees: not for owners / general IT, and not for the IT manager either
    for who, code in (("IT01", 403), ("JHS1191", 403), ("ITM1", 409)):
        assert approve(it, who, fid).status_code == code, who
    assert it.col.find_one({})["approval"]["current_stage"] == "it"


def test_junior_employees_see_only_their_own_status_and_details(it):
    fid = to_it(it)
    it.as_user("T001")
    t = it.get(f"{U}/tracker").json()
    assert t["it_clearance"] is None or t["it_clearance"]["status"] in ("draft",)           # nothing visible yet
    assert [s["label"] for s in t["stages"]] == ["Reporting Manager", "IT Clearance", "HR Clearance", "Form Complete"]
    it.as_user("ITM1")
    for k in KEYS:
        sig(it, fid, k)
    assert it.post(f"{I}/{fid}/clearance/submit", json={"items": rows("Yes", "returned")}).status_code == 201
    it.as_user("T001")
    ic = it.get(f"{U}/tracker").json()["it_clearance"]
    assert ic["status"] == "submitted" and [i["option"] for i in ic["items"]] == ["Yes"] * 12 and ic["items"][0]["remarks"] == "returned"
    assert all(i["has_signature"] for i in ic["items"])
    assert it.get(f"{U}/it/dashboard").status_code == 403 and it.get(f"{I}/{fid}/clearance").status_code == 403
    assert it.get(f"{I}/{fid}/clearance/signature/hardware_devices").status_code == 200          # own submitted clearance file
    it.as_user("T005")
    assert it.get(f"{I}/{fid}/clearance/signature/hardware_devices").status_code == 403           # someone else's


def test_row_signatures_are_individual_and_checked(it):
    fid = to_it(it)
    it.as_user("ITM1")
    assert it.get(f"{I}/{fid}/clearance").status_code == 200
    assert sig(it, fid, "nonsense").status_code == 404
    assert sig(it, fid, "jhs_laptop").status_code == 201
    assert sig(it, fid, "client_email_disabled", PDF, "e.pdf", "application/pdf").status_code == 201
    g = {i["key"]: i for i in it.get(f"{I}/{fid}/clearance").json()["items"]}
    assert g["jhs_laptop"]["signature"] and g["client_email_disabled"]["signature"] and not g["hardware_devices"]["signature"]
    first = g["jhs_laptop"]["signature"]["file_id"]
    assert sig(it, fid, "jhs_laptop", PDF, "n.pdf", "application/pdf").status_code == 201        # replace
    files = list(it.files.find({"metadata.kind": "it_clearance", "metadata.row_key": "jhs_laptop"}))
    assert len(files) == 1 and files[0]["filename"] == "n.pdf" and str(files[0]["_id"]) != first
    assert it.delete(f"{I}/{fid}/clearance/signature/client_email_disabled").json() == {"deleted": True}
    assert it.files.count_documents({"metadata.kind": "it_clearance"}) == 1
    assert it.chunks.count_documents({}) == it.files.count_documents({})
    assert it.delete(f"{I}/{fid}/clearance/signature/hardware_devices").status_code == 404


def test_every_employees_it_clearance_is_locked_until_their_own_manager_and_handover(it):
    """ITM1 sees everyone; each employee's IT Clearance opens only after THAT employee's Reporting Manager approved + handover."""
    f1 = submit_as(it, "T001")                                          # M001: stays pending
    f4 = submit_as(it, "T004")                                          # M002: approved + handover done
    manager_pass(it, f4, "M002")
    f5 = submit_as(it, "T005")                                          # M001: rejected
    it.as_user("M001")
    assert it.post(f"{M}/{f5}/reject", json={"reason": "Not acceptable right now"}).status_code == 200
    f2 = submit_as(it, "T002")                                          # no manager on record: HR approves the application
    it.as_user("HR01")
    assert it.post(f"{M}/{f2}/approve").status_code == 200              # decision approved, handover still pending
    it.as_user("ITM1")
    d = {a["employee_id"]: a for a in it.get(f"{U}/it/dashboard").json()["applications"]}
    assert set(d) == {"T001", "T002", "T004", "T005"}
    assert (d["T001"]["reporting_manager_status"], d["T001"]["action"]) == ("Pending", None)
    assert (d["T005"]["reporting_manager_status"], d["T005"]["action"]) == ("Rejected", None)
    assert (d["T002"]["reporting_manager_status"], d["T002"]["handover_status"], d["T002"]["action"]) == ("Approved - handover pending", "Pending", None)
    assert (d["T004"]["reporting_manager_status"], d["T004"]["handover_status"], d["T004"]["action"]) == ("Approved", "Completed", "fill")
    for fid in (f1, f2, f5):
        assert it.get(f"{I}/{fid}/clearance").status_code == 409
        assert it.post(f"{I}/{fid}/clearance/submit", json={"items": rows()}).status_code == 409
    assert it.get(f"{I}/{f4}/clearance").status_code == 200
    for k in KEYS:
        assert sig(it, f4, k).status_code == 201
    assert it.post(f"{I}/{f4}/clearance/submit", json={"items": rows()}).status_code == 201
    d = {a["employee_id"]: a for a in it.get(f"{U}/it/dashboard").json()["applications"]}
    assert d["T004"]["it_status"] == "Approved" and d["T004"]["action"] == "view"
    # nobody else gets IT approval, not even owners or general IT approvers
    for who in ("IT01", "JHS1191", "HR01", "M001"):
        it.as_user(who)
        assert it.get(f"{U}/it/dashboard").status_code == 403
    it.as_user("IT01")
    assert it.get(f"{U}/approvals").json()["items"] == []


def test_jhs722_and_his_juniors_work_without_any_database_record(api):
    """The IT manager (JHS722) and juniors (JHS1474, JHS1551) are known by employee ID; exit_approvers is not needed."""
    assert api.col.database["exit_approvers"].count_documents({"stage": "it", "team": {"$exists": True}}) == 0
    EMPLOYEES["JHS722"] = {"EmpID": "JHS722", "Emp Name": "It Boss"}
    for j in ("JHS1474", "JHS1551"):
        EMPLOYEES[j] = {"EmpID": j, "Emp Name": j, "ReportingEmpCode": "M001"}
    try:
        api.as_user("JHS722")
        assert api.get(f"{U}/it/dashboard").json()["manager"]["team_size"] == 2
        fid = to_it(api, "JHS1474")
        api.as_user("JHS1474")
        assert api.get(f"{U}/manager/dashboard").status_code == 403                # IT approvers, but no Reporting Manager dashboard
        api.as_user("JHS722")
        assert api.get(f"{I}/{fid}/clearance").status_code == 200
        api.as_user("IT01")
        assert api.get(f"{U}/approvals").json()["items"] == []
    finally:
        for k in ("JHS722", "JHS1474", "JHS1551"):
            EMPLOYEES.pop(k, None)


def test_jhs722_is_also_a_reporting_manager_for_his_juniors(api):
    """JHS722 gets the Reporting Manager dashboard for JHS1474 / JHS1551 as well as IT Clearance, in the strict order."""
    EMPLOYEES["JHS722"] = {"EmpID": "JHS722", "Emp Name": "It Boss", "Designation Name": "Sr IT Executive"}
    for j in ("JHS1474", "JHS1551"):
        EMPLOYEES[j] = {"EmpID": j, "Emp Name": j, "Designation Name": "Executive IT", "ReportingEmpCode": "M001"}
    try:
        api.as_user("JHS722")
        r = api.get(f"{U}/approver-status").json()
        assert r["is_reporting_manager"] is True and r["is_it_manager"] is True and r["team_size"] == 2
        d = api.get(f"{U}/manager/dashboard").json()
        assert [t["employee_id"] for t in d["team"]] == ["JHS1474", "JHS1551"] and d["manager"]["total_team_members"] == 2
        fid = submit_as(api, "JHS1474")
        api.as_user("JHS722")
        apps = api.get(f"{U}/manager/dashboard").json()["applications"]
        assert [a["employee_id"] for a in apps] == ["JHS1474"] and apps[0]["can_decide"] is True      # sees submitted applications only
        assert api.get(f"{U}/it/dashboard").json()["applications"][0]["action"] is None              # IT not available yet
        assert api.get(f"{I}/{fid}/clearance").status_code == 409
        assert api.post(f"{M}/{fid}/approve").status_code == 200                                    # approves as Reporting Manager
        assert api.get(f"{I}/{fid}/clearance").status_code == 409                                   # handover still pending
        for k in ("confidential_files", "project_handover", "induction", "other_comments"):
            assert api.post(f"{M}/{fid}/handover/signature/{k}", files={"file": (f"{k}.png", PNG, "image/png")}).status_code == 201
        items = [{"key": k, "option": "Yes", "remarks": "ok"} for k in ("confidential_files", "project_handover", "induction", "other_comments")]
        assert api.post(f"{M}/{fid}/handover/submit", json={"items": items}).status_code == 201
        assert api.get(f"{U}/it/dashboard").json()["applications"][0]["action"] == "fill"
        assert api.get(f"{I}/{fid}/clearance").status_code == 200
        # the junior and the other junior get no manager access
        for j in ("JHS1474", "JHS1551"):
            api.as_user(j)
            assert api.get(f"{U}/manager/dashboard").status_code == 403
        # the manager in the employee's record (M001) keeps working too
        api.as_user("M001")
        assert api.get(f"{U}/manager/dashboard").status_code == 200
    finally:
        for k in ("JHS722", "JHS1474", "JHS1551"):
            EMPLOYEES.pop(k, None)


def test_it_manager_can_reject_with_a_reason_and_hr_never_starts(it):
    fid = to_it(it)
    it.as_user("T001")
    assert it.post(f"{I}/{fid}/reject", json={"reason": "Return the laptop first"}).status_code == 403
    it.as_user("ITM1")
    assert it.post(f"{I}/{fid}/reject", json={"reason": ""}).status_code == 422
    assert it.post(f"{I}/{fid}/reject", json={"reason": "no"}).status_code == 422
    assert it.post(f"{I}/{fid}/reject", json={"reason": "Return the laptop first"}).status_code == 200
    a = it.col.find_one({})["approval"]
    assert a["it"]["status"] == "rejected" and a["it"]["rejection_reason"] == "Return the laptop first" and a["current_stage"] == "rejected"
    d = it.get(f"{U}/it/dashboard").json()["applications"][0]
    assert d["it_status"] == "Rejected" and d["reporting_manager_status"] == "Approved" and d["action"] is None and d["note"] == "Rejected by IT"
    assert it.post(f"{I}/{fid}/reject", json={"reason": "Again please"}).status_code == 409
    it.as_user("T001")
    t = it.get(f"{U}/tracker").json()
    assert t["rejected"] is True
    s = {x["key"]: x for x in t["stages"]}
    assert s["it"]["status"] == "rejected" and s["it"]["rejection_reason"] == "Return the laptop first"
    assert s["hr"]["state"] == "blocked" and s["reporting_manager"]["state"] == "done"
    it.as_user("HR01")
    assert it.post(f"{U}/approvals/{fid}/approve").status_code == 409


def test_it_reject_is_only_possible_on_its_turn(it):
    fid = submit_as(it)                                                 # Reporting Manager still pending
    it.as_user("ITM1")
    assert it.post(f"{I}/{fid}/reject", json={"reason": "Too early to reject"}).status_code == 409
    assert it.col.find_one({})["approval"]["current_stage"] == "reporting_manager"


def test_draft_endpoint_is_json_safe_after_handover_and_it_clearance(it):
    """GET /draft returns the whole stored form; GridFS ObjectIds nested in project_handover / it_clearance must be strings."""
    fid = to_it(it)
    it.as_user("ITM1")
    for k in KEYS:
        sig(it, fid, k)
    assert it.post(f"{I}/{fid}/clearance/submit", json={"items": rows()}).status_code == 201
    it.as_user("T001")
    for path in ("/draft", "/submission-status", "/tracker"):
        r = it.get(f"{U}{path}")
        assert r.status_code == 200, (path, r.text)
    form = it.get(f"{U}/draft").json()["form"]
    assert isinstance(form["project_handover"]["items"][0]["signature_file"]["gridfs_file_id"], str)
    assert isinstance(form["it_clearance"]["items"][0]["signature_file"]["gridfs_file_id"], str)
    assert isinstance(form["approval"]["reporting_manager"]["pending_since"], str)


def test_jhs1474_and_jhs1551_are_it_approvers_but_not_reporting_managers(api):
    """Both get exactly the form + IT Clearance tabs: IT approval for every employee, no Reporting Manager rights."""
    for j in ("JHS722", "JHS1474", "JHS1551"):
        EMPLOYEES[j] = {"EmpID": j, "Emp Name": j, "Designation Name": "IT", "ReportingEmpCode": "M001"}
    try:
        fid = to_it(api, "T001")
        for j in ("JHS1474", "JHS1551"):
            api.as_user(j)
            r = api.get(f"{U}/approver-status").json()
            assert r["is_it_manager"] is True and r["is_reporting_manager"] is False and r["is_it"] is False and r["is_hr"] is False
            assert api.get(f"{U}/manager/dashboard").status_code == 403
            assert api.post(f"{M}/{fid}/approve").status_code == 403 and api.post(f"{M}/{fid}/reject", json={"reason": "not allowed"}).status_code == 403
            assert [a["employee_id"] for a in api.get(f"{U}/it/dashboard").json()["applications"]] == ["T001"]
        # locked before the employee's own manager + handover
        f4 = submit_as(api, "T004")
        api.as_user("JHS1551")
        assert api.get(f"{I}/{f4}/clearance").status_code == 409
        # JHS1474 starts, JHS1551 completes: one approval, with the real approver recorded
        api.as_user("JHS1474")
        assert api.get(f"{I}/{fid}/clearance").status_code == 200
        for k in KEYS:
            assert sig(api, fid, k).status_code == 201
        api.as_user("JHS1551")
        g = api.get(f"{I}/{fid}/clearance").json()
        assert g["manager_name"] == "JHS1551" and g["items"][10]["signature"]                      # sees the shared draft
        assert api.post(f"{I}/{fid}/clearance/submit", json={"items": rows()}).status_code == 201
        doc = api.col.find_one({"employee_id": "T001"})
        assert doc["it_clearance"]["submitted_by"] == "JHS1551" and doc["approval"]["it"]["approver_code"] == "JHS1551" and doc["approval"]["it"]["approved_at"]
        assert doc["approval"]["current_stage"] == "hr"
        # no conflicting second approval or reject
        api.as_user("JHS1474")
        assert api.post(f"{I}/{fid}/clearance/submit", json={"items": rows()}).status_code == 409
        assert api.post(f"{I}/{fid}/reject", json={"reason": "too late to reject"}).status_code == 409
        # JHS1474's own form is handled by the others, never by himself
        f74 = to_it(api, "JHS1474")
        api.as_user("JHS1474")
        assert api.get(f"{I}/{f74}/clearance").status_code == 403
        api.as_user("JHS1551")
        assert api.get(f"{I}/{f74}/clearance").status_code == 200
        # a normal employee gets nothing
        api.as_user("T005")
        assert api.get(f"{U}/it/dashboard").status_code == 403 and api.get(f"{I}/{fid}/clearance").status_code == 403
    finally:
        for k in ("JHS722", "JHS1474", "JHS1551"):
            EMPLOYEES.pop(k, None)


def test_access_comes_from_the_it_clearance_approvers_collection(api):
    coll = api.col.database["it_clearance_approvers"]
    assert coll.count_documents({}) == 0
    api.as_user("JHS722")
    assert api.get(f"{U}/it/dashboard").status_code == 200                       # first read seeds the three starting approvers
    assert sorted(d["empid"] for d in coll.find()) == ["JHS1474", "JHS1551", "JHS722"]
    api.as_user("T005")
    assert api.get(f"{U}/it/dashboard").status_code == 403
    coll.insert_one({"empid": "T005"})                                           # grant access in the collection
    assert api.get(f"{U}/it/dashboard").status_code == 200
    assert api.get(f"{U}/approver-status").json()["is_it_manager"] is True
    coll.update_one({"empid": "T005"}, {"$set": {"active": False}})              # revoke
    assert api.get(f"{U}/it/dashboard").status_code == 403
    assert api.get(f"{U}/approver-status").json()["is_it_manager"] is False
    coll.delete_one({"empid": "JHS1551"})                                        # removing a person removes their access
    api.as_user("JHS1551")
    assert api.get(f"{U}/it/dashboard").status_code == 403
    assert api.get(f"{U}/approver-status").json()["is_it_manager"] is False


def test_na_is_an_allowed_option_and_only_one_option_per_row(it):
    fid = to_it(it)
    it.as_user("ITM1")
    assert it.get(f"{I}/{fid}/clearance").status_code == 200
    bad = it.post(f"{I}/{fid}/clearance/draft", json={"items": [{"key": KEYS[0], "option": "Maybe"}]})
    assert bad.status_code == 422                                                   # only Yes / No / NA
    items = [{"key": k, "option": ("NA" if i % 3 == 0 else "Yes" if i % 3 == 1 else "No"), "remarks": ""} for i, k in enumerate(KEYS)]
    assert it.post(f"{I}/{fid}/clearance/draft", json={"items": items}).status_code == 200
    got = [i["option"] for i in it.get(f"{I}/{fid}/clearance").json()["items"]]
    assert got == [x["option"] for x in items] and "NA" in got
    assert it.post(f"{I}/{fid}/clearance/submit", json={"items": items}).status_code == 422          # the Yes rows have no signature yet
    for k in KEYS:
        assert sig(it, fid, k).status_code == 201
    assert it.post(f"{I}/{fid}/clearance/submit", json={"items": items}).status_code == 201
    assert it.col.find_one({})["it_clearance"]["items"][0]["option"] == "NA"
    it.as_user("T001")
    assert it.get(f"{U}/tracker").json()["it_clearance"]["items"][0]["option"] == "NA"
    it.as_user("ITM1")
    assert it.post(f"{I}/{fid}/clearance/draft", json={"items": [{"key": "laptop_system", "option": "Yes"}]}).status_code in (409, 422)


def test_a_draft_started_with_the_old_questions_is_upgraded(it):
    fid = to_it(it)
    old = [{"key": k, "particular": k, "option": "Yes", "remarks": "", "signature_file": None}
           for k in ("laptop_system", "software_id_card", "email_deletion", "hardware")]
    it.col.update_one({}, {"$set": {"it_clearance": {"approver_id": "ITM1", "status": "draft", "items": old}}})
    it.as_user("ITM1")
    g = it.get(f"{I}/{fid}/clearance").json()
    assert [i["key"] for i in g["items"]] == KEYS and all(i["option"] is None for i in g["items"])
    assert it.col.count_documents({}) == 1 and it.col.find_one({})["it_clearance"]["status"] == "draft"
