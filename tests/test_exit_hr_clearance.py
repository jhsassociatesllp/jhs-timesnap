"""HR Clearance (the HR stage, done by the HR manager JHS1423 from the HR Clearance form) - throwaway database zz_exit_test.

JHS1423 manages T006 (a Reporting Manager like any other); T001 reports to M001, T004 to M002. JHS722 / JHS1474 / JHS1551 are the IT approvers.
"""
import pytest

from tests.test_exit_approvals import HR_KEYS, M, approve, hr_pass, it_pass, manager_pass, stage_states, submit_as  # noqa: F401
from tests.test_exit_management import EMPLOYEES, PNG, U, api, full_form, upload  # noqa: F401

H = f"{U}/hr/applications"


@pytest.fixture()
def hr(api):
    EMPLOYEES["JHS1423"] = {"EmpID": "JHS1423", "Emp Name": "Hr Boss", "Designation Name": "HR Manager ", "Branch Name": "Mumbai",
                            "ReportingEmpCode": "JHS01"}
    EMPLOYEES["T006"] = {"EmpID": "T006", "Emp Name": "Test Six", "Designation Name": "Analyst", "ReportingEmpCode": "JHS1423"}
    for j in ("JHS722", "JHS1474", "JHS1551"):
        EMPLOYEES[j] = {"EmpID": j, "Emp Name": j, "ReportingEmpCode": "M001"}
    EMPLOYEES["JHS01"] = {"EmpID": "JHS01", "Emp Name": "Top Boss"}
    yield api
    for k in ("JHS1423", "T006", "JHS722", "JHS1474", "JHS1551", "JHS01"):
        EMPLOYEES.pop(k, None)


def rows(option="Yes", remarks="ok"):
    return [{"key": k, "option": option, "remarks": remarks} for k in HR_KEYS]


def sig(api, fid, key, data=PNG):
    return api.post(f"{H}/{fid}/clearance/signature/{key}", files={"file": (f"{key}.png", data, "image/png")})


def to_hr(api, who="T001", mgr="M001"):
    fid = submit_as(api, who)
    manager_pass(api, fid, mgr)
    it_pass(api, fid)
    return fid


# 1, 2, 4: tabs / roles
def test_jhs1423_gets_exactly_the_four_tabs_and_hr_instead_of_it(hr):
    hr.as_user("JHS1423")
    r = hr.get(f"{U}/approver-status").json()
    assert r["is_reporting_manager"] is True and r["team_size"] == 1          # My Team Member Details + Employee Exit Applications
    assert r["is_hr_manager"] is True                                          # HR Clearance
    assert r["is_it_manager"] is False                                         # no IT Clearance tab
    assert hr.get(f"{U}/manager/dashboard").status_code == 200
    assert hr.get(f"{U}/it/dashboard").status_code == 403
    for j in ("JHS722", "JHS1474", "JHS1551"):                                 # IT access unchanged
        hr.as_user(j)
        r = hr.get(f"{U}/approver-status").json()
        assert r["is_it_manager"] is True and r["is_hr_manager"] is False
        assert hr.get(f"{U}/it/dashboard").status_code == 200 and hr.get(f"{U}/hr/dashboard").status_code == 403


# 3
def test_unauthorized_employees_cannot_access_hr_clearance(hr):
    fid = to_hr(hr)
    for who in ("T001", "T005", "X999", "M001", "JHS1191", "JHS722", "JHS1474", "JHS1551", "IT01"):
        hr.as_user(who)
        assert hr.get(f"{U}/approver-status").json()["is_hr_manager"] is False, who
        assert hr.get(f"{U}/hr/dashboard").status_code == 403, who
        assert hr.get(f"{H}/{fid}/clearance").status_code == 403, who
        assert hr.post(f"{H}/{fid}/clearance/draft", json={"items": rows()}).status_code == 403, who
        assert hr.post(f"{H}/{fid}/clearance/submit", json={"items": rows()}).status_code == 403, who
        assert hr.post(f"{H}/{fid}/reject", json={"reason": "not mine to reject"}).status_code == 403, who
        assert sig(hr, fid, "hr_sign").status_code == 403, who
    assert hr.col.find_one({})["approval"]["current_stage"] == "hr"


