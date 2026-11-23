"""Reporting Manager dashboard + project handover form tests (throwaway database zz_exit_test).

Stub data (see test_exit_management.py): M001 manages T001 and T005; M002 manages T004; T002 has no manager on record.
"""
import io

import pytest
from PIL import Image

from tests.test_exit_approvals import M, ROWS, approve, manager_pass, stage_states, submit_as  # noqa: F401
from tests.test_exit_management import EMPLOYEES, MB5, PDF, PNG, U, api, full_form, make_pdf, upload  # noqa: F401


def dash(api, who):
    api.as_user(who)
    return api.get(f"{U}/manager/dashboard")


def sig(api, fid, key, data=PNG, name=None, ctype="image/png"):
    return api.post(f"{M}/{fid}/handover/signature/{key}", files={"file": (name or f"{key}.png", data, ctype)})


def open_handover(api, fid, mgr="M001"):
    api.as_user(mgr)
    assert api.post(f"{M}/{fid}/approve").status_code == 200


def items(option="Yes", remarks="ok"):
    return [{"key": k, "option": option, "remarks": remarks} for k in ROWS]


# ── 1-4: automatic manager detection, team, submitted applications only ───────
def test_manager_detected_automatically_from_the_login(api):
    r = dash(api, "M001")
    assert r.status_code == 200
    m = r.json()["manager"]
    assert m["employee_id"] == "M001" and m["name"] == "Manager One" and m["total_team_members"] == 2
    api.as_user("M002")
    assert api.get(f"{U}/manager/dashboard").json()["manager"]["name"] == "Manager Two"      # no id was ever sent
    assert api.get(f"{U}/manager/dashboard", params={"manager_id": "M001"}).json()["manager"]["name"] == "Manager Two"


def test_non_managers_have_no_dashboard(api):
    for who in ("X999", "T001", "IT01"):
        assert dash(api, who).status_code == 403
    assert dash(api, "NOBODY").status_code == 404                                    # no employee record at all


def test_team_members_are_exactly_the_people_reporting_to_the_manager(api):
    d = dash(api, "M001").json()
    assert [t["employee_id"] for t in d["team"]] == ["T005", "T001"]                 # sorted by name; T004 is not here
    assert d["manager"]["total_team_members"] == len(d["team"]) == 2
    t1 = d["team"][1]
    assert t1["name"] == "Test One" and t1["designation"] == "Consultant" and t1["joining_date"] == "2024-10-07"
    assert t1["has_exit_application"] is False
    d2 = dash(api, "M002").json()
    assert [t["employee_id"] for t in d2["team"]] == ["T004"] and d2["manager"]["total_team_members"] == 1


def test_department_is_not_invented(api, monkeypatch):
    m = dash(api, "M001").json()["manager"]
    assert m["department"] == "" and m["department_available"] is False             # the employee data has no department
    monkeypatch.setitem(EMPLOYEES["M001"], "Department", "Audit")                     # ...but one would be picked up if added
    m = dash(api, "M001").json()["manager"]
    assert m["department"] == "Audit" and m["department_available"] is True


def test_only_submitted_applications_of_the_team_are_listed(api):
    assert dash(api, "M001").json()["applications"] == []
    api.as_user("T001")
    api.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "x"}})     # a draft is not an application
    assert dash(api, "M001").json()["applications"] == []
    submit_as(api, "T001")
    submit_as(api, "T004")                                                          # another manager's employee
    d = dash(api, "M001").json()
    assert [a["employee_id"] for a in d["applications"]] == ["T001"]                # not T005 (no form), not T004
    a = d["applications"][0]
    assert a["employee_name"] == "Test One" and a["designation"] == "Consultant"
    assert a["resignation_date"] == "2026-11-01" and a["last_working_date"] == "2026-12-01" and a["submitted_at"]
    assert a["application_status"] == "Pending your review" and a["can_decide"] is True
    assert [t["has_exit_application"] for t in d["team"]] == [False, True]
    assert d["pending_count"] == 1
    assert [x["employee_id"] for x in dash(api, "M002").json()["applications"]] == ["T004"]


