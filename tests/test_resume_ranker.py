import io
from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.resume_ranker import extract, parser, scoring, worker


# ── helpers ─────────────────────────────────────────────────────────────────

def make_pdf(text: str) -> bytes:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in text.split("\n"):
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def make_docx(paragraphs, table_rows=None) -> bytes:
    import docx
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    if table_rows:
        t = d.add_table(rows=0, cols=2)
        for a, b in table_rows:
            cells = t.add_row().cells
            cells[0].text, cells[1].text = a, b
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


ALICE = ("Alice Sharma\nalice@example.com  +91 98765 43210\nMumbai\n"
         "Senior Auditor at Deloitte 2015-2023. Skills: Audit, Tally ERP, ReactJS. CA qualified. ALICE-MARKER")
BOB = "Bob Rao\nbob@example.com\nPune\nJunior Accountant at Acme 2022-2024. Skills: Excel. BOB-MARKER"


# ── extraction ──────────────────────────────────────────────────────────────

def test_extract_pdf_docx_and_tables():
    assert "Senior Auditor" in extract.extract_text(make_pdf(ALICE), "a.pdf")
    text = extract.extract_text(make_docx(["Hello there this is a resume body with enough text."],
                                          [("Skills", "Audit, Tally, Excel, GST filing")]), "a.docx")
    assert "Audit, Tally" in text and "Hello there" in text


def test_extract_uses_content_not_extension():
    docx_bytes = make_docx(["A perfectly normal resume paragraph that is long enough to pass."])
    assert "perfectly normal" in extract.extract_text(docx_bytes, "cv.doc")       # docx named .doc
    rtf = b"{\\rtf1\\ansi Jane Doe, Senior Accountant with ten years of audit experience in Pune.}"
    assert "Senior Accountant" in extract.extract_text(rtf, "cv.doc")               # rtf named .doc


@pytest.mark.parametrize("data,msg", [
    (b"", "empty"),
    (b"this is not a resume file at all, just plain junk bytes" * 3, "Unrecognised"),
    (b"%PDF-1.4\ngarbage that is not a real pdf structure", "corrupt|No readable"),
    (b"PK\x03\x04truncatedzip", "Unrecognised|corrupt"),
])
def test_extract_bad_files_raise_clean_errors(data, msg):
    with pytest.raises(extract.ExtractionError, match="(?i)" + msg):
        extract.extract_text(data, "x.pdf")


def test_blank_pdf_reports_scanned():
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    with pytest.raises(extract.ExtractionError, match="scanned"):
        extract.extract_text(bytes(pdf.output()), "scan.pdf")


# ── parsing helpers ─────────────────────────────────────────────────────────

def test_skill_key_merges_variants():
    assert {parser.skill_key(s) for s in ("React.js", "ReactJS", "react js", "React")} == {"react"}
    assert parser.skill_key("Node.js") == "node"
    assert parser.skill_key("JavaScript") == "javascript"
    assert parser.skill_key("C++") == "c++"


def test_total_years_merges_overlaps():
    exp = [{"start": "2015-01", "end": "2019-12"}, {"start": "2018-01", "end": "2020-12"},
           {"start": "2022-01", "end": "present"}]
    got = parser.compute_total_years(exp, date(2024, 1, 1))
    assert got == pytest.approx((72 + 25) / 12)          # 2015-01..2020-12 (72m) + 2022-01..2024-01 (25m)
    assert parser.compute_total_years([{"start": None, "end": None}]) is None


def test_normalize_falls_back_to_regex_contact_and_guesses_level():
    out = parser.normalize_parsed({"skills": ["A"], "education": [{"degree": "M.Sc Physics"}]},
                                  "Call +91 98765 43210 or mail Me@X.com")
    assert out["email"] == "me@x.com" and parser.phone_key(out["phone"]) == "9876543210"
    assert out["highest_education_level"] == "master"


# ── scoring maths ───────────────────────────────────────────────────────────

JOB = {
    "title": "Audit Manager", "required_skills": [{"name": "Audit", "must_have": True}, {"name": "Tally", "must_have": False}],
    "preferred_skills": ["Power BI"], "min_years": 5, "experience_must_have": True,
    "education_level": "bachelor", "required_certifications": [{"name": "CA", "must_have": True}],
    "industries": ["Audit"], "location": "Mumbai", "location_type": "onsite",
    "weights": {"skills": 40, "experience": 30, "education": 15, "certifications": 0, "industry": 15, "location": 0},
    "must_have_action": "flag",
}
PARSED = {"total_years_experience": 8.0, "highest_education_level": "master", "location": "Pune", "industries": ["Audit"]}