# 5-7
def test_dashboard_lists_all_submitted_forms_and_locks_by_stage(hr):
    f1 = submit_as(hr, "T001")                                               # RM pending
    f4 = submit_as(hr, "T004")
    manager_pass(hr, f4, "M002")                                             # RM + handover done, IT pending
    f5 = submit_as(hr, "T005")
    hr.as_user("M001")
    assert hr.post(f"{M}/{f5}/reject", json={"reason": "Not acceptable right now"}).status_code == 200
    f6 = submit_as(hr, "T006")
    manager_pass(hr, f6, "JHS1423")
    it_pass(hr, f6)                                                          # ready for HR
    hr.as_user("T002")
    hr.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "x"}})   # a draft is never listed
    hr.as_user("JHS1423")
    d = {a["employee_id"]: a for a in hr.get(f"{U}/hr/dashboard").json()["applications"]}
    assert set(d) == {"T001", "T004", "T005", "T006"}                          # every team, no drafts
    a = d["T006"]
    assert a["employee_name"] == "Test Six" and a["designation"] == "Analyst" and a["resignation_date"] and a["last_working_date"]
    assert (a["reporting_manager_status"], a["it_status"], a["hr_status"], a["action"]) == ("Approved", "Approved", "Pending", "fill")
    assert (d["T001"]["hr_status"], d["T001"]["action"]) == ("Waiting", None)
    assert (d["T004"]["reporting_manager_status"], d["T004"]["it_status"], d["T004"]["action"]) == ("Approved", "Pending", None)
    assert (d["T005"]["reporting_manager_status"], d["T005"]["hr_status"], d["T005"]["action"]) == ("Rejected", "Not applicable", None)
    for fid in (f1, f4, f5):                                                   # employees waiting on an earlier stage cannot proceed to HR
        assert hr.get(f"{H}/{fid}/clearance").status_code == 409
        assert hr.post(f"{H}/{fid}/clearance/submit", json={"items": rows()}).status_code == 409
        assert hr.post(f"{H}/{fid}/reject", json={"reason": "too early for HR"}).status_code == 409
    assert hr.get(f"{H}/{f6}/clearance").status_code == 200
    assert hr.col.count_documents({"status": "submitted"}) == 4                # still one document per employee


def test_hr_clearance_opens_only_after_it_clearance(hr):
    fid = submit_as(hr)
    manager_pass(hr, fid)
    hr.as_user("JHS1423")
    assert hr.get(f"{H}/{fid}/clearance").status_code == 409                   # IT clearance still pending
    it_pass(hr, fid)
    hr.as_user("JHS1423")
    assert hr.get(f"{H}/{fid}/clearance").status_code == 200


