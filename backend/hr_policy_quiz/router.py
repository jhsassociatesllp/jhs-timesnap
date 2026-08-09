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
from backend.hr_policy_quiz.db import candidates, documents, questions, attempts, deleted_candidates, hr_quiz_admins
from backend.hr_policy_quiz.schemas import (
    CandidateLoginRequest,
    AddCandidatesRequest,
    RegeneratePasswordRequest,
    SubmitQuizRequest,
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
            "filename": file.filename,
            "chunk_count": len(chunks),
            "uploaded_by": hr["sub"],
            "uploaded_at": now(),
        }
    )
    questions.insert_one({"_id": doc_id, "document_id": doc_id, "pool": pool})

    return {"document_id": doc_id, "title": title, "question_pool_size": len(pool)}


@router.get("/api/hr/documents")
def list_documents(hr=Depends(get_current_hr)):
    docs = list(documents.find({}, {"_id": 1, "title": 1, "filename": 1, "uploaded_at": 1, "chunk_count": 1}))
    for d in docs:
        d["document_id"] = d.pop("_id")
    return docs


@router.delete("/api/hr/documents/{document_id}")
def delete_document(document_id: str, hr=Depends(get_current_hr)):
    doc = documents.find_one({"_id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Only removes the document + its generated question pool. Candidates
    # and their attempt history (candidates, attempts collections) are
    # never touched here, so past results stay intact.
    documents.delete_one({"_id": document_id})
    questions.delete_one({"_id": document_id})
    return {"deleted": True}


# ---------------------------------------------------------------------------
# HR: candidate (new joiner) management
# ---------------------------------------------------------------------------

@router.post("/api/hr/candidates")
def add_candidates(body: AddCandidatesRequest, hr=Depends(get_current_hr)):
    doc = documents.find_one({"_id": body.document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Selected document does not exist")

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
                    "document_id": body.document_id,
                    "document_title": doc["title"],
                    "updated_at": now(),
                },
                "$setOnInsert": {"created_at": now(), "created_by": hr["sub"]},
            },
            upsert=True,
        )
        created.append(email)

    return {"emails": created, "password": shared_password, "document_title": doc["title"]}


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
                "document_title": c.get("document_title"),
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


@router.get("/api/hr/candidates/{email}/attempts")
def candidate_attempts(email: str, hr=Depends(get_current_hr)):
    docs = list(
        attempts.find({"candidate_email": email.lower()}, {"answers_detail": 1, "score": 1, "total_questions": 1, "submitted_at": 1, "started_at": 1, "status": 1})
    )
    for d in docs:
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
    return {"access_token": token, "document_title": user.get("document_title")}


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

    pool_doc = questions.find_one({"_id": user["document_id"]})
    if not pool_doc or len(pool_doc["pool"]) < settings.QUIZ_QUESTION_COUNT:
        raise HTTPException(status_code=500, detail="Quiz is not ready yet, please contact HR")

    selected = random.sample(pool_doc["pool"], settings.QUIZ_QUESTION_COUNT)
    session_id = str(uuid.uuid4())

    attempts.insert_one(
        {
            "_id": session_id,
            "candidate_email": email,
            "document_id": user["document_id"],
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
    text_by_id = {q["id"]: (q["question"], q["options"]) for q in attempt["question_snapshot"]}

    score = 0
    detail = []
    for ans in body.answers:
        correct_index = correct_by_id.get(ans.question_id)
        if correct_index is None:
            continue
        is_correct = ans.selected_option == correct_index
        if is_correct:
            score += 1
        q_text, options = text_by_id[ans.question_id]
        detail.append(
            {
                "question": q_text,
                "options": options,
                "selected_option": ans.selected_option,
                "correct_index": correct_index,
                "is_correct": is_correct,
                "time_taken_seconds": ans.time_taken_seconds,
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