def test_weights_normalise_over_active_criteria_only():
    job = {"required_skills": [{"name": "x", "must_have": False}], "min_years": 2,
           "weights": {"skills": 60, "experience": 20, "education": 100}}     # education inactive -> ignored
    w = scoring.effective_weights(job)
    assert w == {"skills": 75.0, "experience": 25.0}


def test_compute_scores_breakdown_and_flags():
    judgement = {
        "skills": [{"name": "Audit", "match": "full", "evidence": "x"}, {"name": "Tally", "match": "partial"}],
        "preferred_skills": [{"name": "Power BI", "match": "none"}],
        "certifications": [{"name": "CA", "match": "none"}],
        "relevant_years": 8, "industry_fit": 80, "location_match": "no",
    }
    r = scoring.compute_scores(JOB, PARSED, judgement)
    assert r["sub_scores"]["skills"]["score"] == pytest.approx(100 * (0.75 * 0.75 + 0.25 * 0), abs=0.1)
    assert r["sub_scores"]["experience"]["score"] == 100.0
    assert r["sub_scores"]["education"]["score"] == 100.0
    assert "certifications" in r["sub_scores"] and r["sub_scores"]["certifications"]["score"] == 0.0
    msgs = [f["message"] for f in r["flags"]]
    assert "Missing required certification: CA" in msgs
    assert not r["meets_all_must_haves"] and not r["capped"]
    assert 0 <= r["total"] <= 100


def test_must_have_cap_and_short_experience():
    job = {**JOB, "must_have_action": "cap", "must_have_cap": 40}
    judgement = {"skills": [{"name": "Audit", "match": "none"}, {"name": "Tally", "match": "full"}],
                 "relevant_years": 2, "industry_fit": 100}
    r = scoring.compute_scores(job, {**PARSED, "total_years_experience": 2.0}, judgement)
    assert "Missing required skill: Audit" in [f["message"] for f in r["flags"]]
    assert any(f["type"] == "experience_below_minimum" for f in r["flags"])
    assert r["total"] <= 40 and r["capped"]


def test_model_omissions_count_as_none_never_optimistic():
    r = scoring.compute_scores(JOB, PARSED, {})
    assert r["sub_scores"]["skills"]["score"] == 0.0
    assert r["total"] < 60


def test_masked_profile_hides_identity():
    parsed = {"name": "Alice", "email": "a@b.c", "phone": "1", "skills": ["x"],
              "education": [{"degree": "BA", "level": "bachelor", "institution": "St Xavier's", "year": 1999}],
              "experience": [{"title": "Auditor", "company": "Deloitte", "start": "2015", "end": "2020"}]}
    masked = str(scoring.build_profile(parsed, True))
    assert "Alice" not in masked and "a@b.c" not in masked and "Deloitte" not in masked and "1999" not in masked
    assert "Auditor" in masked
    assert "Alice" in str(scoring.build_profile(parsed, False))


# ── end-to-end through the API ──────────────────────────────────────────────

@pytest.fixture
def api(clean_db, fake_llm):
    from backend.auth import get_current_user
    from backend.resume_ranker.db import holders
    from backend.resume_ranker.router import router

    holders.delete_many({})
    holders.insert_one({"empid": "HR1", "role": "hr"})
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "HR1"

    fake_llm.parse_by_marker = {
        "ALICE-MARKER": {"name": "Alice Sharma", "email": "alice@example.com", "phone": "+91 98765 43210",
                         "location": "Mumbai", "skills": ["Audit", "Tally ERP", "ReactJS"],
                         "education": [{"degree": "CA", "level": "professional"}], "certifications": ["CA"],
                         "experience": [{"title": "Senior Auditor", "company": "Deloitte", "start": "2015-01", "end": "2023-01",
                                         "industry": "Audit"}], "industries": ["Audit"]},
        "BOB-MARKER": {"name": "Bob Rao", "email": "bob@example.com", "location": "Pune", "skills": ["Excel"],
                       "education": [{"degree": "B.Com", "level": "bachelor"}],
                       "experience": [{"title": "Junior Accountant", "company": "Acme", "start": "2022-01", "end": "2024-01"}]},
    }
    fake_llm.judge_by_marker = {
        "Alice Sharma": {"skills": [{"name": "Audit", "match": "full"}, {"name": "Tally", "match": "full", "evidence": "Tally ERP"}],
                         "certifications": [{"name": "CA", "match": "full"}], "relevant_years": 8, "industry_fit": 95,
                         "location_match": "yes", "summary": "Strong fit."},
        "Bob Rao": {"skills": [{"name": "Audit", "match": "none"}, {"name": "Tally", "match": "none"}],
                    "certifications": [{"name": "CA", "match": "none"}], "relevant_years": 1, "industry_fit": 20,
                    "location_match": "no", "summary": "Too junior."},
    }
    return TestClient(app)