# 8-13
def test_answers_remarks_comments_and_signatures_save_and_complete_the_form(hr):
    fid = to_hr(hr)
    hr.as_user("JHS1423")
    g = hr.get(f"{H}/{fid}/clearance").json()
    assert [i["particular"] for i in g["items"]] == ["Served Notice Period", "Any Cash/Salary/Loan Adjustment Due?", "ERP ID Deletion"]
    assert g["declaration"].startswith("I hereby declare that I haven't joined any of JHS Client OR")
    assert g["editable"] is True and g["employee_signature"]["filename"]                     # the employee's own signature from the Exit Form
    assert hr.get(f"{H}/{fid}/clearance/signature/employee").status_code == 200
    # validation: only Yes / No
    assert hr.post(f"{H}/{fid}/clearance/draft", json={"items": [{"key": HR_KEYS[0], "option": "NA"}]}).status_code == 422
    assert hr.post(f"{H}/{fid}/clearance/draft", json={"items": [{"key": "nonsense", "option": "Yes"}]}).status_code == 422
    r = hr.post(f"{H}/{fid}/clearance/submit", json={"items": []})
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 3
    # save draft: answers, per-row remarks, HR comments
    body = {"items": [{"key": HR_KEYS[0], "option": "Yes", "remarks": "Served 60 days"}, {"key": HR_KEYS[1], "option": "No", "remarks": "Nothing due"},
                      {"key": HR_KEYS[2], "option": "Yes", "remarks": "Deleted today"}], "hr_comments": "Good luck"}
    assert hr.post(f"{H}/{fid}/clearance/draft", json=body).status_code == 200
    g = hr.get(f"{H}/{fid}/clearance").json()
    assert [(i["option"], i["remarks"]) for i in g["items"]] == [("Yes", "Served 60 days"), ("No", "Nothing due"), ("Yes", "Deleted today")]
    assert g["hr_comments"] == "Good luck"
    r = hr.post(f"{H}/{fid}/clearance/submit", json=body)
    assert r.status_code == 422 and "signature is required when the answer is Yes" in r.json()["detail"]["errors"][0]          # Yes rows, no signature yet
    assert sig(hr, fid, "nonsense").status_code == 404
    assert sig(hr, fid, HR_KEYS[0]).status_code == 201 and sig(hr, fid, "hr_sign").status_code == 201
    g = hr.get(f"{H}/{fid}/clearance").json()
    assert g["items"][0]["signature"] and g["hr_signature"] and not g["items"][1]["signature"]
    assert hr.get(f"{H}/{fid}/clearance/signature/hr_sign").status_code == 200
    assert sig(hr, fid, "hr_sign").status_code == 201                                                     # replace: old file removed
    assert hr.files.count_documents({"metadata.kind": "hr_clearance", "metadata.row_key": "hr_sign"}) == 1
    assert hr.delete(f"{H}/{fid}/clearance/signature/{HR_KEYS[0]}").json() == {"deleted": True}
    assert hr.delete(f"{H}/{fid}/clearance/signature/{HR_KEYS[0]}").status_code == 404
    r = hr.post(f"{H}/{fid}/clearance/submit", json=body)
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 2 and "Served Notice Period" in r.json()["detail"]["errors"][0]   # both Yes rows (1 and 3) are unsigned
    assert sig(hr, fid, HR_KEYS[0]).status_code == 201 and sig(hr, fid, HR_KEYS[2]).status_code == 201       # sign the two rows answered Yes (the middle row is No)
    r = hr.post(f"{H}/{fid}/clearance/submit", json=body)
    assert r.status_code == 201 and r.json() == {"submitted": True, "next_stage": "complete"}
    doc = hr.col.find_one({"employee_id": "T001"})
    hc, a = doc["hr_clearance"], doc["approval"]
    assert hc["status"] == "submitted" and hc["submitted_by"] == "JHS1423" and hc["hr_comments"] == "Good luck" and hc["hr_signature_file"]["gridfs_file_id"]
    assert a["hr"]["status"] == "approved" and a["hr"]["approver_code"] == "JHS1423" and a["hr"]["approved_at"]
    assert a["current_stage"] == "complete" and a["form_complete"]["status"] == "approved" and a["form_complete"]["completed_at"]
    # tracker
    assert stage_states(hr) == [("reporting_manager", "approved", "done"), ("it", "approved", "done"), ("hr", "approved", "done"), ("form_complete", "approved", "done")]
    assert hr.get(f"{U}/tracker").json()["complete"] is True
    # no duplicate / conflicting action afterwards
    hr.as_user("JHS1423")
    assert hr.post(f"{H}/{fid}/clearance/submit", json=body).status_code == 409
    assert hr.post(f"{H}/{fid}/reject", json={"reason": "changed my mind"}).status_code == 409
    assert hr.post(f"{H}/{fid}/clearance/draft", json=body).status_code == 409
    assert sig(hr, fid, "hr_sign").status_code == 409
    assert hr.get(f"{H}/{fid}/clearance").json()["editable"] is False
    assert hr.get(f"{U}/hr/dashboard").json()["applications"][0]["action"] == "view"
    # the employee can view the submitted HR signature, nobody else can
    hr.as_user("T001")
    assert hr.get(f"{H}/{fid}/clearance/signature/hr_sign").status_code == 200
    assert hr.get(f"{H}/{fid}/clearance").status_code == 403
    hr.as_user("T005")
    assert hr.get(f"{H}/{fid}/clearance/signature/hr_sign").status_code == 403


def test_hr_reject_saves_comments_and_status_and_the_tracker_shows_it(hr):
    fid = to_hr(hr)
    hr.as_user("JHS1423")
    assert hr.post(f"{H}/{fid}/reject", json={"reason": ""}).status_code == 422
    assert hr.post(f"{H}/{fid}/reject", json={"reason": "no"}).status_code == 422
    assert hr.get(f"{H}/{fid}/clearance").status_code == 200
    assert hr.post(f"{H}/{fid}/reject", json={"reason": "Notice period not served"}).status_code == 200
    doc = hr.col.find_one({})
    assert doc["approval"]["hr"]["status"] == "rejected" and doc["approval"]["hr"]["rejection_reason"] == "Notice period not served"
    assert doc["approval"]["hr"]["approver_code"] == "JHS1423" and doc["approval"]["hr"]["rejected_at"]
    assert doc["hr_clearance"]["hr_comments"] == "Notice period not served" and doc["approval"]["current_stage"] == "rejected"
    d = hr.get(f"{U}/hr/dashboard").json()["applications"][0]
    assert d["hr_status"] == "Rejected" and d["action"] == "view" and d["note"] == "Rejected by HR"
    assert hr.post(f"{H}/{fid}/clearance/submit", json={"items": rows()}).status_code == 409
    hr.as_user("T001")
    t = hr.get(f"{U}/tracker").json()
    assert t["rejected"] is True and t["complete"] is False
    s = {x["key"]: x for x in t["stages"]}
    assert s["hr"]["status"] == "rejected" and s["hr"]["rejection_reason"] == "Notice period not served"
    assert s["form_complete"]["state"] == "blocked" and s["it"]["state"] == "done"


