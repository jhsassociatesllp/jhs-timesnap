"""Employee Exit Management API tests (drafts, submit, GridFS signature upload).

Runs against a THROWAWAY database (zz_exit_test) on the same Mongo server - the real
`exist_form` collection and `signature_files` bucket are never touched. Employee lookups are
stubbed so the tests do not depend on real employee data.  Skipped if MongoDB is not reachable.
"""
import io

import gridfs
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.auth import get_current_user
from backend.database import _client
from backend.exit_management import repository as repo
from backend.exit_management.routes import router

try:
    _client.admin.command("ping")
except Exception:  # pragma: no cover
    pytest.skip("MongoDB not reachable", allow_module_level=True)

MB5 = 5 * 1024 * 1024
EMPLOYEES = {
    "T001": {"EmpID": "T001", "Emp Name": "Test One", "Designation Name": "Consultant",
             "Date of Joining": "07/10/2024", "ReportingEmpName": "Boss One", "ReportingEmpCode": "M001"},
    "T002": {"EmpID": "T002", "Emp Name": "Test Two"},   # sparse record: no reporting manager on record
    "M001": {"EmpID": "M001", "Emp Name": "Manager One"},
    "IT01": {"EmpID": "IT01", "Emp Name": "It Person"},
    "HR01": {"EmpID": "HR01", "Emp Name": "Hr Person"},
    "X999": {"EmpID": "X999", "Emp Name": "Random Colleague"},
    "JHS1191": {"EmpID": "JHS1191", "Emp Name": "Owner One"},
    # a second team, to prove managers only ever see their own people
    "M002": {"EmpID": "M002", "Emp Name": "Manager Two", "Designation Name": "Senior Manager"},
    "T004": {"EmpID": "T004", "Emp Name": "Test Four", "Designation Name": "Analyst", "Date of Joining": "01/02/2023",
             "ReportingEmpName": "Manager Two", "ReportingEmpCode": "M002", "Branch Name": "Mumbai"},
    "T005": {"EmpID": "T005", "Emp Name": "Test Five", "Designation Name": "Associate", "Date of Joining": "15/06/2024",
             "ReportingEmpName": "Boss One", "ReportingEmpCode": "M001", "Branch Name": "Pune"},   # M001's second report, never submits
}
RATINGS_M = ["team_management", "communication", "motivation", "technical_skills", "fairness",
             "approachability", "relationship_with_other_teams", "management_skills"]
RATINGS_C = ["company_culture", "learning_experience", "rewards_recognition", "performance_review_system",
             "physical_working_conditions", "facilities", "opportunity_for_growth", "management_skills"]
U = "/api/exit-management"


def make_png() -> bytes:
    b = io.BytesIO(); Image.new("RGB", (40, 20), "white").save(b, "PNG"); return b.getvalue()


def make_jpg() -> bytes:
    b = io.BytesIO(); Image.new("RGB", (40, 20), "white").save(b, "JPEG"); return b.getvalue()


def make_pdf(size: int = 600) -> bytes:
    body = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    return body + b" " * (size - len(body))


PNG, JPG, PDF = make_png(), make_jpg(), make_pdf()