def drain(limit=200):
    for _ in range(limit):
        t = worker.claim_next()
        if not t:
            return
        worker.run_task(t)
    raise AssertionError("queue did not drain")


def post_job(api, **over):
    body = {"title": "Audit Manager", "required_skills": [{"name": "Audit", "must_have": True}, {"name": "Tally"}],
            "min_years": 5, "experience_must_have": True, "education_level": "bachelor",
            "required_certifications": [{"name": "CA", "must_have": True}], "industries": ["Audit"],
            "location": "Mumbai", **over}
    r = api.post("/resume-ranker/jobs", json=body)
    assert r.status_code == 200, r.text
    return r.json()["job"]


def upload(api, batch_id, files):
    return api.post(f"/resume-ranker/batches/{batch_id}/files",
                    files=[("files", (n, io.BytesIO(d), "application/octet-stream")) for n, d in files]).json()["results"]


def test_access_is_enforced(api):
    from backend.resume_ranker.db import holders
    holders.delete_many({})
    assert api.get("/resume-ranker/jobs").status_code == 403
    assert api.get("/resume-ranker/access-check").json()["allowed"] is False


def test_job_needs_at_least_one_requirement(api):
    assert api.post("/resume-ranker/jobs", json={"title": "Empty job"}).status_code == 422