def test_employees_cannot_approve_their_own_hr_clearance(hr):
    fid = to_hr(hr, "JHS1423", "JHS01")                                        # the HR manager's own exit form (his manager is JHS01)
    hr.as_user("JHS1423")
    assert hr.get(f"{H}/{fid}/clearance").status_code == 403
    assert hr.post(f"{H}/{fid}/clearance/submit", json={"items": rows()}).status_code == 403
    assert hr.post(f"{H}/{fid}/reject", json={"reason": "I reject myself"}).status_code == 403
    assert hr.get(f"{U}/hr/dashboard").json()["applications"] == []            # not even listed for himself
    assert hr.col.find_one({})["approval"]["current_stage"] == "hr"


def test_one_click_approval_no_longer_completes_the_hr_stage(hr):
    fid = to_hr(hr)
    for who in ("JHS1423", "JHS1191", "HR01", "IT01"):
        assert approve(hr, who, fid).status_code in (403, 409), who
    assert hr.col.find_one({})["approval"]["current_stage"] == "hr"
    hr_pass(hr, fid)
    assert hr.col.find_one({})["approval"]["current_stage"] == "complete"


def test_jhs911_is_an_hr_approver_with_exactly_two_tabs(hr):
    """JHS911 (HR Executive, reports to JHS1423, nobody reports to him): Employee Exit Form + HR Clearance only, like JHS1474 / JHS1551 for IT."""
    EMPLOYEES["JHS911"] = {"EmpID": "JHS911", "Emp Name": "Hr Exec", "Designation Name": "HR Executive", "ReportingEmpCode": "JHS1423"}
    try:
        fid = to_hr(hr)
        hr.as_user("JHS911")
        r = hr.get(f"{U}/approver-status").json()
        assert r["is_hr_manager"] is True                                      # HR Clearance tab
        assert r["is_reporting_manager"] is False                              # no My Team Member Details / Employee Exit Applications tabs
        assert r["is_it_manager"] is False and r["is_hr"] is False
        assert hr.get(f"{U}/manager/dashboard").status_code == 403
        assert hr.get(f"{U}/it/dashboard").status_code == 403
        assert [a["employee_id"] for a in hr.get(f"{U}/hr/dashboard").json()["applications"]] == ["T001"]    # every team, like JHS1423
        assert hr.post(f"{M}/{fid}/approve").status_code == 403                # no Reporting Manager rights
        hr_pass(hr, fid, "JHS911")                                             # completes HR Clearance for an employee of another team
        doc = hr.col.find_one({"employee_id": "T001"})
        assert doc["approval"]["hr"]["approver_code"] == "JHS911" and doc["hr_clearance"]["submitted_by"] == "JHS911"
        assert doc["approval"]["current_stage"] == "complete"
        hr.as_user("JHS1423")                                                  # no conflicting second approval
        assert hr.post(f"{H}/{fid}/clearance/submit", json={"items": rows()}).status_code == 409
        assert hr.post(f"{H}/{fid}/reject", json={"reason": "second opinion"}).status_code == 409
        # his own exit form is handled by the other HR approver, never by himself
        f911 = to_hr(hr, "JHS911", "JHS1423")
        hr.as_user("JHS911")
        assert hr.get(f"{H}/{f911}/clearance").status_code == 403
        assert hr.post(f"{H}/{f911}/reject", json={"reason": "reject myself"}).status_code == 403
        hr.as_user("JHS1423")
        assert hr.get(f"{H}/{f911}/clearance").status_code == 200
        hr.as_user("T005")                                                     # a normal employee gets nothing
        assert hr.get(f"{U}/hr/dashboard").status_code == 403
    finally:
        EMPLOYEES.pop("JHS911", None)


def test_access_comes_from_the_hr_clearance_approvers_collection(hr):
    coll = hr.col.database["hr_clearance_approvers"]
    assert coll.count_documents({}) == 0
    hr.as_user("JHS1423")
    assert hr.get(f"{U}/hr/dashboard").status_code == 200                        # first read seeds the two starting approvers
    assert sorted(d["empid"] for d in coll.find()) == ["JHS1423", "JHS911"] and all(d["active"] for d in coll.find())
    hr.as_user("T005")
    assert hr.get(f"{U}/hr/dashboard").status_code == 403
    coll.insert_one({"empid": "T005"})                                           # grant access in the collection
    assert hr.get(f"{U}/hr/dashboard").status_code == 200
    assert hr.get(f"{U}/approver-status").json()["is_hr_manager"] is True
    coll.update_one({"empid": "T005"}, {"$set": {"active": False}})              # revoke
    assert hr.get(f"{U}/hr/dashboard").status_code == 403
    assert hr.get(f"{U}/approver-status").json()["is_hr_manager"] is False
    coll.delete_one({"empid": "JHS911"})                                         # removing a person removes their access
    hr.as_user("JHS911")
    assert hr.get(f"{U}/hr/dashboard").status_code == 403
