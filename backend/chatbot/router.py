"""
Chatbot API router — mounted at /chatbot in main.py.

All endpoints are protected by the existing JWT auth (get_current_user),
which automatically resolves the logged-in employee's empid from the Bearer
token. This means chat history is automatically scoped per-user without
any extra session management on the frontend.
"""
import json
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.chatbot import rag, cache, history, assistant, ingest_policy, multi_format, admin_stats, usage, alerts, upload_history
from backend.chatbot.admin_auth import require_chatbot_admin
from backend.chatbot.config import chatbot_settings
from backend.chatbot.vectorstore import get_index
from backend.database import employee_details_collection

router = APIRouter(prefix="/chatbot", tags=["chatbot"])
logger = logging.getLogger("chatbot")


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


class GreetingOut(BaseModel):
    name: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
def chatbot_health():
    """Health check — also returns FAQ cache stats."""
    return {"status": "ok", **cache.stats()}


def _persist_turn(empid: str, session_id: str, user_message: str, answer: str) -> None:
    """Runs AFTER the HTTP response has already gone out (see BackgroundTasks
    below) — Mongo writes never add to the reply latency the employee feels.
    Any failure here is logged, not raised, since the user already has their
    answer and there's nothing left to return an error to. Used by the
    HR-dedicated /chat and /chat/stream endpoints, always HR's own history."""
    try:
        history.save_turn(empid, session_id, user_message, answer)
    except Exception:
        logger.exception("Failed to persist chat turn for empid=%s session=%s", empid, session_id)
    alerts.record_if_match(empid, "hr", session_id, user_message)


def _persist_assistant_turn(empid: str, session_id: str, user_message: str, answer: str, bot: str) -> None:
    """Same as _persist_turn, but for the floating assistant bubble, which
    can answer via ANY of the three bots — routes into THAT bot's own
    history collection instead of always defaulting to HR's, which
    previously made an RCM- or Library-answered question asked through the
    bubble show up in the HR tab's own chat history sidebar."""
    try:
        if bot == "rcm":
            from backend.rcm_chatbot import history as rcm_history
            rcm_history.save_turn(empid, session_id, user_message, answer)
        elif bot == "library":
            from backend.library_chatbot import history as library_history
            library_history.save_turn(empid, session_id, user_message, answer)
        else:
            history.save_turn(empid, session_id, user_message, answer)
    except Exception:
        logger.exception("Failed to persist assistant chat turn for empid=%s session=%s bot=%s", empid, session_id, bot)
    alerts.record_if_match(empid, bot, session_id, user_message)


def _recent_context(empid: str, session_id: str) -> List[dict]:
    """Wrapped so a Mongo hiccup degrades to 'no memory of earlier turns'
    instead of failing the whole request — the employee still gets an answer."""
    try:
        return history.get_recent_messages(empid, session_id, chatbot_settings.SESSION_HISTORY_TURNS)
    except Exception:
        logger.exception("Failed to load chat history for empid=%s session=%s", empid, session_id)
        return []


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, background_tasks: BackgroundTasks, empid: str = Depends(get_current_user)):
    """Send a message and get an AI response. History is saved per user (empid),
    written to MongoDB in the background so DB latency never delays the reply."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    context = _recent_context(empid, req.session_id)

    try:
        answer, sources, from_cache, follow_ups = rag.answer_query(req.message, context)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        # Covers non-RuntimeError failures from dependencies (e.g. Pinecone's
        # own exception types on a network/TLS hiccup) — the employee should
        # see a clean "try again" message, not a raw 500 traceback.
        logger.exception("Unexpected failure answering chat message for empid=%s", empid)
        raise HTTPException(status_code=502, detail="Something went wrong generating a reply. Please try again.")

    background_tasks.add_task(_persist_turn, empid, req.session_id, req.message, answer)

    return ChatResponse(answer=answer, sources=sources, from_cache=from_cache, follow_ups=follow_ups)


@router.post("/chat/stream")
def chat_stream(req: ChatRequest, empid: str = Depends(get_current_user)):
    """Same as /chat, but streams the answer token-by-token over Server-Sent
    Events so the employee sees words appear immediately instead of waiting
    for the full reply. Each event is a JSON line:
      {"type": "chunk", "text": "..."}
      {"type": "done", "sources": [...], "from_cache": bool}
      {"type": "error", "message": "..."}
    History is persisted once the stream finishes."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    context = _recent_context(empid, req.session_id)

    def event_stream():
        full_answer: List[str] = []
        try:
            for event in rag.answer_query_stream(req.message, context):
                if event.get("type") == "chunk":
                    full_answer.append(event["text"])
                yield f"data: {json.dumps(event)}\n\n"
        except RuntimeError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return
        except Exception:
            # Non-RuntimeError failures (e.g. Pinecone's own exception types
            # on a network/TLS hiccup) would otherwise kill the SSE stream
            # silently mid-response. Surface a clean error event instead.
            logger.exception("Unexpected failure streaming chat reply for empid=%s", empid)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong generating a reply. Please try again.'})}\n\n"
            return

        answer = "".join(full_answer)
        if answer:
            _persist_turn(empid, req.session_id, req.message, answer)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/assistant/chat/stream")