def test_full_pipeline_rank_flags_search_export_and_failures(api, fake_llm):
    job = post_job(api)
    batch = api.post("/resume-ranker/batches", json={"job_ids": [job["id"]], "expected_files": 7}).json()["batch_id"]

    results = upload(api, batch, [
        ("alice.pdf", make_pdf(ALICE)),
        ("bob.docx", make_docx(BOB.split("\n"))),
        ("corrupt.pdf", b"%PDF-1.4 total garbage"),
        ("notes.txt", b"hello"),
        ("empty.docx", b""),
        ("alice_again.pdf", make_pdf(ALICE)),                                   # byte-identical to alice.pdf
        ("blank.pdf", _blank_pdf()),
    ])
    by_name = {r["filename"]: r for r in results}
    assert by_name["notes.txt"]["status"] == "rejected" and "Unsupported" in by_name["notes.txt"]["reason"]
    assert by_name["empty.docx"]["status"] == "rejected"
    assert by_name["alice_again.pdf"]["status"] == "duplicate"

    drain()

    prog = api.get(f"/resume-ranker/batches/{batch}").json()
    assert prog["finished"] is True
    assert prog["counts"]["parsed"] == 2 and prog["counts"]["failed"] == 2 and prog["counts"]["duplicate"] == 1
    assert {f["filename"] for f in prog["failures"]} == {"corrupt.pdf", "blank.pdf"}
    assert len(prog["rejected"]) == 2

    ranked = api.get("/resume-ranker/resumes", params={"job_id": job["id"]}).json()
    names = [r["name"] for r in ranked["resumes"]]
    assert names == ["Alice Sharma", "Bob Rao"]                                  # highest first, duplicate hidden
    alice, bob = ranked["resumes"]
    assert alice["rank"] == 1 and bob["rank"] == 2 and alice["score"]["total"] > 85 > bob["score"]["total"]
    assert alice["score"]["meets_all_must_haves"] is True
    bob_msgs = [f["message"] for f in bob["score"]["flags"]]
    assert "Missing required skill: Audit" in bob_msgs and "Missing required certification: CA" in bob_msgs
    assert set(alice["score"]["sub_scores"]) == {"skills", "experience", "education", "certifications", "industry", "location"}
    assert alice["total_years"] == pytest.approx(8.1, abs=0.1)

    # search & filter
    def ids(**p):
        return [r["name"] for r in api.get("/resume-ranker/resumes", params=p).json()["resumes"]]
    assert ids(skills="react") == ["Alice Sharma"]                               # ReactJS ~ react
    assert ids(q="deloitte") == ["Alice Sharma"]
    assert ids(min_exp=5) == ["Alice Sharma"] and ids(max_exp=3) == ["Bob Rao"]
    assert ids(job_id=job["id"], min_score=90) == ["Alice Sharma"]
    assert ids(job_id=job["id"], must_haves_ok="true") == ["Alice Sharma"]
    assert ids(min_education="master") == [] and sorted(ids(min_education="bachelor")) == ["Alice Sharma", "Bob Rao"]
    assert sorted(ids(hide_duplicates="false")) == ["Alice Sharma", "Alice Sharma", "Bob Rao"]

    # stage / tags / notes
    aid = alice["id"]
    assert api.put(f"/resume-ranker/jobs/{job['id']}/stage", json={"resume_ids": [aid], "stage": "shortlisted"}).json()["updated"] == 1
    assert api.put(f"/resume-ranker/resumes/{aid}/tags", json={"tags": ["Top Pick", "top pick", "mumbai"]}).json()["tags"] == ["top pick", "mumbai"]
    note = api.post(f"/resume-ranker/resumes/{aid}/notes", json={"text": "Call on Monday"}).json()["note"]
    assert ids(job_id=job["id"], stage="shortlisted") == ["Alice Sharma"]
    assert ids(tag="mumbai") == ["Alice Sharma"]
    detail = api.get(f"/resume-ranker/resumes/{aid}").json()
    assert detail["notes"][0]["text"] == "Call on Monday" and detail["scores"][0]["job_title"] == "Audit Manager"
    assert detail["parsed"]["skills"][0] == "Audit" and "Senior Auditor" in detail["text"]
    assert len(detail["duplicates"]) == 1
    api.delete(f"/resume-ranker/resumes/{aid}/notes/{note['id']}")

    # export
    csv_resp = api.get(f"/resume-ranker/jobs/{job['id']}/export", params={"format": "csv", "stage": "shortlisted"})
    lines = csv_resp.text.lstrip("﻿").strip().splitlines()
    assert len(lines) == 2 and lines[1].startswith("1,Alice Sharma")
    xlsx = api.get(f"/resume-ranker/jobs/{job['id']}/export", params={"format": "xlsx"})
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(xlsx.content)).active
    assert ws.max_row == 3 and ws["B2"].value == "Alice Sharma" and ws["F2"].value > ws["F3"].value

    # retry failed files
    assert api.post(f"/resume-ranker/batches/{batch}/retry").json()["requeued"] == 2


def _blank_pdf():
    from fpdf import FPDF
    p = FPDF()
    p.add_page()
    return bytes(p.output())


def test_transient_ai_errors_retry_then_succeed(api, fake_llm):
    job = post_job(api)
    batch = api.post("/resume-ranker/batches", json={"job_ids": [job["id"]], "expected_files": 1}).json()["batch_id"]
    upload(api, batch, [("alice.pdf", make_pdf(ALICE))])
    fake_llm.fail_transient = 1
    t = worker.claim_next()
    worker.run_task(t)                                                            # first attempt: 429 -> requeued
    from backend.resume_ranker.db import tasks
    assert tasks.find_one({"_id": t["_id"]})["status"] == "queued"
    tasks.update_many({"status": "queued"}, {"$set": {"run_after": datetime(2000, 1, 1)}})    # skip the backoff wait
    drain()
    assert api.get("/resume-ranker/resumes", params={"job_id": job["id"]}).json()["total"] == 1