@pytest.fixture()
def api(monkeypatch):
    monkeypatch.setenv("EXIT_MAIL_DISABLED", "1")                    # the tests must never send real e-mail
    tdb = _client["zz_exit_test"]
    for c in ("exist_form", "signature_files.files", "signature_files.chunks", "exit_approvers"):
        tdb[c].delete_many({})
    tdb["exit_approvers"].insert_many([{"stage": "it", "empid": "IT01"}, {"stage": "hr", "empid": "HR01"}])
    tdb["it_clearance_approvers"].delete_many({})
    tdb["hr_clearance_approvers"].delete_many({})
    monkeypatch.setattr(repo, "hr_approvers", tdb["hr_clearance_approvers"])
    monkeypatch.setattr(repo, "approvers", tdb["exit_approvers"])
    monkeypatch.setattr(repo, "it_approvers", tdb["it_clearance_approvers"])
    monkeypatch.setattr(repo, "collection", tdb["exist_form"])
    monkeypatch.setattr(repo, "signature_bucket", gridfs.GridFSBucket(tdb, bucket_name="signature_files"))
    monkeypatch.setattr(repo, "db", tdb)
    monkeypatch.setattr(repo, "_indexes_ready", False)
    monkeypatch.setattr(repo, "find_employee", lambda empid: EMPLOYEES.get(empid))
    monkeypatch.setattr(repo, "find_team", lambda code: sorted(
        [e for e in EMPLOYEES.values() if code and e.get("ReportingEmpCode") == code and e["EmpID"] != code], key=lambda e: e["Emp Name"]))
    app = FastAPI()
    app.include_router(router)
    user = {"id": "T001"}
    app.dependency_overrides[get_current_user] = lambda: user["id"]
    client = TestClient(app)
    client.as_user = lambda u: user.update(id=u)
    client.col = tdb["exist_form"]
    client.files = tdb["signature_files.files"]
    client.chunks = tdb["signature_files.chunks"]
    yield client
    for c in ("exist_form", "signature_files.files", "signature_files.chunks", "exit_approvers", "it_clearance_approvers", "hr_clearance_approvers"):
        tdb[c].delete_many({})


def upload(api, name="sig.png", data=PNG, ctype="image/png"):
    return api.post(f"{U}/upload-signature", files={"file": (name, data, ctype)})


def full_form(**over):
    body = {
        "resignation_date": "2026-11-01", "last_working_date": "2026-12-01",
        "manager_feedback": {k: "Good" for k in RATINGS_M},
        "company_feedback": {k: "Satisfactory" for k in RATINGS_C},
        "exit_interview": {
            "would_rejoin": "Yes", "systems_and_processes": "a", "team_experience": "b",
            "resignation_reason": "c", "better_prospect": "Yes", "new_employer": "Acme",
            "pull_factors": "d", "recommend_company": "No", "recommend_reason": "Limited growth", "jhs_memories": "e",
            "improvements": "f", "employee_benefits": "g", "departure_prevention": "h"},
    }
    body.update(over)
    return body


# ── login / details ───────────────────────────────────────────────────────────
def test_requires_login():
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    assert c.get(f"{U}/employee-details").status_code in (401, 403)
    assert c.get(f"{U}/signature").status_code in (401, 403)
    assert c.delete(f"{U}/signature").status_code in (401, 403)
    assert c.post(f"{U}/upload-signature", files={"file": ("a.png", PNG, "image/png")}).status_code in (401, 403)


def test_employee_details_mapped(api):
    d = api.get(f"{U}/employee-details").json()
    assert d["employee_name"] == "Test One" and d["code"] == "T001"
    assert d["designation"] == "Consultant" and d["joining_date"] == "2024-10-07"
    assert d["reporting_to"] == "Boss One" and d["missing"] == []


def test_employee_details_missing_fields_reported(api):
    api.as_user("T002")
    d = api.get(f"{U}/employee-details").json()
    assert set(d["missing"]) == {"Designation", "Joining date", "Reporting to"}


def test_unknown_employee_404(api):
    api.as_user("NOPE")
    assert api.get(f"{U}/employee-details").status_code == 404


# ── drafts ────────────────────────────────────────────────────────────────────
def test_draft_save_reopen_update(api):
    assert api.get(f"{U}/draft").json()["status"] == "none"
    r = api.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "first"}})
    assert r.status_code == 200 and r.json()["status"] == "draft"
    first_id = r.json()["id"]
    form = api.get(f"{U}/draft").json()["form"]
    assert form["exit_interview"]["resignation_reason"] == "first" and form["status"] == "draft"
    r = api.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "second"}})
    assert r.json()["id"] == first_id
    assert api.col.count_documents({"employee_id": "T001"}) == 1


def test_draft_rejects_bad_values(api):
    assert api.post(f"{U}/draft", json={"manager_feedback": {"fairness": "Great"}}).status_code == 422
    assert api.post(f"{U}/draft", json={"resignation_date": "01/11/2026"}).status_code == 422