# ── 5-6: reject ───────────────────────────────────────────────────────────────
def test_reject_saves_reason_and_shows_rejected_to_the_employee(api):
    fid = submit_as(api)
    api.as_user("M001")
    assert api.post(f"{M}/{fid}/reject", json={"reason": ""}).status_code == 422             # a reason is required
    assert api.post(f"{M}/{fid}/reject", json={"reason": "no"}).status_code == 422
    assert api.post(f"{M}/{fid}/reject", json={"reason": "Handover of the audit files is not planned yet"}).status_code == 200
    rm = api.col.find_one({})["approval"]["reporting_manager"]
    assert rm["status"] == "rejected" and rm["decision"] == "rejected" and rm["rejected_at"]
    assert rm["rejection_reason"] == "Handover of the audit files is not planned yet" and rm["decided_by_code"] == "M001"
    assert api.col.find_one({})["approval"]["current_stage"] == "rejected"
    # employee's tracker
    api.as_user("T001")
    t = api.get(f"{U}/tracker").json()
    assert t["rejected"] is True and t["complete"] is False
    s = {x["key"]: x for x in t["stages"]}
    assert s["reporting_manager"]["status"] == "rejected" and s["reporting_manager"]["state"] == "rejected"
    assert s["reporting_manager"]["rejection_reason"] == "Handover of the audit files is not planned yet"
    assert s["reporting_manager"]["rejected_at"]
    assert [s[k]["state"] for k in ("it", "hr", "form_complete")] == ["blocked"] * 3          # IT and HR never start
    assert [s[k]["status"] for k in ("it", "hr", "form_complete")] == ["pending"] * 3
    assert s["it"]["pending_since"] is None
    # nothing can proceed
    assert approve(api, "IT01", fid).status_code == 409 and approve(api, "HR01", fid).status_code == 409
    api.as_user("IT01")
    assert api.get(f"{U}/approvals").json()["items"] == []
    api.as_user("M001")
    assert api.post(f"{M}/{fid}/approve").status_code == 409                                  # decided: cannot change its mind
    assert api.post(f"{M}/{fid}/reject", json={"reason": "again again"}).status_code == 409
    assert api.get(f"{M}/{fid}/handover").status_code == 409                                  # no handover form for a rejected one
    a = api.get(f"{U}/manager/dashboard").json()["applications"][0]
    assert a["application_status"] == "Rejected" and a["can_decide"] is False and a["can_handover"] is False
    assert api.col.count_documents({}) == 1


# ── 7: approve opens the handover form ────────────────────────────────────────
def test_approve_opens_handover_form_but_does_not_complete_the_stage(api):
    fid = submit_as(api)
    api.as_user("M001")
    assert api.get(f"{M}/{fid}/handover").status_code == 409                                  # not opened yet
    r = api.post(f"{M}/{fid}/approve")
    assert r.status_code == 200 and r.json() == {"decision": "approved", "form_id": fid}
    doc = api.col.find_one({})
    rm = doc["approval"]["reporting_manager"]
    assert rm["decision"] == "approved" and rm["decided_at"] and rm["decided_by_code"] == "M001"
    assert rm["status"] == "pending" and doc["approval"]["current_stage"] == "reporting_manager"    # stage NOT approved yet
    assert doc["approval"]["it"]["pending_since"] is None
    assert doc["project_handover"]["status"] == "draft" and len(doc["project_handover"]["items"]) == 4
    # the employee sees: still with the Reporting Manager, handover pending
    api.as_user("T001")
    s = api.get(f"{U}/tracker").json()["stages"]
    assert s[0]["status"] == "pending" and s[0]["state"] == "active" and "handover form" in s[0]["detail"]
    assert s[1]["state"] == "waiting"
    # the form shows the employee's details automatically
    api.as_user("M001")
    h = api.get(f"{M}/{fid}/handover").json()
    assert h["employee"]["name"] == "Test One" and h["employee"]["employee_id"] == "T001"
    assert h["manager_name"] == "Manager One" and len(h["form_date"]) == 10 and h["editable"] is True
    assert [i["particular"] for i in h["items"]] == [
        "Return of all confidential files and information", "Project Related Details Handover",
        "Induction given to the replacement (if any)", "Any other comments"]
    assert all(i["option"] is None and i["signature"] is None for i in h["items"])
    a = api.get(f"{U}/manager/dashboard").json()["applications"][0]
    assert a["application_status"] == "Approved - handover form pending" and a["can_handover"] is True
    # IT cannot act yet
    assert approve(api, "IT01", fid).status_code == 409
    assert api.col.count_documents({}) == 1