def test_rescoring_and_stale_detection_when_criteria_change(api):
    job = post_job(api)
    batch = api.post("/resume-ranker/batches", json={"job_ids": [job["id"]], "expected_files": 1}).json()["batch_id"]
    upload(api, batch, [("alice.pdf", make_pdf(ALICE))])
    drain()
    assert api.get(f"/resume-ranker/jobs/{job['id']}").json()["job"]["stale_count"] == 0

    body = {**{k: v for k, v in job.items() if k in ("title", "required_skills", "min_years", "education_level",
                                                    "required_certifications", "industries", "location")},
            "min_years": 10, "weights": {"skills": 10, "experience": 60, "education": 10, "certifications": 10, "industry": 5, "location": 5}}
    upd = api.put(f"/resume-ranker/jobs/{job['id']}", json=body).json()
    assert upd["criteria_changed"] is True and upd["job"]["stale_count"] == 1
    row = api.get("/resume-ranker/resumes", params={"job_id": job["id"]}).json()["resumes"][0]
    assert row["score"]["stale"] is True

    assert api.post(f"/resume-ranker/jobs/{job['id']}/score", json={"scope": "stale"}).json()["queued"] == 1
    from backend.resume_ranker.db import tasks
    assert api.post(f"/resume-ranker/jobs/{job['id']}/score", json={"scope": "stale"}).json()["queued"] == 1
    assert tasks.count_documents({"kind": "score", "status": "queued"}) == 1          # re-clicking doesn't pile up tasks
    drain()
    assert api.get(f"/resume-ranker/jobs/{job['id']}").json()["job"]["stale_count"] == 0


def test_multiple_jobs_have_independent_rankings(api):
    j1 = post_job(api, title="Audit Manager")
    j2 = post_job(api, title="Junior Accountant", min_years=0, required_skills=[{"name": "Excel"}],
                  education_level="none", required_certifications=[], industries=[], location=None,
                  experience_must_have=False)
    batch = api.post("/resume-ranker/batches", json={"job_ids": [j1["id"], j2["id"]], "expected_files": 2}).json()["batch_id"]
    upload(api, batch, [("alice.pdf", make_pdf(ALICE)), ("bob.docx", make_docx(BOB.split("\n")))])
    drain()
    for j in (j1, j2):
        assert api.get("/resume-ranker/resumes", params={"job_id": j["id"]}).json()["total"] == 2
    assert {s["job_title"] for s in api.get(
        f"/resume-ranker/resumes/{api.get('/resume-ranker/resumes').json()['resumes'][0]['id']}").json()["scores"]} == {"Audit Manager", "Junior Accountant"}


def test_duplicate_candidate_detected_by_email_across_different_files(api, fake_llm):
    job = post_job(api)
    batch = api.post("/resume-ranker/batches", json={"job_ids": [job["id"]], "expected_files": 2}).json()["batch_id"]
    upload(api, batch, [("alice_v1.pdf", make_pdf(ALICE)), ("alice_v2.pdf", make_pdf(ALICE + "\nUpdated 2024"))])
    drain()
    rows = api.get("/resume-ranker/resumes", params={"hide_duplicates": "false"}).json()["resumes"]
    dup = [r for r in rows if r["duplicate_of"]]
    assert len(rows) == 2 and len(dup) == 1 and dup[0]["duplicate_reason"] == "same email address"
    assert dup[0]["filename"] == "alice_v2.pdf"                                     # later upload points at the earlier one


def test_extract_criteria_from_pasted_jd(api):
    r = api.post("/resume-ranker/jobs/extract-criteria", json={"description": "JOBDESC " + "We need an auditor. " * 5})
    assert r.status_code == 200
    c = r.json()["criteria"]
    assert [s["name"] for s in c["required_skills"]] == ["Audit", "Tally"] and c["education_level"] == "professional"


def test_masked_job_never_sends_identity_to_the_model(api, fake_llm):
    job = post_job(api, mask_personal_info=True)
    batch = api.post("/resume-ranker/batches", json={"job_ids": [job["id"]], "expected_files": 1}).json()["batch_id"]
    upload(api, batch, [("alice.pdf", make_pdf(ALICE))])
    drain()
    scoring_prompts = [u for s, u in fake_llm.calls if "recruiter" in s]
    assert scoring_prompts and all("Alice" not in u and "alice@example.com" not in u and "Deloitte" not in u
                                   for u in scoring_prompts)


# ── general (job-free) ranking: "upload CVs, AI ranks every one, top shows first" ──

def test_general_score_rewards_experience_education_skills_certs_and_caps_at_100():
    empty = parser.general_score({})
    assert empty["total"] == 0.0

    strong = parser.general_score({
        "total_years_experience": 15, "highest_education_level": "doctorate",
        "skills": [f"skill{i}" for i in range(20)], "certifications": ["CA", "CPA", "CFA"],
        "achievements": ["a", "b", "c", "d"],
    })
    assert strong["total"] == 100.0
    assert set(strong["breakdown"]) == {"experience", "education", "skills", "certifications", "achievements"}

    weak = parser.general_score({"total_years_experience": 1, "highest_education_level": "high_school", "skills": ["x"]})
    assert 0 < weak["total"] < strong["total"]


