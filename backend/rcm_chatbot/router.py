"""
RCM chatbot API router — mounted at /chatbot/rcm in main.py.

Chat endpoints follow the same shape/auth as backend/chatbot/router.py
(get_current_user resolves empid from the Bearer token; SSE events are
{"type": "chunk"|"done"|"error"}). Admin endpoints (upload/manage the
knowledge base) are additionally gated by _require_rcm_admin, copied from
backend/timesheet/timesheet_admin.py's admin-check pattern.
"""
import json
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.chatbot.admin_auth import require_chatbot_admin
from backend.rcm_chatbot import answer, history, ingest
from backend.rcm_chatbot.config import rcm_settings
from backend.rcm_chatbot.parsers import parse_file
from backend.rcm_chatbot.vectorstore import list_namespaces, namespace_stats

router = APIRouter(prefix="/chatbot/rcm", tags=["rcm-chatbot"])
logger = logging.getLogger("rcm_chatbot")

# Kept as a local alias so the rest of this file's `Depends(_require_rcm_admin)`
# call sites don't need to change — see backend/chatbot/admin_auth.py for the
# actual (shared, HR/RCM/Library) check.
_require_rcm_admin = require_chatbot_admin


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    answer: str
    sources: List[str]
    from_cache: bool
    follow_ups: List[str] = []


class SessionSummary(BaseModel):
    id: str
    title: str
    updated_at: float


class MessageOut(BaseModel):
    role: str
    content: str
    created_at: Optional[float] = None


class CollectionSummary(BaseModel):
    name: str
    pretty_name: str
    rows: int


# ─────────────────────────────────────────────────────────────────────────────
# Chat endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
def rcm_health():
    return {"status": "ok", "configured": answer.is_configured()}


def _persist_turn(empid: str, session_id: str, user_message: str, reply: str) -> None:
    try:
        history.save_turn(empid, session_id, user_message, reply)
    except Exception:
        logger.exception("Failed to persist RCM chat turn for empid=%s session=%s", empid, session_id)
    from backend.chatbot import alerts
    alerts.record_if_match(empid, "rcm", session_id, user_message)


def _recent_context(empid: str, session_id: str) -> List[dict]:
    try:
        return history.get_recent_messages(empid, session_id, rcm_settings.SESSION_HISTORY_TURNS)
    except Exception:
        logger.exception("Failed to load RCM chat history for empid=%s session=%s", empid, session_id)
        return []


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, background_tasks: BackgroundTasks, empid: str = Depends(get_current_user)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    context = _recent_context(empid, req.session_id)
    reply, sources, from_cache, follow_ups = answer.answer_query(req.message, context)

    background_tasks.add_task(_persist_turn, empid, req.session_id, req.message, reply)
    return ChatResponse(answer=reply, sources=sources, from_cache=from_cache, follow_ups=follow_ups)


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, empid: str = Depends(get_current_user)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    context = _recent_context(empid, req.session_id)

    def event_stream():
        full_answer: List[str] = []
        try:
            for event in answer.answer_query_stream(req.message, context):
                if event.get("type") == "chunk":
                    full_answer.append(event["text"])
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            logger.exception("Unexpected failure streaming RCM chat reply for empid=%s", empid)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong generating a reply. Please try again.'})}\n\n"
            return

        reply = "".join(full_answer)
        if reply:
            _persist_turn(empid, req.session_id, req.message, reply)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/sessions", response_model=List[SessionSummary])
def get_sessions(empid: str = Depends(get_current_user)):
    return history.list_sessions(empid)


@router.get("/session/{session_id}/messages", response_model=List[MessageOut])
def get_session_messages(session_id: str, empid: str = Depends(get_current_user)):
    return history.get_messages(empid, session_id)


@router.post("/session/{session_id}/reset")
def reset_session(session_id: str, empid: str = Depends(get_current_user)):
    history.delete_session(empid, session_id)
    return {"status": "cleared"}


@router.delete("/session/{session_id}")
def delete_session(session_id: str, empid: str = Depends(get_current_user)):
    history.delete_session(empid, session_id)
    return {"status": "deleted"}


@router.post("/new-session")
def new_session(empid: str = Depends(get_current_user)):
    return {"session_id": str(uuid.uuid4())}


# ─────────────────────────────────────────────────────────────────────────────
# Admin endpoints — manage the knowledge base
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/collections")
def list_collections(empid: str = Depends(_require_rcm_admin)):
    from backend.rcm_chatbot.search import pretty_name
    stats = namespace_stats()
    return [
        {"name": name, "pretty_name": pretty_name(name), "rows": count}
        for name, count in sorted(stats.items())
    ]


@router.post("/admin/collections/{name}/upload")
async def upload_file(name: str, empid: str = Depends(_require_rcm_admin), file: UploadFile = File(...)):
    content = await file.read()
    try:
        sheets = parse_file(file.filename, content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    inserted = ingest.ingest_sheets(name, file.filename, sheets)
    return {
        "collection": name,
        "file": file.filename,
        "rows_inserted": inserted,
    }


@router.post("/admin/collections/bulk-upload")
async def bulk_upload(empid: str = Depends(_require_rcm_admin), files: List[UploadFile] = File(...)):
    """Upload several files at once — each becomes its own namespace
    (auto-named from its filename), same as a single upload does, just
    looped over everything picked from the folder."""
    used_names = set(list_namespaces())
    results = []
    total_rows = 0
    for f in files:
        base_name = ingest.slugify(f.filename)
        coll_name, i = base_name, 2
        while coll_name in used_names:
            coll_name = f"{base_name}_{i}"
            i += 1

        content = await f.read()
        try:
            sheets = parse_file(f.filename, content)
        except Exception as e:
            results.append({"file": f.filename, "error": str(e)})
            continue

        used_names.add(coll_name)
        inserted = ingest.ingest_sheets(coll_name, f.filename, sheets)
        total_rows += inserted
        results.append({"file": f.filename, "collection": coll_name, "rows_inserted": inserted})

    return {
        "files_processed": len(files),
        "files_succeeded": sum(1 for r in results if "collection" in r),
        "rows_imported": total_rows,
        "results": results,
    }


@router.delete("/admin/collections/{name}")
def delete_collection(name: str, empid: str = Depends(_require_rcm_admin)):
    ingest.delete_namespace(name)
    return {"status": "deleted"}


@router.delete("/admin/collections/{name}/files")
def delete_file(name: str, filename: str, empid: str = Depends(_require_rcm_admin)):
    """Each namespace holds exactly one file's rows (see ingest.py), so
    removing "the file" from a namespace is the same as dropping the whole
    namespace — filename is accepted (and matched loosely) only to keep the
    same request shape the admin UI already uses."""
    ingest.delete_namespace(name)
    return {"status": "deleted"}
