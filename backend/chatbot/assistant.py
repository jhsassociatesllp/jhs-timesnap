"""
General-purpose router for the floating JHS Assistant bubble.

The bubble (static/chatbot/chatbot-widget.js) is visible on every page and
isn't dedicated to one bot the way the JHS Chatbot module's tabs are. Each
incoming message gets a lightweight one-word classification, then gets
dispatched to whichever backend can actually answer it — HR Policy RAG,
the JHS Library audit-observation bot, the RCM checklist bot, or a plain
general reply for anything else (small talk, "what can you do", platform
questions). Every reply closes with a short nudge toward the full
/jhs-chatbot module for deeper digging, since the bubble is meant as a
quick-answer surface, not a replacement for it.

Kept as one generator (dispatch_stream) yielding the same SSE event shape
rag.answer_query_stream already uses ({"type": "chunk"/"done"/"error"}), so
chatbot-widget.js needs no protocol changes to use it.
"""
import logging
import re
from typing import Dict, Generator, List

from backend.chatbot import rag
from backend.chatbot.llm import call_llm, stream_llm

logger = logging.getLogger("chatbot.assistant")

CLASSIFY_PROMPT = (
    "Classify the employee's message into exactly one label. Reply with ONLY "
    "the label, nothing else.\n\n"
    "Labels:\n"
    "HR — questions about JHS company policy: leave, attendance, work from "
    "home, notice period, conduct, benefits, office rules, onboarding, etc.\n"
    "LIBRARY — questions about audit observations/findings: risks, root "
    "causes, recommendations, sectors, audit types, control weaknesses, "
    "drafting a finding, or anything about the JHS observation library.\n"
    "RCM — questions explicitly about Revenue Cycle Management / RCM.\n"
    "GENERAL — greetings, small talk, questions about the assistant itself, "
    "or anything not clearly HR/LIBRARY/RCM.\n\n"
    f"Message: "
)

GENERAL_SYSTEM_PROMPT = (
    "You are the JHS Assistant, a friendly guide for JHS employees using the internal "
    "JHS platform. You can help with quick HR policy questions and questions about the "
    "JHS audit observation library. For anything you can't answer directly, or when the "
    "employee wants to go deeper (browse full audit data, see past chats, ask about RCM), "
    "point them to the 'JHS Chatbot' module on their dashboard. Keep replies short, warm, "
    "and plain-spoken — a sentence or two unless more is genuinely needed. Never invent "
    "policy details or audit data you don't actually have."
)

def classify_message(message: str) -> str:
    try:
        label = call_llm(
            [{"role": "user", "content": CLASSIFY_PROMPT + message}],
            temperature=0,
        )
        label = re.sub(r"[^A-Z]", "", label.upper())
        if label in ("HR", "LIBRARY", "RCM", "GENERAL"):
            return label
        return "GENERAL"
    except Exception:
        logger.exception("Assistant classify_message failed — defaulting to GENERAL")
        return "GENERAL"


def _html_to_markdownish(html: str) -> str:
    """The Library bot answers in HTML (see library_chatbot/ai.py's
    HTML_FORMAT_RULES). The floating widget's renderer expects markdown-ish
    plain text (chat-core.js renderMarkdown escapes HTML first). Converts
    just the small set of tags that bot ever emits."""
    text = html
    text = re.sub(r"<h4>(.*?)</h4>", r"\n**\1**\n", text, flags=re.I | re.S)
    text = re.sub(r"<li>(.*?)</li>", r"- \1\n", text, flags=re.I | re.S)
    text = re.sub(r"</p>\s*<p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _library_answer(question: str):
    from backend.library_chatbot import audit_bot

    result = audit_bot.ask_bot(question, page=1, page_size=5)
    answer = _html_to_markdownish(result.get("answer", ""))
    # Deliberately no "Observations referenced" append — no reference/
    # citation text shown in the conversation, plain answer only.
    answer = answer or "I couldn't find anything on that in the observation library."
    return answer, result.get("follow_ups") or []


def _rcm_answer(question: str):
    from backend.rcm_chatbot import answer as rcm_answer

    reply, _sources, _from_cache, follow_ups = rcm_answer.answer_query(question, history=[])
    # Deliberately no "Sources" append — no reference/citation text shown
    # in the conversation, plain answer only.
    return reply, follow_ups


def dispatch_stream(message: str, history: List[Dict[str, str]]) -> Generator[Dict, None, None]:
    label = classify_message(message)

    if label == "HR":
        yield from rag.answer_query_stream(message, history)
        return

    if label == "LIBRARY":
        try:
            answer, follow_ups = _library_answer(message)
        except Exception:
            logger.exception("Assistant library dispatch failed")
            yield {"type": "error", "message": "Something went wrong searching the library. Please try again."}
            return
        yield {"type": "chunk", "text": answer}
        yield {"type": "done", "sources": ["JHS Library"], "from_cache": False, "follow_ups": follow_ups}
        return

    if label == "RCM":
        try:
            answer, follow_ups = _rcm_answer(message)
        except Exception:
            logger.exception("Assistant RCM dispatch failed")
            yield {"type": "error", "message": "Something went wrong searching the RCM knowledge base. Please try again."}
            return
        yield {"type": "chunk", "text": answer}
        yield {"type": "done", "sources": ["RCM Checklist Library"], "from_cache": False, "follow_ups": follow_ups}
        return

    # GENERAL
    messages = [{"role": "system", "content": GENERAL_SYSTEM_PROMPT}]
    messages.extend(history[-6:])
    messages.append({"role": "user", "content": message})
    try:
        full = []
        for token in stream_llm(messages):
            full.append(token)
            yield {"type": "chunk", "text": token}
        yield {"type": "done", "sources": [], "from_cache": False}
    except RuntimeError as e:
        yield {"type": "error", "message": str(e)}
