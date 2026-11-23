"""The HR manager's read-only views: the employee's filled exit form and the IT Clearance form (throwaway database zz_exit_test)."""
from tests.test_exit_approvals import M, approve, manager_pass, submit_as  # noqa: F401
from tests.test_exit_approvals import it_pass
from tests.test_exit_hr_clearance import H, hr, to_hr  # noqa: F401
from tests.test_exit_management import EMPLOYEES, U, api  # noqa: F401


def test_hr_manager_can_read_the_filled_exit_form_at_any_stage_but_nobody_else_can(hr):
    fid = submit_as(hr)                                                         # still with the Reporting Manager
    for path in ("exit-form", "exit-form/signature"):
        hr.as_user("JHS1423")
        assert hr.get(f"{H}/{fid}/{path}").status_code == 200, path
        hr.as_user("JHS911")
        assert hr.get(f"{H}/{fid}/{path}").status_code == 200, path
        for who in ("T001", "T005", "M001", "M002", "X999", "IT01", "JHS1191", "JHS722", "JHS1474"):
            hr.as_user(who)
            assert hr.get(f"{H}/{fid}/{path}").status_code == 403, (who, path)
    hr.as_user("JHS1423")
    f = hr.get(f"{H}/{fid}/exit-form").json()
    assert f["employee_id"] == "T001" and f["employee_name"] == "Test One"
    assert f["employee_details"]["last_working_date"] == "2026-12-01" and f["manager_feedback"]["communication"] == "Good"
    assert f["exit_interview"]["resignation_reason"] == "c" and f["signature"]["filename"] and "_id" not in f
    assert hr.get(f"{H}/{'0' * 24}/exit-form").status_code == 404


def test_hr_manager_can_read_the_it_clearance_form_read_only(hr):
    fid = submit_as(hr)
    manager_pass(hr, fid)
    hr.as_user("JHS1423")
    assert hr.get(f"{H}/{fid}/it-clearance").status_code == 409                # IT clearance not started yet
    it_pass(hr, fid)
    hr.as_user("JHS1423")
    r = hr.get(f"{H}/{fid}/it-clearance")
    assert r.status_code == 200
    f = r.json()
    assert f["editable"] is False and f["status"] == "submitted" and len(f["items"]) == 12
    assert [i["option"] for i in f["items"]] == ["Yes"] * 12 and f["items"][0]["particular"] == "JHS Laptop Returned"
    assert f["items"][0]["signature"]["filename"] and f["employee"]["employee_id"] == "T001"
    assert hr.get(f"{H}/{fid}/it-clearance/signature/jhs_laptop").status_code == 200         # HR can open the signature files too
    hr.as_user("JHS911")
    assert hr.get(f"{H}/{fid}/it-clearance").status_code == 200
    for who in ("T001", "T005", "M001", "X999", "IT01", "JHS1191", "JHS722", "JHS1474"):
        hr.as_user(who)
        assert hr.get(f"{H}/{fid}/it-clearance").status_code == 403, who
        # (existing rules: the employee, the two owners and the IT approvers may open IT signature files; everyone else may not)
        assert hr.get(f"{H}/{fid}/it-clearance/signature/jhs_laptop").status_code == (200 if who in ("T001", "JHS1191", "JHS722", "JHS1474") else 403), who
    # the IT Clearance itself stays the IT approvers' form: HR cannot change it through the IT endpoints
    hr.as_user("JHS1423")
    assert hr.post(f"{U}/it/applications/{fid}/clearance/draft", json={"items": []}).status_code == 403


def test_hr_manager_cannot_read_their_own_forms_here(hr):
    fid = to_hr(hr, "JHS1423", "JHS01")
    hr.as_user("JHS1423")
    assert hr.get(f"{H}/{fid}/exit-form").status_code == 403
    assert hr.get(f"{H}/{fid}/it-clearance").status_code == 403
    hr.as_user("JHS911")                                                       # the other HR approver can
    assert hr.get(f"{H}/{fid}/exit-form").status_code == 200
    assert hr.get(f"{H}/{fid}/it-clearance").status_code == 200


def test_hr_manager_can_read_the_project_details_form_read_only(hr):
    fid = submit_as(hr)
    hr.as_user("JHS1423")
    assert hr.get(f"{H}/{fid}/handover").status_code == 409                     # the Reporting Manager has not started it yet
    manager_pass(hr, fid)
    hr.as_user("JHS1423")
    r = hr.get(f"{H}/{fid}/handover")
    assert r.status_code == 200
    f = r.json()
    assert f["editable"] is False and f["status"] == "submitted" and len(f["items"]) == 4
    assert [i["option"] for i in f["items"]] == ["Yes"] * 4 and f["items"][1]["particular"] == "Project Related Details Handover"
    assert f["manager_name"] == "Manager One" and f["employee"]["employee_id"] == "T001"          # the Reporting Manager, not the HR reader
    assert hr.get(f"{H}/{fid}/handover/signature/project_handover").status_code == 200
    hr.as_user("JHS911")
    assert hr.get(f"{H}/{fid}/handover").status_code == 200
    for who in ("T001", "T005", "M002", "X999", "IT01"):
        hr.as_user(who)
        assert hr.get(f"{H}/{fid}/handover").status_code == 403, who
        # (existing rule: a general IT approver such as IT01 may open handover signature files)
        assert hr.get(f"{H}/{fid}/handover/signature/project_handover").status_code == (200 if who == "IT01" else 403), who
    hr.as_user("JHS1423")                                                       # HR cannot change it
    assert hr.post(f"{U}/manager/applications/{fid}/handover/draft", json={"items": []}).status_code == 403
    assert hr.get(f"{H}/{'0' * 24}/handover").status_code == 404
