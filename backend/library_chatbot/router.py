"""
JHS Library chatbot API router — mounted at /chatbot/library in main.py.

Ported from the standalone JHS Library FastAPI app (backend/main.py there),
with two differences: every endpoint now sits behind the platform's existing
JWT auth (get_current_user) instead of being open, and /ask persists a
per-user chat history turn (backend/library_chatbot/history.py) the same way
the HR Policy bot does.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.chatbot import upload_history
from backend.chatbot.admin_auth import require_chatbot_admin
from backend.library_chatbot import audit_bot, data_access, history, ingest, search

router = APIRouter(prefix="/chatbot/library", tags=["library-chatbot"])
logger = logging.getLogger("library_chatbot")


class QuestionRequest(BaseModel):
    session_id: str
    question: str
    page: int = 1
    page_size: int = 20


class DraftRequest(BaseModel):
    sector: str = ""
    process_area: str = ""
    description: str = ""


class SessionSummary(BaseModel):
    id: str
    title: str
    updated_at: float


class MessageOut(BaseModel):
    role: str
    content: str
    created_at: Optional[float] = None
    rows: Optional[List[dict]] = None


@router.get("/health")
def library_health():
    return {"status": "ok", "service": "JHS Library Audit Intelligence Assistant"}


@router.get("/facets")
def facets(
    q: str = Query(default=""),
    sector: List[str] = Query(default=[]),
    audit_type: List[str] = Query(default=[]),
    risk: List[str] = Query(default=[]),
    process_area: List[str] = Query(default=[]),
    risk_theme: List[str] = Query(default=[]),
    coso_component: List[str] = Query(default=[]),
    fs_assertion: List[str] = Query(default=[]),
    fraud_risk_indicator: List[str] = Query(default=[]),
    empid: str = Depends(get_current_user),
):
    # Same filter params /observations takes — when any are active, facet
    # options cascade (each field's values reflect every OTHER active
    # filter), so picking one narrows what's worth showing in the rest.
    filters = {
        "sector": sector, "audit_type": audit_type, "risk": risk,
        "process_area": process_area, "risk_theme": risk_theme,
        "coso_component": coso_component, "fs_assertion": fs_assertion,
        "fraud_risk_indicator": fraud_risk_indicator,
    }
    return data_access.get_facets(filters=filters, text_query=q)


@router.get("/observations")
def list_observations(
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sector: List[str] = Query(default=[]),
    audit_type: List[str] = Query(default=[]),
    risk: List[str] = Query(default=[]),
    process_area: List[str] = Query(default=[]),
    risk_theme: List[str] = Query(default=[]),
    coso_component: List[str] = Query(default=[]),
    fs_assertion: List[str] = Query(default=[]),
    fraud_risk_indicator: List[str] = Query(default=[]),
    empid: str = Depends(get_current_user),
):
    filters = {
        "sector": sector, "audit_type": audit_type, "risk": risk,
        "process_area": process_area, "risk_theme": risk_theme,
        "coso_component": coso_component, "fs_assertion": fs_assertion,
        "fraud_risk_indicator": fraud_risk_indicator,
    }
    try:
        rows, total = data_access.query_observations(filters, text_query=q, page=page, page_size=page_size)
        return {"rows": rows, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.error(f"Error listing observations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/observations/{sr_no}")
def observation_detail(sr_no: int, empid: str = Depends(get_current_user)):
    row = data_access.get_by_sr_no(sr_no)
    if row is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    return row


@router.get("/observations/{sr_no}/similar")
def observation_similar(sr_no: int, top_k: int = Query(default=6, ge=1, le=20), empid: str = Depends(get_current_user)):
    try:
        matches = search.similar_by_sr_no(sr_no, top_k=top_k)
        rows = data_access.get_many_by_sr_no([m[0] for m in matches])
        scores = {m[0]: m[1] for m in matches}
        for r in rows:
            r["similarity"] = round(scores.get(r["sr_no"], 0), 3)
        return {"rows": rows}
    except Exception as e:
        logger.error(f"Error finding similar observations for {sr_no}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _persist_turn(empid: str, session_id: str, question: str, answer_html: str, sr_nos: List[int] = None) -> None:
    try:
        history.save_turn(empid, session_id, question, answer_html, sr_nos)
    except Exception:
        logger.exception("Failed to persist library chat turn for empid=%s session=%s", empid, session_id)
    from backend.chatbot import alerts
    alerts.record_if_match(empid, "library", session_id, question)


@router.post("/ask")
def ask_question(payload: QuestionRequest, background_tasks: BackgroundTasks, empid: str = Depends(get_current_user)):
    try:
        logger.info(f"Processing question: {payload.question}")
        result = audit_bot.ask_bot(payload.question, page=payload.page, page_size=payload.page_size)
        if payload.page == 1 and result.get("answer"):
            sr_nos = [r["sr_no"] for r in (result.get("rows") or [])]
            background_tasks.add_task(_persist_turn, empid, payload.session_id, payload.question, result["answer"], sr_nos)
        return result
    except Exception as e:
        logger.error(f"Error processing question: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing question: {e}")


@router.post("/draft")
def draft_finding(payload: DraftRequest, empid: str = Depends(get_current_user)):
    try:
        return audit_bot.draft_bot(payload.sector, payload.process_area, payload.description)
    except Exception as e:
        logger.error(f"Error drafting finding: {e}")
        raise HTTPException(status_code=500, detail=f"Error drafting finding: {e}")


@router.get("/stats")
def get_statistics(empid: str = Depends(get_current_user)):
    try:
        return data_access.get_stats()
    except Exception as e:
        logger.error(f"Error fetching statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions", response_model=List[SessionSummary])
def get_sessions(empid: str = Depends(get_current_user)):
    return history.list_sessions(empid)


@router.get("/session/{session_id}/messages", response_model=List[MessageOut])
def get_session_messages(session_id: str, empid: str = Depends(get_current_user)):
    return history.get_messages(empid, session_id)


@router.delete("/session/{session_id}")
def delete_session(session_id: str, empid: str = Depends(get_current_user)):
    history.delete_session(empid, session_id)
    return {"status": "deleted"}


# ─────────────────────────────────────────────────────────────────────────────
# Admin — observation library knowledge-base management (Update / Replace)
# ─────────────────────────────────────────────────────────────────────────────
# Gated by the shared "chatbot" module admin check (backend/chatbot/admin_auth.py
# — same one HR/RCM's admin endpoints use). Only ever touches the observations
# collection + the "consolidated_v1" Pinecone namespace — never chat history.

@router.get("/admin/knowledge/stats")
def library_knowledge_stats(empid: str = Depends(require_chatbot_admin)):
    return ingest.stats()


@router.get("/admin/knowledge/history")
def library_knowledge_history(empid: str = Depends(require_chatbot_admin)):
    return upload_history.list_uploads("library")


_SUPPORTED_EXTS = ingest.TABULAR_EXTS + ("pdf", "docx", "txt", "json")


def _validate_upload(file: UploadFile) -> None:
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in _SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: .{ext}. Supported: {', '.join('.' + e for e in _SUPPORTED_EXTS)}",
        )


@router.post("/admin/knowledge/update")
async def library_knowledge_update(empid: str = Depends(require_chatbot_admin), file: UploadFile = File(...)):
    """Appends the uploaded file's rows (renumbered after the current
    highest Sr. No.) alongside every existing observation — nothing
    existing is removed or overwritten. Tabular files (.xlsx/.xls/.csv)
    become normal faceted observations; anything else (.pdf/.docx/.txt/
    .json) becomes "unclassified" observations — see ingest.py."""
    _validate_upload(file)
    content = await file.read()
    try:
        result = ingest.update(file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    upload_history.record_upload("library", empid, "update", file.filename, result.get("rows_inserted", 0))
    return {"file": file.filename, **result}


@router.post("/admin/knowledge/replace")
async def library_knowledge_replace(empid: str = Depends(require_chatbot_admin), file: UploadFile = File(...)):
    """Deletes EVERY existing observation, then ingests only this file's
    rows — full replace, matching the standalone project's ingest script."""
    _validate_upload(file)
    content = await file.read()
    try:
        result = ingest.replace(file.filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    upload_history.record_upload("library", empid, "replace", file.filename, result.get("rows_inserted", 0))
    return {"file": file.filename, **result}
