"""
HR bot — post-generation grounding validation. A cheap, separate LLM call
that checks the just-generated answer against the retrieved policy context
BEFORE it reaches the employee, catching exactly the failure modes prompt
instructions alone can't guarantee: an invented fact, an altered number, a
blended-together designation rule, or an answer that should have said "not
found" instead of guessing.

Used by rag.py's answer generation with AT MOST ONE retry on failure
(regenerate with a stricter reminder) — never a regeneration loop. If the
retry still fails, rag.py degrades to a plain "not found in the HR policy"
response rather than showing an answer flagged as possibly ungrounded.
"""
import json
import logging
import re
from typing import Dict, Optional

from backend.chatbot.llm import ProviderOverride, call_llm

logger = logging.getLogger("chatbot.hr.grounding")

_SYSTEM_PROMPT = (
    "You are a strict fact-checker for an HR policy chatbot's answer. Given the retrieved HR "
    "policy notes and the bot's answer, verify the answer ONLY contains claims actually "
    "supported by those notes.\n\n"
    "Check specifically:\n"
    "1. Every factual claim (a number, date, percentage, eligibility rule, designation-specific "
    "rate) is present in the notes — not invented, not from general HR knowledge.\n"
    "2. Numbers/dates/percentages in the answer EXACTLY match what's in the notes (not rounded, "
    "not substituted, not pulled from a different row/designation than the one asked about).\n"
    "3. If the notes have designation-specific rules, the answer doesn't blend/mix rules from "
    "different designations into one statement.\n"
    "4. If the notes don't actually answer the question, the answer correctly says the "
    "information isn't available, rather than guessing.\n\n"
    "Distinguish two very different kinds of problem:\n"
    "- hallucinated: the answer states a SPECIFIC fact (a number, date, rule) with no real basis "
    "in the notes at all — confidently wrong. This is the serious failure.\n"
    "- merely_uncertain: the answer is otherwise accurate but touches on something the notes "
    "state ambiguously (e.g. a table cell using a dash/placeholder whose exact meaning isn't "
    "100% certain) — NOT a fabrication, just a genuinely unclear source. An answer that "
    "correctly and separately hedges on the unclear part while stating the clear part plainly "
    "is GOOD behavior, not a grounding failure — the policy itself explicitly wants partial "
    "answers that flag what's uncertain instead of an all-or-nothing refusal.\n\n"
    'Return ONLY JSON: {"grounded": true|false, "hallucinated": true|false, '
    '"issues": ["short specific issue", ...]}\n'
    "grounded=true if there are no issues at all. hallucinated=true ONLY for the serious kind "
    "above — never true just because something is merely uncertain/hedged appropriately. Be "
    "strict but fair — do not flag reasonable phrasing/tone choices, only actual factual/"
    "grounding problems."
)


def check_grounding(question: str, context_text: str, answer: str, provider: Optional[ProviderOverride] = None) -> Dict:
    """Returns {"grounded": bool, "hallucinated": bool, "issues": [...]}.

    "grounded" and "hallucinated" are deliberately separate: an answer can
    be flagged grounded=False (the checker found SOME issue worth a closer
    look) while hallucinated=False (that issue was a genuinely ambiguous
    source, not an invented fact) — callers should treat that combination
    as a partially-supported answer worth keeping (it likely already
    hedges appropriately), reserving the "I don't have that information"
    fallback for hallucinated=True, where the model stated something with
    no real basis at all. See rag.py's _generate_grounded_answer.

    On any failure to run the check itself (timeout, bad JSON, provider
    hiccup), degrades to grounded=True — a validator hiccup should never
    block a genuinely fine answer from reaching the employee; this is a
    safety net, not a hard gate that can take the whole bot down."""
    try:
        raw = call_llm(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"NOTES:\n{context_text[:6000]}\n\nQUESTION: {question}\n\nANSWER: {answer}",
                },
            ],
            temperature=0,
            provider=provider,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(json)?", "", raw).rstrip("`").strip()
        data = json.loads(raw)
        return {
            "grounded": bool(data.get("grounded", True)),
            "hallucinated": bool(data.get("hallucinated")),
            "issues": list(data.get("issues") or []),
        }
    except Exception:
        logger.exception("Grounding check failed to run — defaulting to grounded=True")
        return {"grounded": True, "hallucinated": False, "issues": []}
