# backend/hr_policy_quiz/router.py
"""
HR Policy onboarding quiz — mounted under /hr-quiz on the main JHS
Platform API. HR dashboard access is bridged from the main platform's
employee login (see /api/platform-access + db.hr_quiz_admins); quiz candidates
get their own separate JWT (see security.py), stored in the frontend
under a different localStorage key.
"""
import random
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response, status

from backend.auth import get_current_user
from backend.hr_policy_quiz.config import settings
from backend.hr_policy_quiz.db import candidates, documents, questions, attempts, deleted_candidates, hr_quiz_admins, quiz_sets
from backend.hr_policy_quiz.schemas import (
    CandidateLoginRequest,
    AddCandidatesRequest,
    RegeneratePasswordRequest,
    SubmitQuizRequest,
    CreateQuizSetRequest,
    UpdateQuizSetRequest,
)
from backend.hr_policy_quiz.security import (
    hash_password,
    verify_password,
    generate_password,
    create_token,
    get_current_hr,
    get_current_candidate,
)
from backend.hr_policy_quiz import rag, reports

router = APIRouter(prefix="/hr-quiz", tags=["HR Policy Quiz"])


def now():
    return datetime.now(timezone.utc)


def _is_admin_empid(empid: str) -> bool:
    empid = empid.strip().upper()
    if hr_quiz_admins.find_one({"empid": empid}):
        return True
    # Case-insensitive fallback, in case someone inserts a code manually
    # from Compass in lowercase or mixed case.
    return hr_quiz_admins.find_one({"empid": {"$regex": f"^{empid}$", "$options": "i"}}) is not None


# ---------------------------------------------------------------------------
# Bridge auth: lets an already-logged-in JHS Timesnap employee (identified by
# their normal platform token) straight into the HR dashboard, with no
# separate hr-login step, IF their employee code is in the admins collection.
# ---------------------------------------------------------------------------

@router.get("/api/platform-access")
def platform_access(current_user: str = Depends(get_current_user)):
    empid = current_user.strip().upper()
    if not _is_admin_empid(empid):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for the HR Policy Quiz dashboard")
    token = create_token(empid, "hr", settings.HR_TOKEN_EXPIRE_MINUTES)
    return {"access_token": token, "name": empid}


# ---------------------------------------------------------------------------
# HR: document upload + RAG question generation
# ---------------------------------------------------------------------------

@router.post("/api/hr/documents")
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    category: str = Form(""),
    hr=Depends(get_current_hr),
):
    raw = await file.read()
    text = rag.extract_text(raw, file.filename)
    chunks = rag.chunk_text(text)
    if len(chunks) < 1:
        raise HTTPException(status_code=400, detail="Could not read any usable text from this file")

    doc_id = str(uuid.uuid4())
    pool = rag.build_question_pool(chunks)
    if len(pool) < settings.QUIZ_QUESTION_COUNT:
        raise HTTPException(
            status_code=422,
            detail=f"Only generated {len(pool)} usable questions, need at least {settings.QUIZ_QUESTION_COUNT}. Try a longer document.",
        )

    documents.insert_one(
        {
            "_id": doc_id,
            "title": title,
            "category": category.strip(),
            "filename": file.filename,
            "chunk_count": len(chunks),
            "uploaded_by": hr["sub"],
            "uploaded_at": now(),
        }
    )
    questions.insert_one({"_id": doc_id, "document_id": doc_id, "pool": pool})

    return {"document_id": doc_id, "title": title, "category": category.strip(), "question_pool_size": len(pool)}


@router.get("/api/hr/documents")
def list_documents(hr=Depends(get_current_hr)):
    docs = list(documents.find({}, {"_id": 1, "title": 1, "category": 1, "filename": 1, "uploaded_at": 1, "chunk_count": 1}))
    pools = {p["_id"]: len(p["pool"]) for p in questions.find({}, {"pool": 1})}
    for d in docs:
        d["document_id"] = d.pop("_id")
        d["question_pool_size"] = pools.get(d["document_id"], 0)
    return docs