def test_client_cannot_spoof_identity_or_signature(api):
    api.post(f"{U}/draft", json={"employee_id": "T002", "employee_name": "Hacker",
                                 "employee_details": {"designation": "CEO"},
                                 "signature_file": {"gridfs_file_id": "x"}, "signature": "data:image/png;base64,AAAA"})
    doc = api.col.find_one({})
    assert doc["employee_id"] == "T001" and doc["employee_name"] == "Test One"
    assert doc["employee_details"]["designation"] == "Consultant"
    assert "signature_file" not in doc and "signature" not in doc


def test_drafts_are_private_per_employee(api):
    api.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "mine"}})
    api.as_user("T002")
    assert api.get(f"{U}/draft").json()["status"] == "none"
    assert api.delete(f"{U}/draft").status_code == 404
    api.as_user("T001")
    assert api.get(f"{U}/draft").json()["status"] == "draft"


# ── signature upload: accepted types and sizes ────────────────────────────────
@pytest.mark.parametrize("name,data,ctype,expect", [
    ("sig.pdf", PDF, "application/pdf", "application/pdf"),
    ("sig.jpg", JPG, "image/jpeg", "image/jpeg"),
    ("sig.jpeg", JPG, "image/jpeg", "image/jpeg"),
    ("SIG.PNG", PNG, "image/png", "image/png"),
])
def test_upload_accepts_pdf_jpg_jpeg_png(api, name, data, ctype, expect):
    r = upload(api, name, data, ctype)
    assert r.status_code == 201
    meta = r.json()
    assert meta["content_type"] == expect and meta["file_size"] == len(data) and meta["filename"] == name
    assert api.files.count_documents({}) == 1
    gf = api.files.find_one({})
    assert gf["length"] == len(data) and gf["filename"] == name
    assert gf["metadata"]["employee_id"] == "T001" and gf["metadata"]["content_type"] == expect
    assert gf["metadata"]["extension"] == "." + name.rsplit(".", 1)[1].lower()
    doc = api.col.find_one({"employee_id": "T001"})
    assert gf["metadata"]["form_id"] == doc["_id"]                 # linked to the exit form
    ref = doc["signature_file"]
    assert ref["gridfs_file_id"] == gf["_id"] and ref["file_size"] == len(data) and ref["uploaded_at"]
    assert not any(isinstance(v, (bytes, str)) and len(v) > 5000 for v in doc.values())   # no file bytes / base64 in the form


def test_upload_exactly_5mb_accepted_and_above_rejected(api):
    assert upload(api, "big.pdf", make_pdf(MB5), "application/pdf").status_code == 201
    assert api.files.find_one({})["length"] == MB5
    api.files.delete_many({}); api.chunks.delete_many({}); api.col.delete_many({})
    r = upload(api, "big.pdf", make_pdf(MB5 + 1), "application/pdf")
    assert r.status_code == 413 and "5 MB" in r.json()["detail"]
    assert api.files.count_documents({}) == 0 and api.chunks.count_documents({}) == 0   # nothing left behind
    assert api.col.count_documents({}) == 0


def test_upload_rejects_executable_and_unsupported(api):
    exe = b"MZ\x90\x00" + b"\x00" * 200
    assert upload(api, "virus.exe", exe, "application/octet-stream").status_code == 415
    assert upload(api, "virus.pdf", exe, "application/pdf").status_code == 415       # exe disguised as pdf
    assert upload(api, "virus.png", exe, "image/png").status_code == 415
    assert upload(api, "notes.txt", b"hello world", "text/plain").status_code == 415
    assert upload(api, "anim.gif", b"GIF89a" + b"\x00" * 50, "image/gif").status_code == 415
    assert upload(api, "doc.png", PDF, "image/png").status_code == 415               # content != declared / extension
    assert upload(api, "doc.pdf", PNG, "application/pdf").status_code == 415
    assert upload(api, "pic.jpg", PNG, "image/jpeg").status_code == 415
    assert upload(api, "broken.png", PNG[:30], "image/png").status_code == 415      # truncated image
    assert upload(api, "noext", PDF, "application/pdf").status_code == 415
    assert api.files.count_documents({}) == 0 and api.col.count_documents({}) == 0