def test_no_job_selected_ranks_every_resume_by_general_score_automatically(api, fake_llm):
    """The core ask: no job needed at all — upload, AI ranks every resume via the free
    general_score, and a plain search already shows the top-ranked resume first."""
    batch = api.post("/resume-ranker/batches", json={"job_ids": [], "expected_files": 2}).json()["batch_id"]
    upload(api, batch, [("alice.pdf", make_pdf(ALICE)), ("bob.docx", make_docx(BOB.split("\n")))])
    drain()

    d = api.get("/resume-ranker/resumes").json()          # no job_id, no ai_rank, no sort — just look
    assert d["total"] == 2
    names = [r["name"] for r in d["resumes"]]
    assert names == ["Alice Sharma", "Bob Rao"]            # Alice: 13y, CA, 5 skills > Bob: 2y, no cert, 1 skill
    assert all(r["general_score"] is not None and r["rank"] is not None for r in d["resumes"])
    assert d["resumes"][0]["rank"] == 1 and d["resumes"][0]["general_score"] > d["resumes"][1]["general_score"]
    # zero LLM calls beyond the two parse calls -- ranking itself cost nothing
    assert len(fake_llm.calls) == 2


def test_general_ranking_never_needs_ai_rank_or_a_job(api, fake_llm):
    batch = api.post("/resume-ranker/batches", json={"job_ids": [], "expected_files": 1}).json()["batch_id"]
    upload(api, batch, [("alice.pdf", make_pdf(ALICE))])
    drain()
    r = api.get("/resume-ranker/resumes", params={"q": "Deloitte"}).json()
    assert r["total"] == 1 and r["resumes"][0]["general_score"] > 0
    assert r["resumes"][0].get("score") is None                 # no paid AI-rank call happened


# ── keyword search matches whole words, not substrings ──

def test_keyword_search_matches_whole_words_only(api, fake_llm):
    """Searching "CA" used to match every CV ("Associate", "Chartered", "Location"...), so the list
    never changed and Search looked broken. It must match the word CA only."""
    batch = api.post("/resume-ranker/batches", json={"job_ids": [], "expected_files": 2}).json()["batch_id"]
    upload(api, batch, [("alice.pdf", make_pdf(ALICE)), ("bob.docx", make_docx(BOB.split("\n")))])
    drain()
    names = lambda **p: sorted(r["name"] for r in api.get("/resume-ranker/resumes", params=p).json()["resumes"])
    assert names() == ["Alice Sharma", "Bob Rao"]
    assert names(q="CA") == ["Alice Sharma"]            # "CA qualified" -- not "Associate"/"Accountant"
    assert names(q="ca") == ["Alice Sharma"]            # case-insensitive
    assert names(q="Account") == []                     # a fragment of "Accountant" is not a word match
    assert names(q="Accountant") == ["Bob Rao"]
    assert names(q="Mumbai", location="mumbai") == ["Alice Sharma"]
    assert names(location="Pun") == []                  # location is whole-word too


# ── delete ──

def test_delete_one_and_bulk_delete_remove_cv_file_and_cached_scores(api, fake_llm):
    import os
    from backend.resume_ranker.db import adhoc_scores, resumes
    batch = api.post("/resume-ranker/batches", json={"job_ids": [], "expected_files": 2}).json()["batch_id"]
    upload(api, batch, [("alice.pdf", make_pdf(ALICE)), ("bob.docx", make_docx(BOB.split("\n")))])
    drain()
    rows = api.get("/resume-ranker/resumes").json()["resumes"]
    alice, bob = rows[0], rows[1]
    from backend.resume_ranker import filestore
    stored = resumes.find_one({"_id": __import__("bson").ObjectId(alice["id"])})
    assert stored.get("file_id") and filestore.has_file(stored)       # CV bytes live in the database
    adhoc_scores.insert_one({"_id": "sig_" + alice["id"], "resume_id": alice["id"], "score": {"total": 50}})

    assert api.delete(f"/resume-ranker/resumes/{alice['id']}").json() == {"success": True}
    assert not filestore.has_file(stored)                              # stored CV file removed
    assert adhoc_scores.count_documents({"resume_id": alice["id"]}) == 0
    assert api.get(f"/resume-ranker/resumes/{alice['id']}").status_code == 404
    assert api.delete(f"/resume-ranker/resumes/{alice['id']}").status_code == 404

    assert api.post("/resume-ranker/resumes/bulk-delete", json={"ids": [bob["id"], "0" * 24]}).json() == {"deleted": 1}
    assert api.get("/resume-ranker/resumes").json()["total"] == 0
    assert api.post("/resume-ranker/resumes/bulk-delete", json={"ids": []}).status_code == 422
    assert api.post("/resume-ranker/resumes/bulk-delete", json={"ids": ["not-an-id"]}).status_code == 404


