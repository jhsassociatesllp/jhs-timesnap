"""A row answered Yes needs a signature in the Project Details, IT Clearance and HR Clearance forms; No / NA rows do not (throwaway database zz_exit_test)."""
from tests.test_exit_approvals import HR_KEYS, IT_KEYS, M, manager_pass, submit_as  # noqa: F401
from tests.test_exit_approvals import it_pass
from tests.test_exit_hr_clearance import H, hr, sig as hr_sig  # noqa: F401
from tests.test_exit_it_clearance import I, sig as it_sig
from tests.test_exit_manager import ROWS, sig as ho_sig
from tests.test_exit_management import PNG, U, api  # noqa: F401

NEED = "a signature is required when the answer is Yes"


def test_project_details_yes_rows_need_a_signature(hr):
    fid = submit_as(hr)
    hr.as_user("M001")
    assert hr.post(f"{M}/{fid}/approve").status_code == 200
    assert ho_sig(hr, fid, ROWS[0]).status_code == 201                              # only the first row is signed
    body = [{"key": ROWS[0], "option": "Yes"}, {"key": ROWS[1], "option": "Yes", "remarks": "x"}, {"key": ROWS[2], "option": "No"}, {"key": ROWS[3], "option": "NA" if False else "No"}]
    r = hr.post(f"{M}/{fid}/handover/submit", json={"items": body})
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 1 and ROWS and "Project Related Details Handover" in r.json()["detail"]["errors"][0] and NEED in r.json()["detail"]["errors"][0]
    assert hr.col.find_one({})["approval"]["current_stage"] == "reporting_manager"          # nothing was submitted
    assert ho_sig(hr, fid, ROWS[1]).status_code == 201                                     # sign the other Yes row: No rows need nothing
    assert hr.post(f"{M}/{fid}/handover/submit", json={"items": body}).status_code == 201


def test_it_clearance_yes_rows_need_a_signature_but_no_and_na_do_not(hr):
    fid = submit_as(hr)
    manager_pass(hr, fid)
    hr.as_user("JHS722")
    assert hr.get(f"{I}/{fid}/clearance").status_code == 200
    assert it_sig(hr, fid, IT_KEYS[0]).status_code == 201
    opts = ["Yes", "Yes", "No", "NA"] + ["NA"] * 8
    body = [{"key": k, "option": o} for k, o in zip(IT_KEYS, opts)]
    r = hr.post(f"{I}/{fid}/clearance/submit", json={"items": body})
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 1 and "Official JHS Email ID Disabled" in r.json()["detail"]["errors"][0] and NEED in r.json()["detail"]["errors"][0]
    assert hr.col.find_one({})["approval"]["current_stage"] == "it"
    assert it_sig(hr, fid, IT_KEYS[1]).status_code == 201
    assert hr.post(f"{I}/{fid}/clearance/submit", json={"items": body}).status_code == 201   # the No / NA rows stay unsigned


def test_hr_clearance_yes_rows_need_a_signature_but_no_does_not(hr):
    fid = submit_as(hr)
    manager_pass(hr, fid)
    it_pass(hr, fid)
    hr.as_user("JHS1423")
    assert hr.get(f"{H}/{fid}/clearance").status_code == 200
    assert hr_sig(hr, fid, "hr_sign").status_code == 201                                # the HR Sign alone does not cover a Yes row
    body = {"items": [{"key": HR_KEYS[0], "option": "Yes"}, {"key": HR_KEYS[1], "option": "No"}, {"key": HR_KEYS[2], "option": "Yes"}]}
    r = hr.post(f"{H}/{fid}/clearance/submit", json=body)
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 2 and all(NEED in e for e in r.json()["detail"]["errors"])
    assert hr.col.find_one({})["approval"]["current_stage"] == "hr"
    assert hr_sig(hr, fid, HR_KEYS[0]).status_code == 201 and hr_sig(hr, fid, HR_KEYS[2]).status_code == 201
    assert hr.post(f"{H}/{fid}/clearance/submit", json=body).status_code == 201