def test_upload_rejects_empty_file(api):
    r = upload(api, "empty.pdf", b"", "application/pdf")
    assert r.status_code == 400
    assert api.files.count_documents({}) == 0


def test_oversized_upload_refused_from_content_length_before_parsing(api):
    r = api.post(f"{U}/upload-signature", files={"file": ("big.pdf", make_pdf(MB5 + 200_000), "application/pdf")})
    assert r.status_code == 413
    assert api.files.count_documents({}) == 0


# ── replace / view / remove ───────────────────────────────────────────────────
def test_replace_signature_cleans_up_old_file(api):
    first = upload(api, "one.png", PNG).json()
    second = upload(api, "two.pdf", PDF, "application/pdf").json()
    assert first["file_id"] != second["file_id"]
    assert api.files.count_documents({}) == 1                                     # old file gone
    assert api.files.find_one({})["filename"] == "two.pdf"
    ref = api.col.find_one({"employee_id": "T001"})["signature_file"]
    assert str(ref["gridfs_file_id"]) == second["file_id"]
    assert api.col.count_documents({"employee_id": "T001"}) == 1
    assert api.chunks.count_documents({"files_id": {"$ne": api.files.find_one({})["_id"]}}) == 0   # old chunks gone too


def test_failed_replacement_keeps_existing_signature(api):
    ok = upload(api, "keep.png", PNG).json()
    assert upload(api, "bad.exe", b"MZ" + b"\x00" * 100, "application/octet-stream").status_code == 415
    assert api.files.count_documents({}) == 1
    assert str(api.col.find_one({"employee_id": "T001"})["signature_file"]["gridfs_file_id"]) == ok["file_id"]


def test_get_signature_returns_file_with_correct_type(api):
    upload(api, "me.png", PNG)
    r = api.get(f"{U}/signature")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert "inline" in r.headers["content-disposition"] and "me.png" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in api.get(f"{U}/signature?download=true").headers["content-disposition"]
    api.delete(f"{U}/signature")
    upload(api, "me.pdf", PDF, "application/pdf")
    r = api.get(f"{U}/signature")
    assert r.headers["content-type"] == "application/pdf" and r.content == PDF


def test_get_signature_404_when_none(api):
    assert api.get(f"{U}/signature").status_code == 404
    api.post(f"{U}/draft", json={})
    assert api.get(f"{U}/signature").status_code == 404


def test_delete_signature_removes_gridfs_file(api):
    upload(api, "me.png", PNG)
    assert api.delete(f"{U}/signature").json() == {"deleted": True}
    assert api.files.count_documents({}) == 0 and api.chunks.count_documents({}) == 0
    assert "signature_file" not in api.col.find_one({"employee_id": "T001"})
    assert api.delete(f"{U}/signature").status_code == 404


# ── draft keeps the signature ─────────────────────────────────────────────────
def test_save_and_reopen_draft_keeps_signature(api):
    meta = upload(api, "me.png", PNG).json()
    api.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "later"}})
    api.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "later 2"}})
    form = api.get(f"{U}/draft").json()["form"]
    assert form["signature_file"]["file_id"] == meta["file_id"] and form["signature_file"]["filename"] == "me.png"
    assert form["exit_interview"]["resignation_reason"] == "later 2"
    assert api.files.count_documents({}) == 1


# ── submit ────────────────────────────────────────────────────────────────────
def test_submit_validation_lists_everything_missing(api):
    r = api.post(f"{U}/submit", json={})
    assert r.status_code == 422
    errs = r.json()["detail"]["errors"]
    assert any("Resignation Date" in e for e in errs) and any("signature document" in e for e in errs)
    assert sum("rate" in e for e in errs) == 16
    assert api.col.count_documents({}) == 0