@router.delete("/api/hr/documents/{document_id}")
def delete_document(document_id: str, hr=Depends(get_current_hr)):
    doc = documents.find_one({"_id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    in_use = quiz_sets.find_one({"documents.document_id": document_id})
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=f"This document is used by the quiz set \"{in_use['name']}\". Remove it from that quiz set first.",
        )

    # Only removes the document + its generated question pool. Candidates
    # and their attempt history (candidates, attempts collections) are
    # never touched here, so past results stay intact.
    documents.delete_one({"_id": document_id})
    questions.delete_one({"_id": document_id})
    return {"deleted": True}


# ---------------------------------------------------------------------------
# HR: quiz sets (multiple documents mixed together with a per-document
# question-count weightage - e.g. 7 from "HR Handbook", 8 from "IT Policy").
# A candidate is assigned one quiz set; at quiz time the questions are
# randomly sampled from each document's pool per its weight and combined.
# ---------------------------------------------------------------------------

def _build_quiz_set_documents(entries) -> tuple[list, int]:
    """Validates each document exists and has enough pooled questions for
    the requested weight. Returns (denormalized entries, total_questions)."""
    doc_entries = []
    total = 0
    for entry in entries:
        doc = documents.find_one({"_id": entry.document_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {entry.document_id} not found")
        pool_doc = questions.find_one({"_id": entry.document_id})
        pool_size = len(pool_doc["pool"]) if pool_doc else 0
        if pool_size < entry.count:
            raise HTTPException(
                status_code=422,
                detail=f"\"{doc['title']}\" only has {pool_size} questions available, cannot draw {entry.count}",
            )
        doc_entries.append({"document_id": entry.document_id, "document_title": doc["title"], "count": entry.count})
        total += entry.count
    return doc_entries, total


@router.post("/api/hr/quiz-sets")
def create_quiz_set(body: CreateQuizSetRequest, hr=Depends(get_current_hr)):
    doc_entries, total = _build_quiz_set_documents(body.documents)

    quiz_set_id = str(uuid.uuid4())
    quiz_sets.insert_one(
        {
            "_id": quiz_set_id,
            "name": body.name.strip(),
            "documents": doc_entries,
            "total_questions": total,
            "created_by": hr["sub"],
            "created_at": now(),
            "updated_at": now(),
        }
    )
    return {"quiz_set_id": quiz_set_id, "name": body.name.strip(), "documents": doc_entries, "total_questions": total}


@router.get("/api/hr/quiz-sets")
def list_quiz_sets(hr=Depends(get_current_hr)):
    sets = list(quiz_sets.find({}))
    for s in sets:
        s["quiz_set_id"] = s.pop("_id")
    sets.sort(key=lambda s: s.get("created_at") or now(), reverse=True)
    return sets


@router.put("/api/hr/quiz-sets/{quiz_set_id}")
def update_quiz_set(quiz_set_id: str, body: UpdateQuizSetRequest, hr=Depends(get_current_hr)):
    existing = quiz_sets.find_one({"_id": quiz_set_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Quiz set not found")

    update = {"updated_at": now()}
    if body.name is not None:
        update["name"] = body.name.strip()
    if body.documents is not None:
        doc_entries, total = _build_quiz_set_documents(body.documents)
        update["documents"] = doc_entries
        update["total_questions"] = total

    quiz_sets.update_one({"_id": quiz_set_id}, {"$set": update})
    updated = quiz_sets.find_one({"_id": quiz_set_id})
    updated["quiz_set_id"] = updated.pop("_id")
    return updated


@router.delete("/api/hr/quiz-sets/{quiz_set_id}")
def delete_quiz_set(quiz_set_id: str, hr=Depends(get_current_hr)):
    in_use = candidates.find_one({"quiz_set_id": quiz_set_id})
    if in_use:
        raise HTTPException(
            status_code=409,
            detail="This quiz set has candidates assigned to it. Reassign or delete them first.",
        )
    result = quiz_sets.delete_one({"_id": quiz_set_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Quiz set not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# HR: candidate (new joiner) management
# ---------------------------------------------------------------------------

@router.post("/api/hr/candidates")
def add_candidates(body: AddCandidatesRequest, hr=Depends(get_current_hr)):
    quiz_set = quiz_sets.find_one({"_id": body.quiz_set_id})
    if not quiz_set:
        raise HTTPException(status_code=404, detail="Selected quiz set does not exist")

    shared_password = generate_password()
    password_hash = hash_password(shared_password)
    created = []
    for raw_email in body.emails:
        email = raw_email.lower().strip()
        candidates.update_one(
            {"email": email},
            {
                "$set": {
                    "email": email,
                    "password_hash": password_hash,
                    "quiz_set_id": body.quiz_set_id,
                    "quiz_set_name": quiz_set["name"],
                    "updated_at": now(),
                },
                "$setOnInsert": {"created_at": now(), "created_by": hr["sub"]},
            },
            upsert=True,
        )
        created.append(email)

    return {"emails": created, "password": shared_password, "quiz_set_name": quiz_set["name"]}


@router.post("/api/hr/candidates/regenerate-password")
def regenerate_password(body: RegeneratePasswordRequest, hr=Depends(get_current_hr)):
    """Works for one email or many. Every listed email gets the SAME new
    password (handy for a batch), call it once per email for individual
    regeneration."""
    new_password = generate_password()
    password_hash = hash_password(new_password)
    updated = []
    for raw_email in body.emails:
        email = raw_email.lower().strip()
        result = candidates.update_one(
            {"email": email}, {"$set": {"password_hash": password_hash, "updated_at": now()}}
        )
        if result.matched_count:
            updated.append(email)

    if not updated:
        raise HTTPException(status_code=404, detail="None of these emails are registered candidates yet")

    return {"emails": updated, "password": new_password}


@router.delete("/api/hr/candidates/{email}")
def delete_candidate(email: str, hr=Depends(get_current_hr)):
    email = email.lower().strip()
    candidate = candidates.find_one({"email": email})
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    candidate_attempts = list(attempts.find({"candidate_email": email}))
    for a in candidate_attempts:
        a["session_id"] = a.pop("_id")

    candidate.pop("_id", None)
    deleted_candidates.insert_one(
        {
            "_id": str(uuid.uuid4()),
            **candidate,
            "attempts": candidate_attempts,
            "deleted_at": now(),
            "deleted_by": hr["sub"],
        }
    )

    candidates.delete_one({"email": email})
    attempts.delete_many({"candidate_email": email})
    return {"deleted": True}


@router.get("/api/hr/candidates/deleted")
def list_deleted_candidates(hr=Depends(get_current_hr)):
    docs = list(deleted_candidates.find({}).sort("deleted_at", -1))
    for d in docs:
        d["record_id"] = str(d.pop("_id"))
    return docs


@router.get("/api/hr/candidates")
def list_candidates(hr=Depends(get_current_hr)):
    result = []
    for c in candidates.find({}):
        latest_attempt = attempts.find_one(
            {"candidate_email": c["email"], "status": "completed"}, sort=[("submitted_at", -1)]
        )
        in_progress = attempts.find_one({"candidate_email": c["email"], "status": "in_progress"})
        result.append(
            {
                "email": c["email"],
                "quiz_set_name": c.get("quiz_set_name"),
                "created_at": c.get("created_at"),
                "status": "completed" if latest_attempt else ("in_progress" if in_progress else "not_started"),
                "score": latest_attempt["score"] if latest_attempt else None,
                "total_questions": latest_attempt["total_questions"] if latest_attempt else None,
                "submitted_at": latest_attempt["submitted_at"] if latest_attempt else None,
            }
        )
    result.sort(key=lambda r: r["created_at"], reverse=True)
    return result


@router.get("/api/hr/candidates/export.xlsx")
def export_candidates_xlsx(hr=Depends(get_current_hr)):
    content = reports.generate_excel(reports.gather_report_rows())
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=candidates-report.xlsx"},
    )


@router.get("/api/hr/candidates/export.docx")
def export_candidates_docx(hr=Depends(get_current_hr)):
    content = reports.generate_docx(reports.gather_report_rows())
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=candidates-report.docx"},
    )


@router.get("/api/hr/candidates/export.pdf")
def export_candidates_pdf(hr=Depends(get_current_hr)):
    content = reports.generate_pdf(reports.gather_report_rows())
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=candidates-report.pdf"},
    )


def _backfill_document_titles(attempt: dict) -> None:
    """Ensures every answers_detail item has a document_title, so both the
    per-question tag AND the score-by-document summary work in the HR
    dashboard's "View answers" modal. Newer attempts already have this on
    each answer (tagged at quiz-start time); older attempts (recorded
    before that existed) are backfilled here - NOT by matching question
    text against the full document pools, since different documents can
    (and in practice do) generate near-identical or duplicate-sounding
    questions, which would silently mis-attribute a question. Instead,
    match text against THIS attempt's own question_snapshot (15-ish
    questions, effectively never has an internal duplicate) to recover the
    reliable globally-unique question id, then resolve that id against the
    quiz set's pools - ids never collide across documents, so this is
    exact. Mutates attempt["answers_detail"] in place."""
    answers = attempt.get("answers_detail") or []
    if not answers or all(a.get("document_title") for a in answers):
        return

    quiz_set = quiz_sets.find_one({"_id": attempt.get("quiz_set_id")})
    snapshot = attempt.get("question_snapshot") or []
    if not quiz_set or not snapshot:
        return

    id_to_title = {}
    for entry in quiz_set["documents"]:
        pool_doc = questions.find_one({"_id": entry["document_id"]})
        if pool_doc:
            for q in pool_doc["pool"]:
                id_to_title[q["id"]] = entry["document_title"]
    text_to_id = {q["question"]: q["id"] for q in snapshot}

    for a in answers:
        if not a.get("document_title"):
            a["document_title"] = id_to_title.get(text_to_id.get(a["question"]), "Unknown")


def _score_by_document(attempt: dict) -> list:
    """Per-document correct/total breakdown for a completed attempt (e.g.
    "HR Handbook: 6/8", "IT Policy: 5/7"). Call _backfill_document_titles
    first so this works for both new and older attempts alike."""
    breakdown = {}
    for a in attempt.get("answers_detail") or []:
        title = a.get("document_title") or "Unknown"
        b = breakdown.setdefault(title, {"document_title": title, "correct": 0, "total": 0})
        b["total"] += 1
        if a.get("is_correct"):
            b["correct"] += 1
    return list(breakdown.values())


@router.get("/api/hr/candidates/{email}/attempts")
def candidate_attempts(email: str, hr=Depends(get_current_hr)):
    docs = list(
        attempts.find(
            {"candidate_email": email.lower()},
            {"answers_detail": 1, "score": 1, "total_questions": 1, "submitted_at": 1, "started_at": 1, "status": 1, "quiz_set_id": 1, "question_snapshot": 1},
        )
    )
    for d in docs:
        _backfill_document_titles(d)
        d["score_by_document"] = _score_by_document(d)
        d.pop("question_snapshot", None)  # internal only (has correct_index/ids) - not part of the public shape
        d["attempt_id"] = str(d.pop("_id"))
    docs.sort(key=lambda d: d.get("started_at") or now(), reverse=True)
    return docs


# ---------------------------------------------------------------------------
# Candidate auth
# ---------------------------------------------------------------------------

@router.post("/api/candidate/login")
def candidate_login(body: CandidateLoginRequest):
    user = candidates.find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    token = create_token(user["email"], "candidate", settings.CANDIDATE_TOKEN_EXPIRE_MINUTES)
    return {"access_token": token, "quiz_set_name": user.get("quiz_set_name")}


# ---------------------------------------------------------------------------
# Candidate: take the quiz
# ---------------------------------------------------------------------------

@router.post("/api/candidate/quiz/start")
def start_quiz(candidate=Depends(get_current_candidate)):
    email = candidate["sub"]
    user = candidates.find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="Candidate not found")

    existing = attempts.find_one({"candidate_email": email, "status": "completed"})
    if existing:
        raise HTTPException(status_code=409, detail="You have already completed this quiz")

    quiz_set = quiz_sets.find_one({"_id": user["quiz_set_id"]})
    if not quiz_set:
        raise HTTPException(status_code=500, detail="Quiz is not ready yet, please contact HR")

    # Weighted mix: draw `count` random questions from each document's pool
    # per the quiz set's composition, then shuffle so they don't cluster by
    # source document. Each question is tagged with where it came from so
    # the HR dashboard can later show a per-document score breakdown.
    selected: list = []
    for entry in quiz_set["documents"]:
        pool_doc = questions.find_one({"_id": entry["document_id"]})
        pool = pool_doc["pool"] if pool_doc else []
        if len(pool) < entry["count"]:
            raise HTTPException(status_code=500, detail="Quiz is not ready yet, please contact HR")
        for q in random.sample(pool, entry["count"]):
            selected.append({**q, "document_id": entry["document_id"], "document_title": entry["document_title"]})
    random.shuffle(selected)

    session_id = str(uuid.uuid4())

    attempts.insert_one(
        {
            "_id": session_id,
            "candidate_email": email,
            "quiz_set_id": user["quiz_set_id"],
            "status": "in_progress",
            "started_at": now(),
            "seconds_per_question": settings.SECONDS_PER_QUESTION,
            "question_snapshot": selected,  # includes correct_index, never sent to frontend
        }
    )

    public_questions = [
        {"question_id": q["id"], "question": q["question"], "options": q["options"]} for q in selected
    ]
    return {
        "session_id": session_id,
        "seconds_per_question": settings.SECONDS_PER_QUESTION,
        "questions": public_questions,
    }


@router.post("/api/candidate/quiz/submit")
def submit_quiz(body: SubmitQuizRequest, candidate=Depends(get_current_candidate)):
    email = candidate["sub"]
    attempt = attempts.find_one({"_id": body.session_id, "candidate_email": email})
    if not attempt:
        raise HTTPException(status_code=404, detail="Quiz session not found")
    if attempt["status"] == "completed":
        raise HTTPException(status_code=409, detail="This quiz was already submitted")

    correct_by_id = {q["id"]: q["correct_index"] for q in attempt["question_snapshot"]}
    meta_by_id = {
        q["id"]: (q["question"], q["options"], q.get("document_id", ""), q.get("document_title", ""))
        for q in attempt["question_snapshot"]
    }

    score = 0
    detail = []
    for ans in body.answers:
        correct_index = correct_by_id.get(ans.question_id)
        if correct_index is None:
            continue
        is_correct = ans.selected_option == correct_index
        if is_correct:
            score += 1
        q_text, options, doc_id, doc_title = meta_by_id[ans.question_id]
        detail.append(
            {
                "question": q_text,
                "options": options,
                "selected_option": ans.selected_option,
                "correct_index": correct_index,
                "is_correct": is_correct,
                "time_taken_seconds": ans.time_taken_seconds,
                "document_id": doc_id,
                "document_title": doc_title,
            }
        )

    attempts.update_one(
        {"_id": body.session_id},
        {
            "$set": {
                "status": "completed",
                "submitted_at": now(),
                "score": score,
                "total_questions": len(attempt["question_snapshot"]),
                "answers_detail": detail,
            }
        },
    )

    return {"score": score, "total_questions": len(attempt["question_snapshot"]), "answers_detail": detail}


@router.get("/api/health")
def health():
    return {"status": "ok"}