# ── 8-11: the four rows are independent ───────────────────────────────────────
def test_rows_have_independent_options_remarks_and_signatures(api):
    fid = submit_as(api)
    open_handover(api, fid)
    r = api.post(f"{M}/{fid}/handover/draft", json={"items": [
        {"key": "confidential_files", "option": "Yes", "remarks": "All returned"},
        {"key": "induction", "option": "No", "remarks": "Not applicable"}]})
    assert r.status_code == 200
    s1 = sig(api, fid, "project_handover").json()
    s2 = sig(api, fid, "other_comments", PDF, "notes.pdf", "application/pdf").json()
    assert s1["file_id"] != s2["file_id"] and s2["content_type"] == "application/pdf"
    h = {i["key"]: i for i in api.get(f"{M}/{fid}/handover").json()["items"]}
    assert (h["confidential_files"]["option"], h["confidential_files"]["remarks"]) == ("Yes", "All returned")
    assert (h["induction"]["option"], h["induction"]["remarks"]) == ("No", "Not applicable")
    assert h["project_handover"]["option"] is None and h["other_comments"]["option"] is None
    assert h["confidential_files"]["signature"] is None and h["induction"]["signature"] is None
    assert h["project_handover"]["signature"]["file_id"] == s1["file_id"]
    assert h["other_comments"]["signature"]["filename"] == "notes.pdf"
    # GridFS: one file per row, linked to this form and row, nothing embedded in the document
    files = {f["metadata"]["row_key"]: f for f in api.files.find({"metadata.kind": "handover"})}
    assert set(files) == {"project_handover", "other_comments"}
    f = files["project_handover"]
    assert f["metadata"]["employee_id"] == "T001" and f["metadata"]["uploaded_by"] == "M001"
    assert str(f["metadata"]["form_id"]) == fid and f["metadata"]["content_type"] == "image/png" and f["length"] == len(PNG)
    doc = api.col.find_one({})
    ref = doc["project_handover"]["items"][1]["signature_file"]
    assert ref["gridfs_file_id"] == f["_id"] and ref["file_size"] == len(PNG) and ref["uploaded_at"]
    assert not any(isinstance(v, (bytes,)) for v in ref.values())


def test_remove_signature_affects_only_that_row(api):
    fid = submit_as(api)
    open_handover(api, fid)
    for k in ROWS:
        assert sig(api, fid, k).status_code == 201
    assert api.files.count_documents({"metadata.kind": "handover"}) == 4
    assert api.delete(f"{M}/{fid}/handover/signature/induction").json() == {"deleted": True}
    h = {i["key"]: i for i in api.get(f"{M}/{fid}/handover").json()["items"]}
    assert h["induction"]["signature"] is None
    assert all(h[k]["signature"] for k in ROWS if k != "induction")
    assert api.files.count_documents({"metadata.kind": "handover"}) == 3             # its GridFS file is gone, others stay
    assert api.chunks.count_documents({}) == api.files.count_documents({})
    assert api.delete(f"{M}/{fid}/handover/signature/induction").status_code == 404
    assert api.delete(f"{M}/{fid}/handover/signature/nonsense").status_code == 404
    # a row may stay unsigned, but at least one signed row is needed to submit
    for k in ROWS:
        if k != "induction":
            assert api.delete(f"{M}/{fid}/handover/signature/{k}").status_code == 200
    r = api.post(f"{M}/{fid}/handover/submit", json={"items": items()})
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 4 and all("signature is required when the answer is Yes" in e for e in r.json()["detail"]["errors"])
    r = api.post(f"{M}/{fid}/handover/submit", json={"items": items("No")})        # nothing answered Yes, but still nobody signed
    assert r.status_code == 422 and r.json()["detail"]["errors"] == ["Upload your signature and tick it for at least one row"]
    assert api.col.find_one({})["approval"]["current_stage"] == "reporting_manager"