def test_delete_requires_access(api):
    from backend.resume_ranker.db import holders
    holders.delete_many({})
    assert api.delete("/resume-ranker/resumes/" + "0" * 24).status_code == 403
    assert api.post("/resume-ranker/resumes/bulk-delete", json={"ids": ["0" * 24]}).status_code == 403


def test_cvs_uploaded_before_auto_ranking_get_ranked_without_any_ai_call(api, fake_llm):
    from backend.resume_ranker import router as rr
    from backend.resume_ranker.db import resumes
    batch = api.post("/resume-ranker/batches", json={"job_ids": [], "expected_files": 1}).json()["batch_id"]
    upload(api, batch, [("alice.pdf", make_pdf(ALICE))])
    drain()
    resumes.update_many({}, {"$unset": {"general_score": "", "general_breakdown": ""}})   # simulate an old CV
    assert api.get("/resume-ranker/resumes").json()["resumes"][0]["general_score"] is None
    calls = len(fake_llm.calls)
    assert rr.backfill_general_scores() == 1
    assert rr.backfill_general_scores() == 0                                              # idempotent
    row = api.get("/resume-ranker/resumes").json()["resumes"][0]
    assert row["general_score"] > 0 and row["rank"] == 1
    assert len(fake_llm.calls) == calls                                                   # free: no AI used


# ── department recommendations ──────────────────────────────────────────────

def test_recommend_roles_picks_the_right_departments():
    from backend.resume_ranker.roles import recommend_roles
    hr = {"headline": "HR Executive", "skills": ["Recruitment", "Onboarding", "Payroll", "HRMS"],
          "education": [{"degree": "MBA", "field": "Human Resources"}], "experience": [{"title": "HR Executive"}]}
    data = {"headline": "Data Analyst", "skills": ["Python", "SQL", "Power BI", "Pandas"], "experience": [{"title": "Data Analyst"}]}
    audit = {"skills": ["Statutory audit", "Internal audit", "Tally"], "certifications": ["CA"],
             "experience": [{"title": "Audit Executive"}]}
    assert recommend_roles(hr)[0]["department"] == "Human Resources" and recommend_roles(hr)[0]["fit"] == "Strong"
    assert recommend_roles(data)[0]["department"] == "Data Analytics"
    assert recommend_roles(audit)[0]["department"] == "Audit & Assurance"
    mixed = recommend_roles({"skills": ["Python", "SQL", "Recruitment", "HRMS", "Power BI"], "experience": [{"title": "HR Analyst"}]})
    assert {r["department"] for r in mixed} >= {"Human Resources", "Data Analytics"}
    assert all(r["reasons"] for r in mixed)


def test_recommend_roles_needs_real_evidence():
    from backend.resume_ranker.roles import recommend_roles
    assert recommend_roles(None) == [] and recommend_roles({}) == []
    assert recommend_roles({"skills": ["Microsoft Word"], "experience": []}) == []
    # "CA" only counts as a certification/skill/degree, never as a fragment of ordinary words
    assert recommend_roles({"skills": ["Communication"], "experience": [{"title": "Associate", "summary": "cafe and ca"}]}) == []


def test_recommended_roles_are_stored_and_returned(api, fake_llm):
    from backend.resume_ranker.db import resumes
    from backend.resume_ranker.router import _resume_row, backfill_recommended_roles
    rid = resumes.insert_one({"status": "parsed", "filename": "a.pdf", "parsed": {
        "skills": ["Python", "SQL", "Power BI"], "experience": [{"title": "Data Analyst"}]}}).inserted_id
    assert backfill_recommended_roles() == 1                     # older CV gets them with no AI call
    row = _resume_row(resumes.find_one({"_id": rid}))
    assert row["recommended_roles"][0]["department"] == "Data Analytics"
    assert backfill_recommended_roles() == 0                     # idempotent