def assistant_chat_stream(req: ChatRequest, empid: str = Depends(get_current_user)):
    """Backs the floating JHS Assistant bubble (visible on every page) — unlike
    /chat/stream (dedicated to HR Policy, used by the module's HR tab), this
    classifies each message and routes it to whichever bot can answer it
    (HR / JHS Library / RCM / a general reply). See backend/chatbot/assistant.py.
    Same SSE event shape as /chat/stream, so the widget's streaming code
    doesn't need to know which path answered."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    context = _recent_context(empid, req.session_id)

    def event_stream():
        full_answer: List[str] = []
        answered_by = "hr"
        try:
            for event in assistant.dispatch_stream(req.message, context):
                if event.get("type") == "chunk":
                    full_answer.append(event["text"])
                elif event.get("type") == "done":
                    answered_by = event.get("bot") or "hr"
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            logger.exception("Unexpected failure in assistant stream for empid=%s", empid)
            yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong generating a reply. Please try again.'})}\n\n"
            return

        answer = "".join(full_answer)
        if answer:
            _persist_assistant_turn(empid, req.session_id, req.message, answer, answered_by)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────────────────────
# Admin — HR Policy knowledge-base management (Update / Replace)
# ─────────────────────────────────────────────────────────────────────────────
# Gated by the shared "chatbot" module admin check (backend/chatbot/admin_auth.py
# — same one RCM's admin endpoints use). Deliberately separate from
# chat history (history.py, cache.py) — these endpoints only ever touch the
# "hr-policy" Pinecone namespace, never a session/history collection.

@router.get("/admin/knowledge/stats")
def hr_knowledge_stats(empid: str = Depends(require_chatbot_admin)):
    stats = get_index().describe_index_stats()
    namespaces = stats.get("namespaces") or {}
    count = (namespaces.get(chatbot_settings.POLICY_NAMESPACE) or {}).get("vector_count", 0)
    return {"namespace": chatbot_settings.POLICY_NAMESPACE, "chunks": count}


# ─────────────────────────────────────────────────────────────────────────────
# Admin — cross-bot usage Dashboard (active users + API call usage per bot)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/dashboard")
def admin_dashboard(empid: str = Depends(require_chatbot_admin)):
    # Imported here (not at module load) — these are the OTHER two bots'
    # own history collections, reached via their module-level _col the same
    # way ad-hoc cleanup/diagnostic scripts already do in this codebase;
    # avoids a top-level cross-bot import cycle at router import time.
    from backend.library_chatbot import history as library_history
    from backend.rcm_chatbot import history as rcm_history

    bots = {
        "hr": history._col,
        "rcm": rcm_history._col,
        "library": library_history._col,
    }
    return {
        bot: {
            "active_users": admin_stats.active_user_count(col),
            "user_activity": admin_stats.user_activity(col),
            "api_usage": usage.get_usage(bot),
        }
        for bot, col in bots.items()
    }


@router.get("/admin/alerts")
def admin_alerts(empid: str = Depends(require_chatbot_admin)):
    """Retention-risk alerts — employees whose own chat messages (any bot,
    including ones dispatched through the floating assistant) matched the
    resignation/exit/dissatisfaction/harassment keyword taxonomy in
    alerts.py. Most recent first. `high_alert_users` are employees with a
    RED-severity match in more than 5 distinct chat sessions — surfaced
    separately so a genuinely repeated pattern doesn't get lost in the
    full list."""
    return {"alerts": alerts.list_alerts(), "high_alert_users": alerts.high_alert_users()}


@router.get("/admin/alerts/export.xlsx")
def admin_alerts_export(
    start: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    end: Optional[str] = Query(default=None, description="YYYY-MM-DD, inclusive"),
    empid: str = Depends(require_chatbot_admin),
):
    """Excel export of retention-risk alerts, optionally scoped to a date
    range (inclusive both ends) — the admin Dashboard's week/month presets
    and custom range both just resolve to start/end here."""
    import datetime as _dt

    start_ts = None
    end_ts = None
    try:
        if start:
            start_ts = _dt.datetime.combine(_dt.date.fromisoformat(start), _dt.time.min).timestamp()
        if end:
            end_ts = _dt.datetime.combine(_dt.date.fromisoformat(end), _dt.time.max).timestamp()
    except ValueError:
        raise HTTPException(status_code=400, detail="start/end must be YYYY-MM-DD")

    rows = alerts.list_alerts_in_range(start_ts, end_ts)
    content = alerts.generate_excel(rows)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=retention-risk-alerts.xlsx"},
    )


def _build_chunks_from_upload(file: UploadFile, content: bytes) -> list:
    try:
        # collapse_page_refs=False: keep the granular per-page section title
        # for retrieval grouping (rag.py's sibling-fetch) — the citation
        # shown to the employee still comes out page-free, stripped at
        # display time in rag.py instead. See multi_format.py's docstring.
        return multi_format.build_chunks_any_format(file.filename, content, collapse_page_refs=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read this file: {e}")


@router.post("/admin/knowledge/update")
async def hr_knowledge_update(empid: str = Depends(require_chatbot_admin), file: UploadFile = File(...)):
    """Adds a new document's content ALONGSIDE whatever's already in the
    "hr-policy" namespace — nothing existing is removed or overwritten.
    Accepts any of multi_format.SUPPORTED_EXTS (.docx, .pdf, .xlsx, .xls,
    .csv, .txt, .json)."""
    content = await file.read()
    chunks = _build_chunks_from_upload(file, content)
    added = ingest_policy.ingest_records(chunks, mode="update")
    upload_history.record_upload("hr", empid, "update", file.filename, added)
    return {"mode": "update", "file": file.filename, "chunks_added": added}


@router.post("/admin/knowledge/replace")
async def hr_knowledge_replace(empid: str = Depends(require_chatbot_admin), file: UploadFile = File(...)):
    """Clears the ENTIRE "hr-policy" namespace, then ingests only this
    document — full replace, matching the CLI ingest script's behavior.
    Accepts any of multi_format.SUPPORTED_EXTS."""
    content = await file.read()
    chunks = _build_chunks_from_upload(file, content)
    added = ingest_policy.ingest_records(chunks, mode="replace")
    upload_history.record_upload("hr", empid, "replace", file.filename, added)
    return {"mode": "replace", "file": file.filename, "chunks_added": added}


@router.get("/admin/knowledge/history")
def hr_knowledge_history(empid: str = Depends(require_chatbot_admin)):
    return upload_history.list_uploads("hr")


@router.get("/me", response_model=GreetingOut)
def me(empid: str = Depends(get_current_user)):
    """First name of the logged-in employee, for the chat widget's greeting."""
    emp = employee_details_collection.find_one({"EmpID": empid}, {"_id": 0, "Emp Name": 1})
    full_name = (emp or {}).get("Emp Name", "").strip()
    first_name = full_name.split()[0] if full_name else None
    return GreetingOut(name=first_name)


@router.get("/sessions", response_model=List[SessionSummary])
def get_sessions(empid: str = Depends(get_current_user)):
    """List this user's chat sessions, most recently active first."""
    return history.list_sessions(empid)


@router.get("/session/{session_id}/messages", response_model=List[MessageOut])
def get_session_messages(session_id: str, empid: str = Depends(get_current_user)):
    """Full transcript for one conversation (used to reload it when clicked in sidebar)."""
    return history.get_messages(empid, session_id)


@router.post("/session/{session_id}/reset")
def reset_session(session_id: str, empid: str = Depends(get_current_user)):
    """Clear all messages in a session (keep the session entry)."""
    history.delete_session(empid, session_id)
    return {"status": "cleared"}


@router.delete("/session/{session_id}")
def delete_session(session_id: str, empid: str = Depends(get_current_user)):
    """Permanently delete a session and all its messages."""
    history.delete_session(empid, session_id)
    return {"status": "deleted"}


@router.post("/new-session")
def new_session(empid: str = Depends(get_current_user)):
    """Generate a fresh session ID for the frontend to use."""
    return {"session_id": str(uuid.uuid4())}
