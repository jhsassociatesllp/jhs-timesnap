"""
Generates up to 4 short, relevant follow-up questions from a completed Q&A
turn — shown as clickable suggestion chips so a user can continue the
conversation without typing. Shared by all three bots (HR / RCM / Library).

Deliberately a separate, small/cheap LLM call (not folded into the main
answer prompt) so a follow-up-generation hiccup never affects the main
answer's own quality, and — for the streaming endpoints — never delays the
visible answer itself (it runs AFTER the answer has already fully streamed
to the user, right before the closing "done" event).

Uses the HR bot's OpenAI provider (backend.chatbot.rag.HR_PROVIDER) by
default regardless of which bot is asking — it's the platform's most
reliable provider for structured JSON output, and follow-up generation
itself isn't bot-specific enough to need its own credentials.
"""
import json
import logging
import re
from typing import List, Optional

from backend.chatbot.llm import ProviderOverride, call_llm

logger = logging.getLogger("chatbot.followups")

_SYSTEM_PROMPT = (
    "Given a question and its answer from an internal company chatbot, suggest up to 4 short, "
    "natural follow-up questions a user might genuinely want to ask next — each under 12 words, "
    "specific (not generic like 'tell me more'), and clearly answerable by the SAME knowledge "
    "base this bot draws from (don't suggest something needing outside/general knowledge). If "
    "the answer was a refusal or 'I don't have details on this', suggest questions on nearby "
    "topics instead — never a follow-up to information that was just said to be missing.\n\n"
    'Return ONLY a JSON array of strings, e.g. ["...", "...", "..."]. 0-4 items — fewer is fine '
    "if you can't think of genuinely useful ones; never pad with weak filler."
)


def generate_follow_ups(question: str, answer: str, provider: Optional[ProviderOverride] = None) -> List[str]:
    if not answer or not answer.strip():
        return []
    try:
        if provider is None:
            from backend.chatbot.rag import HR_PROVIDER
            provider = HR_PROVIDER
        raw = call_llm(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Question: {question}\n\nAnswer: {answer[:3000]}"},
            ],
            temperature=0.4,
            provider=provider,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(json)?", "", raw).rstrip("`").strip()
        items = json.loads(raw)
        return [str(q).strip() for q in items if str(q).strip()][:4]
    except Exception:
        logger.exception("Follow-up generation failed — degrading to none")
        return []