def test_replacing_a_row_signature_cleans_up_the_old_file(api):
    fid = submit_as(api)
    open_handover(api, fid)
    first = sig(api, fid, "induction").json()
    second = sig(api, fid, "induction", PDF, "new.pdf", "application/pdf").json()
    assert first["file_id"] != second["file_id"]
    rows = list(api.files.find({"metadata.row_key": "induction"}))
    assert len(rows) == 1 and rows[0]["filename"] == "new.pdf"
    assert api.chunks.count_documents({}) == api.files.count_documents({})


def test_row_signature_upload_rules(api):
    fid = submit_as(api)
    open_handover(api, fid)
    before = api.files.count_documents({})
    for name, data, ctype in (("a.pdf", PDF, "application/pdf"), ("b.jpg", None, "image/jpeg"), ("c.jpeg", None, "image/jpeg"),
                              ("d.png", PNG, "image/png")):
        if data is None:
            buf = io.BytesIO(); Image.new("RGB", (30, 20), "white").save(buf, "JPEG"); data = buf.getvalue()
        assert sig(api, fid, "confidential_files", data, name, ctype).status_code == 201, name
    assert sig(api, fid, "confidential_files", make_pdf(MB5), "exact.pdf", "application/pdf").status_code == 201      # exactly 5 MB
    n = api.files.count_documents({"metadata.kind": "handover"})
    assert sig(api, fid, "confidential_files", make_pdf(MB5 + 1), "big.pdf", "application/pdf").status_code == 413
    assert sig(api, fid, "confidential_files", b"MZ" + b"\x00" * 100, "virus.exe", "application/octet-stream").status_code == 415
    assert sig(api, fid, "confidential_files", b"MZ" + b"\x00" * 100, "virus.pdf", "application/pdf").status_code == 415
    assert sig(api, fid, "confidential_files", b"", "empty.png", "image/png").status_code == 400
    assert sig(api, fid, "confidential_files", b"hello", "x.txt", "text/plain").status_code == 415
    assert sig(api, fid, "not_a_row").status_code == 404
    assert api.files.count_documents({"metadata.kind": "handover"}) == n == 1         # failures leave nothing behind; replace kept one


# ── 12-13: submission completes the Reporting Manager stage and starts IT ─────
def test_submitting_the_handover_form_completes_the_stage_and_starts_it(api):
    fid = submit_as(api)
    open_handover(api, fid)
    api.post(f"{M}/{fid}/handover/draft", json={"items": items("No", "later")})
    # incomplete submissions are refused and change nothing
    r = api.post(f"{M}/{fid}/handover/submit", json={"items": items()})
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 4               # Yes everywhere, no signatures: each row needs one
    for k in ROWS:
        sig(api, fid, k)
    r = api.post(f"{M}/{fid}/handover/submit", json={"items": [{"key": "confidential_files", "option": None}]})
    assert r.status_code == 422 and "choose Yes or No" in r.json()["detail"]["errors"][0]
    assert api.col.find_one({})["approval"]["current_stage"] == "reporting_manager"
    # complete it
    sub = [{"key": ROWS[0], "option": "Yes", "remarks": "Completed"}, {"key": ROWS[1], "option": "Yes", "remarks": "Completed"},
           {"key": ROWS[2], "option": "No", "remarks": "Not applicable"}, {"key": ROWS[3], "option": "Yes", "remarks": "No additional comments"}]
    r = api.post(f"{M}/{fid}/handover/submit", json={"items": sub})
    assert r.status_code == 201 and r.json() == {"submitted": True, "next_stage": "it"}
    doc = api.col.find_one({})
    ph, a = doc["project_handover"], doc["approval"]
    assert ph["status"] == "submitted" and ph["submitted_at"] and ph["submitted_by"] == "M001"
    assert [(i["option"], i["remarks"]) for i in ph["items"]] == [("Yes", "Completed"), ("Yes", "Completed"),
                                                                  ("No", "Not applicable"), ("Yes", "No additional comments")]
    assert all(i["signature_file"]["gridfs_file_id"] for i in ph["items"])
    assert a["reporting_manager"]["status"] == "approved" and a["reporting_manager"]["approver_code"] == "M001"
    assert a["reporting_manager"]["approved_at"] and a["current_stage"] == "it" and a["it"]["pending_since"]
    assert api.files.count_documents({"metadata.kind": "handover"}) == 4              # signatures kept in GridFS
    # tracker + IT queue
    assert stage_states(api) == [("reporting_manager", "approved", "done"), ("it", "pending", "active"),
                                 ("hr", "pending", "waiting"), ("form_complete", "pending", "waiting")]
    api.as_user("JHS722")
    assert [a["it_status"] for a in api.get(f"{U}/it/dashboard").json()["applications"]] == ["Pending"]
    # the form is frozen
    api.as_user("M001")
    assert api.post(f"{M}/{fid}/handover/submit", json={"items": sub}).status_code == 409
    assert api.post(f"{M}/{fid}/handover/draft", json={"items": sub}).status_code == 409
    assert sig(api, fid, ROWS[0]).status_code == 409
    assert api.delete(f"{M}/{fid}/handover/signature/{ROWS[0]}").status_code == 409
    assert api.files.count_documents({"metadata.kind": "handover"}) == 4
    h = api.get(f"{M}/{fid}/handover").json()
    assert h["status"] == "submitted" and h["editable"] is False
    a = api.get(f"{U}/manager/dashboard").json()["applications"][0]
    assert a["application_status"] == "With IT" and a["can_decide"] is False and a["can_handover"] is False
    assert api.col.count_documents({}) == 1