def test_submit_requires_uploaded_signature(api):
    r = api.post(f"{U}/submit", json=full_form())
    assert r.status_code == 422 and r.json()["detail"]["errors"] == ["Please upload your signature document"]
    assert api.col.count_documents({}) == 0


def test_submit_conditional_employer(api):
    upload(api)
    body = full_form()
    body["exit_interview"]["new_employer"] = ""
    r = api.post(f"{U}/submit", json=body)
    assert r.status_code == 422 and any("new employer" in e for e in r.json()["detail"]["errors"])
    body["exit_interview"]["better_prospect"] = "No"
    body["exit_interview"]["pull_factors"] = ""
    assert api.post(f"{U}/submit", json=body).status_code == 201


def test_submit_rejects_bad_dates(api):
    upload(api)
    assert api.post(f"{U}/submit", json=full_form(last_working_date="2026-10-01")).status_code == 422


def test_full_flow_submit_keeps_signature_and_blocks_duplicates(api):
    api.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "draft text"}})
    meta = upload(api, "me.pdf", PDF, "application/pdf").json()
    r = api.post(f"{U}/submit", json=full_form())
    assert r.status_code == 201 and r.json()["status"] == "submitted"
    assert api.col.count_documents({"employee_id": "T001"}) == 1
    doc = api.col.find_one({"employee_id": "T001"})
    assert doc["status"] == "submitted" and doc["submitted_at"]
    assert str(doc["signature_file"]["gridfs_file_id"]) == meta["file_id"]           # reference kept
    assert api.files.count_documents({}) == 1 and api.files.find_one({})["length"] == len(PDF)   # file kept in GridFS
    st = api.get(f"{U}/submission-status").json()
    assert st["submitted"] is True and st["has_draft"] is False and st["has_signature"] is True
    # submitted form is frozen: no resubmit, no draft overwrite, no draft delete, no signature change
    assert api.post(f"{U}/submit", json=full_form()).status_code == 409
    assert api.post(f"{U}/draft", json={"exit_interview": {"resignation_reason": "x"}}).status_code == 409
    assert api.delete(f"{U}/draft").status_code == 404
    assert upload(api, "new.png", PNG).status_code == 409
    assert api.delete(f"{U}/signature").status_code == 409
    assert api.files.count_documents({}) == 1 and api.files.find_one({})["filename"] == "me.pdf"
    assert api.get(f"{U}/signature").content == PDF                                  # still viewable after submit
    assert api.get(f"{U}/draft").json()["status"] == "submitted"


def test_submit_without_prior_draft_fields_and_delete_draft_removes_nothing_submitted(api):
    api.post(f"{U}/draft", json={})
    assert api.delete(f"{U}/draft").json() == {"deleted": True}
    assert api.col.count_documents({}) == 0


def test_delete_draft_with_signature_leaves_no_orphan(api):
    """Deleting a draft that has a signature must not leave the GridFS file behind."""
    upload(api)
    assert api.delete(f"{U}/draft").json() == {"deleted": True}
    assert api.files.count_documents({}) == 0 and api.chunks.count_documents({}) == 0


# ── ownership / tampering ─────────────────────────────────────────────────────
def test_other_employee_cannot_get_or_remove_my_signature(api):
    upload(api, "mine.png", PNG)
    api.as_user("T002")
    assert api.get(f"{U}/signature").status_code == 404
    assert api.delete(f"{U}/signature").status_code == 404
    assert api.files.count_documents({}) == 1


def test_tampered_reference_to_someone_elses_file_is_not_served_or_submittable(api):
    mine = upload(api, "mine.png", PNG).json()
    api.as_user("T002")
    api.post(f"{U}/draft", json={})
    from bson import ObjectId
    api.col.update_one({"employee_id": "T002"}, {"$set": {"signature_file": {
        "gridfs_file_id": ObjectId(mine["file_id"]), "filename": "mine.png", "content_type": "image/png",
        "file_size": len(PNG), "extension": ".png"}}})
    assert api.get(f"{U}/signature").status_code == 404                              # metadata.employee_id mismatch
    r = api.post(f"{U}/submit", json=full_form())
    assert r.status_code == 422 and "could not be found" in r.json()["detail"]["errors"][0]
    assert api.col.find_one({"employee_id": "T002"})["status"] == "draft"