def test_handover_payload_validation(api):
    fid = submit_as(api)
    open_handover(api, fid)
    assert api.post(f"{M}/{fid}/handover/draft", json={"items": [{"key": "bogus", "option": "Yes"}]}).status_code == 422
    assert api.post(f"{M}/{fid}/handover/draft", json={"items": [{"key": ROWS[0], "option": "Maybe"}]}).status_code == 422
    assert api.post(f"{M}/{fid}/handover/draft", json={"items": [{"key": ROWS[0], "option": "Yes"}, {"key": ROWS[0], "option": "No"}]}).status_code == 422
    assert api.post(f"{M}/{fid}/handover/draft", json={"items": [{"key": ROWS[0], "remarks": "x" * 1001}]}).status_code == 422


# ── 14: security ──────────────────────────────────────────────────────────────
def test_other_managers_and_outsiders_cannot_touch_the_application(api):
    fid = submit_as(api)
    for who in ("M002", "X999", "IT01", "T004", "T001"):
        api.as_user(who)
        assert api.post(f"{M}/{fid}/approve").status_code == 403, who
        assert api.post(f"{M}/{fid}/reject", json={"reason": "not my team"}).status_code == 403, who
    assert api.col.find_one({})["approval"]["reporting_manager"]["decision"] == "pending"
    assert [a["employee_id"] for a in dash(api, "M002").json()["applications"]] == []        # M002 does not see T001's form
    open_handover(api, fid)
    sig(api, fid, "induction")
    for who in ("M002", "X999", "T001"):
        api.as_user(who)
        assert api.get(f"{M}/{fid}/handover").status_code == 403, who
        assert api.post(f"{M}/{fid}/handover/draft", json={"items": items()}).status_code == 403, who
        assert api.post(f"{M}/{fid}/handover/submit", json={"items": items()}).status_code == 403, who
        assert sig(api, fid, "induction").status_code == 403, who
        assert api.delete(f"{M}/{fid}/handover/signature/induction").status_code == 403, who
        assert api.get(f"{M}/{fid}/handover/signature/induction").status_code == 403, who
    assert api.files.count_documents({"metadata.kind": "handover"}) == 1
    assert api.col.find_one({})["project_handover"]["status"] == "draft"


def test_an_employee_never_acts_on_their_own_form_even_as_manager(api):
    EMPLOYEES["M001"]["ReportingEmpCode"] = "M001"             # absurd data: manager reports to themself
    try:
        fid = submit_as(api, "M001")
        api.as_user("M001")
        assert api.post(f"{M}/{fid}/approve").status_code == 403
        assert dash(api, "M001").json()["applications"] == [] or all(a["employee_id"] != "M001" for a in dash(api, "M001").json()["applications"])
    finally:
        EMPLOYEES["M001"].pop("ReportingEmpCode", None)