def test_submit_rejects_file_linked_to_another_form(api):
    upload(api)
    api.files.update_one({}, {"$set": {"metadata.form_id": __import__("bson").ObjectId()}})
    r = api.post(f"{U}/submit", json=full_form())
    assert r.status_code == 422 and "does not belong to this form" in r.json()["detail"]["errors"][0]


def test_submit_rejects_missing_gridfs_file(api):
    upload(api)
    api.files.delete_many({}); api.chunks.delete_many({})
    r = api.post(f"{U}/submit", json=full_form())
    assert r.status_code == 422 and "could not be found" in r.json()["detail"]["errors"][0]


def test_indexes_created(api):
    api.get(f"{U}/draft")
    idx = api.col.index_information()
    assert any(v.get("unique") and v["key"] == [("employee_id", 1)] for v in idx.values())
    assert any(v["key"] == [("status", 1)] for v in idx.values())


def test_pdf_export_endpoints_are_gone(api):
    assert api.post(f"{U}/export-pdf", json={}).status_code == 405                     # export is GET only (and only when the exit is complete)
    assert api.get(f"{U}/submission-pdf").status_code == 404


def test_every_interview_question_17_to_27_is_required_to_submit(api):
    """Blank or whitespace-only answers to Q17-Q27 are refused; Q22 / the employer name only matter when Q21 is Yes."""
    api.as_user("T001")
    assert upload(api).status_code == 201
    keys = ["would_rejoin", "systems_and_processes", "team_experience", "resignation_reason", "better_prospect",
            "recommend_company", "jhs_memories", "improvements", "employee_benefits", "departure_prevention"]
    for key in keys:
        body = full_form()
        body["exit_interview"][key] = None
        r = api.post(f"{U}/submit", json=body)
        assert r.status_code == 422, key
        body["exit_interview"][key] = "   " if key not in ("would_rejoin", "better_prospect", "recommend_company") else None
        assert api.post(f"{U}/submit", json=body).status_code == 422, key
    body = full_form()
    body["exit_interview"].update(better_prospect="Yes", new_employer="", pull_factors="")   # Q21 = Yes -> employer name and Q22 become required too
    assert api.post(f"{U}/submit", json=body).status_code == 422
    assert api.col.count_documents({"status": "submitted"}) == 0
    assert api.post(f"{U}/submit", json=full_form()).status_code == 201


def test_q23_no_needs_a_reason_and_the_reason_is_kept_only_for_no(api):
    api.as_user("T001")
    assert upload(api).status_code == 201
    body = full_form()
    body["exit_interview"]["recommend_company"] = "No"
    body["exit_interview"]["recommend_reason"] = ""
    r = api.post(f"{U}/submit", json=body)
    assert r.status_code == 422 and any("Q23" in e for e in r.json()["detail"]["errors"])          # No without a reason
    body["exit_interview"]["recommend_reason"] = "   "
    assert api.post(f"{U}/submit", json=body).status_code == 422                                    # blanks are not a reason
    assert api.post(f"{U}/draft", json=body).status_code == 200                                     # a draft may stay incomplete
    body["exit_interview"]["recommend_reason"] = "Too little growth for juniors"
    assert api.post(f"{U}/submit", json=body).status_code == 201
    assert api.col.find_one({"employee_id": "T001"})["exit_interview"]["recommend_reason"] == "Too little growth for juniors"


def test_q23_reason_is_dropped_when_the_answer_is_yes(api):
    api.as_user("T001")
    assert upload(api).status_code == 201
    body = full_form()
    body["exit_interview"]["recommend_company"] = "Yes"
    body["exit_interview"]["recommend_reason"] = "left over from an earlier No"
    assert api.post(f"{U}/submit", json=body).status_code == 201
    assert api.col.find_one({"employee_id": "T001"})["exit_interview"]["recommend_reason"] == ""