def test_manager_is_verified_live_against_the_employee_record(api):
    """If the reporting line changes after the form was submitted, the CURRENT manager is the one who can act."""
    fid = submit_as(api)
    EMPLOYEES["T001"]["ReportingEmpCode"] = "M002"
    try:
        api.as_user("M001")
        assert api.post(f"{M}/{fid}/approve").status_code == 403
        api.as_user("M002")
        assert [a["employee_id"] for a in api.get(f"{U}/manager/dashboard").json()["applications"]] == ["T001"]
        assert api.post(f"{M}/{fid}/approve").status_code == 200
    finally:
        EMPLOYEES["T001"]["ReportingEmpCode"] = "M001"


def test_row_signature_files_are_viewable_only_by_the_right_people(api):
    fid = submit_as(api)
    manager_pass(api, fid)
    for who, expected in (("M001", 200), ("IT01", 200), ("HR01", 200), ("M002", 403), ("X999", 403), ("T001", 403)):
        api.as_user(who)
        r = api.get(f"{M}/{fid}/handover/signature/induction")
        assert r.status_code == expected, who
        if expected == 200:
            assert r.content == PNG and r.headers["content-type"] == "image/png"
            assert r.headers["x-content-type-options"] == "nosniff"


def test_a_file_that_is_not_where_it_claims_is_never_served_or_accepted(api):
    fid = submit_as(api)
    open_handover(api, fid)
    for k in ROWS:
        sig(api, fid, k)
    emp_file = api.col.find_one({})["signature_file"]["gridfs_file_id"]                 # the EMPLOYEE's own signature file
    ph = api.col.find_one({})["project_handover"]["items"]
    # point row 1 at a file that belongs to another row / the employee's own signature
    api.col.update_one({}, {"$set": {"project_handover.items.0.signature_file.gridfs_file_id": ph[1]["signature_file"]["gridfs_file_id"]}})
    assert api.get(f"{M}/{fid}/handover/signature/confidential_files").status_code == 404
    r = api.post(f"{M}/{fid}/handover/submit", json={"items": items()})
    assert r.status_code == 422 and "missing or invalid" in r.json()["detail"]["errors"][0]
    api.col.update_one({}, {"$set": {"project_handover.items.0.signature_file.gridfs_file_id": emp_file}})
    assert api.get(f"{M}/{fid}/handover/signature/confidential_files").status_code == 404
    assert api.post(f"{M}/{fid}/handover/submit", json={"items": items()}).status_code == 422
    assert api.col.find_one({})["approval"]["current_stage"] == "reporting_manager"


def test_employee_signature_flow_still_works_alongside(api):
    fid = submit_as(api)
    manager_pass(api, fid)
    api.as_user("T001")
    assert api.get(f"{U}/signature").content == PNG                                   # the employee's own file is untouched
    assert api.files.count_documents({}) == 5
    assert api.col.count_documents({}) == 1


def test_reporting_manager_can_read_the_filled_exit_form_but_nobody_else_can(api):
    fid = submit_as(api)
    for path in ("exit-form", "exit-form/signature"):
        api.as_user("M001")
        assert api.get(f"{M}/{fid}/{path}").status_code == 200, path
        for who in ("T001", "T005", "M002", "X999", "IT01", "HR01", "JHS1191"):               # not the employee, other managers, IT/HR
            api.as_user(who)
            assert api.get(f"{M}/{fid}/{path}").status_code == 403, (who, path)
    api.as_user("M001")
    f = api.get(f"{M}/{fid}/exit-form").json()
    assert f["employee_id"] == "T001" and f["employee_name"] == "Test One"
    assert f["employee_details"]["resignation_date"] == "2026-11-01" and f["employee_details"]["last_working_date"] == "2026-12-01"
    assert f["manager_feedback"]["communication"] == "Good" and f["company_feedback"]["facilities"] == "Satisfactory"
    assert f["exit_interview"]["resignation_reason"] == "c" and f["signature"]["filename"]
    assert isinstance(f["signature"]["file_id"], str) and "_id" not in f
    assert api.get(f"{M}/{'0' * 24}/exit-form").status_code == 404
    assert api.get(f"{M}/{fid}/exit-form/signature").headers["content-type"].startswith("image/png")
