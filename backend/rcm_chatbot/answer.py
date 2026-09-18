"""
Answer orchestration for the RCM chatbot — the router-facing layer that ties
search.py's retrieval together with the shared platform LLM (backend/chatbot
/llm.py) and the exact-match Q&A cache (cache.py), and shapes results into
the same (answer, sources, from_cache) / SSE-event contract every other bot
on this platform uses (see backend/chatbot/rag.py for the HR bot's
equivalent).

Ported from the standalone Sentinel app's backend/main.py `/api/chat` route
handler + backend/search.py's call_openai — ONE deliberate difference beyond
the swap to the shared LLM: replies are plain markdown text here (not
pre-rendered HTML), since every bot on this platform streams markdown and
lets the frontend's shared renderer (chat-core.js renderMarkdown) turn it
into HTML client-side. The original bot's markdown_to_html step is skipped
for that reason — search.py still has it available (kept for fidelity /
in case something else wants pre-rendered HTML), but this module's output
already IS the markdown the original bot would have rendered.

Unlike the HR bot, this intentionally does NOT thread prior chat turns into
the LLM prompt — the original Sentinel app never did either (each question
is judged fresh against retrieved context, so the same question always gets
the same verdict, which matters for a compliance/audit tool). `history` is
still accepted in each function's signature for interface consistency with
the router / other bots, but isn't used in the prompt.
"""
import hashlib
import re
from typing import Any, Dict, Generator, List, Tuple

from backend.chatbot.followups import generate_follow_ups
from backend.chatbot.llm import call_llm
from backend.rcm_chatbot import cache
from backend.rcm_chatbot.config import rcm_settings
from backend.rcm_chatbot.search import (
    direct_field_answer,
    format_doc_for_context,
    pretty_name,
    row_pairs,
    search_documents,
)
from backend.rcm_chatbot.vectorstore import list_namespaces

# RCM's own LLM provider (see config.py's OPENAI_API_KEY) — None (falls
# back to the shared default inside call_llm/generate_follow_ups) until
# RCM_OPENAI_API_KEY is set in .env, then every RCM LLM call below uses
# it, same "own dedicated key" pattern as rag.py's HR_PROVIDER. The "bot"
# key is what backend/chatbot/llm.py's usage tracking attributes calls to.
RCM_PROVIDER = (
    {
        "base_url": rcm_settings.OPENAI_BASE_URL,
        "api_key": rcm_settings.OPENAI_API_KEY,
        "model": rcm_settings.OPENAI_MODEL,
        "name": "openai (rcm)",
        "bot": "rcm",
    }
    if rcm_settings.OPENAI_API_KEY
    else None
)

# Bump whenever SYSTEM_PROMPT changes — folded into the cache key so old
# cached replies (generated under a previous prompt) become guaranteed
# misses instead of being served forever unchanged.
PROMPT_VERSION = "1"

SYSTEM_PROMPT_TEMPLATE = """You are the RCM Assistant, an internal compliance knowledge-base assistant for a business team. You may ONLY use facts, figures, and procedures that literally appear in the excerpts in CONTEXT below — never use general/world knowledge, and never invent specific facts, controls, or procedures that are not present in the context.

STEP 0 — MANDATORY, do this before drafting any answer: Does the question name a specific labeled field of a checklist item — words like "Conclusion", "Objective", "Frequency", "Check points", "System Reports and Documents", "Procedure"/"Procedures" (→ the "Agreed Upon Procedures" field), or similar? If yes:
  1. Find that exact field in CONTEXT for the item being asked about.
  2. Your FIRST sentence must state that field's content, near-verbatim, in this exact form: "**<Field name>:** <its content from CONTEXT>". Nothing about the item's other fields (Objective, Data Receipt, Data Extraction, Data Validation, methodology, steps, etc.) may appear before this sentence.
  3. Only after that sentence may you add up to 1-2 short lines of extra context, if genuinely useful.
  4. Writing a walkthrough of the procedure/methodology INSTEAD of stating the named field is always wrong, even if it feels more thorough or helpful — it directly fails the user's actual question. Do not do this.
  5. If that field's content is itself just a cross-reference to another section not shown in CONTEXT (e.g. a Conclusion reading "Refer point no. 2 of Key Findings"): check whether the SAME item's own text in CONTEXT contains a numbered/enumerated "<Something> Review:" list with at least that many points — if so, state ONLY that Nth point's content as the answer (nothing about it being a cross-reference). If no such list is present for that item, state the pointer verbatim per rule 2 and stop there — do not add any explanatory sentence about what it means or that it's missing from CONTEXT. Never guess or invent what "Key Findings" itself says beyond what's literally enumerated in this item's own CONTEXT text.
If the question does NOT name a specific field (e.g. "what controls apply to Trade Verification", "summarize Trade Verification"), skip this step and answer normally per the rules below.

Next, judge relevance ROW BY ROW, never CONTEXT as a whole. CONTEXT below is pulled from many different checklists searched together, so for any broad question it will always contain a mix: some excerpts genuinely on-topic, most not. That mix, by itself, is never a reason to refuse — judge each excerpt on its own merit against the question, then answer from whichever ones actually qualify. This applies especially to a broad "what criteria/controls should I check for X" style question: its real answer is often scattered across many separate rows, sometimes from more than one checklist, not concentrated in one place.

- Go through CONTEXT and pick out every excerpt that genuinely bears on the question (same real-world subject as at least part of what was asked, not just a coincidental shared word).
- If at least one excerpt qualifies: answer using ONLY those, organized as concise points - one per relevant control/fact, briefly stating what it means. Do NOT cite [Collection › File › Sheet] inline in the body of your answer - that reference information is tracked separately and must never appear inline mid-sentence or mid-point. Ignore every excerpt that didn't qualify; do not mention them.
- A checklist-style question inherently invites a checklist-style answer: use bullet or numbered points (## headers only if multiple distinct sub-topics), one per matched control, over one long paragraph. This applies even when a control's own procedure is itself a dense multi-step block in CONTEXT — break THAT into its own short bullets too (one per verification step/data source), never paste it back as one unbroken paragraph. If you find yourself writing a paragraph longer than 2-3 sentences, stop and reformat it as bullets before answering.
- You may spell out a well-known business/compliance acronym used in the CONTEXT itself even if that exact expansion isn't written out, as long as you are not inventing any other unstated facts.
- If the question clearly has OTHER facets a domain expert would expect but CONTEXT's matched rows don't cover them, do not invent those missing facets from general knowledge - after answering the covered part, add one line naming what's clearly missing and stating it isn't covered in the uploaded knowledge base.
- Bold key terms with **term**. Keep answers focused and business-appropriate.
- Always end with a line starting "Sources:" listing the distinct [Collection › File › Sheet] references you actually used.

Only refuse - "this question is outside the scope of the uploaded knowledge base" - when NOT ONE excerpt in CONTEXT genuinely relates to any part of the question. In that case, say so in 1-2 sentences, optionally suggest the closest related collection from: {coll_list}, and end with exactly: "Sources: None"

CONTEXT:
{context_text}"""


def is_configured() -> bool:
    from backend.chatbot.config import chatbot_settings
    llm_ready = bool(rcm_settings.OPENAI_API_KEY) or bool(chatbot_settings.ACTIVE_API_KEY)
    return llm_ready and bool(rcm_settings.PINECONE_API_KEY)


# A PDF-sourced row's "sheet" is a bare "PageN" / "PageN_TableM" internal
# chunk-grouping label (see backend/rcm_chatbot/parsers.py's parse_pdf) —
# useful for retrieval, not something a user asking a checklist question
# should see quoted back as a "source". A real sheet name (an actual Excel
# tab, a docx table) is still shown — this only hides the page-number kind.
_PAGE_REF_RE = re.compile(r"^Page\d+(?:_Table\d+)?$", re.IGNORECASE)


def _sources_for(docs: List[Dict[str, Any]]) -> List[str]:
    seen = set()
    sources = []
    for d in docs[:6]:
        collection_label = pretty_name(d.get("collection", ""))
        sheet = d.get("sheet")
        key = collection_label if not sheet or _PAGE_REF_RE.match(str(sheet)) else f"{collection_label} › {sheet}"
        if key not in seen:
            seen.add(key)
            sources.append(key)
    return sources


def _no_docs_message(collection: str) -> str:
    collections = list_namespaces()
    names = ", ".join(pretty_name(c) for c in collections) if collections else "none yet — ask your admin to add data"
    scope_note = f" within **{pretty_name(collection)}**" if collection and collection != "All" else ""
    return (
        f"I couldn't find matching items in the database for that query{scope_note}. "
        f"Try rephrasing — collections available: {names}."
    )


def _fallback_text(docs: List[Dict[str, Any]]) -> str:
    """Raw top-match dump used when the LLM is unreachable/unconfigured —
    still useful, just not synthesized."""
    parts = []
    for d in docs[:5]:
        pairs = row_pairs(d.get("header", []), d.get("row", []))
        lines = "\n".join(f"**{h}:** {v[:5000]}" for h, v in pairs)
        parts.append(f"_{pretty_name(d.get('collection', ''))} › {d.get('sheet')}_\n{lines}")
    return "\n\n---\n\n".join(parts) if parts else "No matches found."


def strip_sources_line(reply: str) -> str:
    lines = reply.rstrip().split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^\s*sources\s*:", line, re.IGNORECASE):
            return "\n".join(lines[:i]).rstrip()
    return reply.rstrip()


def _build_messages(query: str, context_docs: List[Dict[str, Any]], collection_names: List[str]):
    context_text = "\n\n---\n\n".join(format_doc_for_context(d) for d in context_docs)
    coll_list = ", ".join(collection_names) if collection_names else "none"
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(coll_list=coll_list, context_text=context_text)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]


def _context_hash(context_docs: List[Dict[str, Any]]) -> str:
    context_text = "\n\n---\n\n".join(format_doc_for_context(d) for d in context_docs)
    return hashlib.sha256(context_text.encode("utf-8")).hexdigest()


def answer_query(
    question: str, history: List[Dict[str, str]], collection: str = "All"
) -> Tuple[str, List[str], bool, List[str]]:
    """Returns (answer_markdown, sources, was_served_from_cache, follow_up_questions)."""
    docs = search_documents(question, collection)
    sources = _sources_for(docs)

    field_hit = direct_field_answer(question, docs)
    if field_hit:
        text = field_hit["text"]
        return text, sources, False, generate_follow_ups(question, text, provider=RCM_PROVIDER)

    if not docs:
        return _no_docs_message(collection), [], False, []

    if not is_configured():
        text = _fallback_text(docs)
        return text, sources, False, generate_follow_ups(question, text, provider=RCM_PROVIDER)

    cache_key = cache.make_key(PROMPT_VERSION, question, _context_hash(docs))
    cached = cache.get(cache_key)
    if cached is not None:
        return cached, sources, True, generate_follow_ups(question, cached, provider=RCM_PROVIDER)

    try:
        collection_names = [pretty_name(c) for c in list_namespaces()]
        messages = _build_messages(question, docs, collection_names)
        reply = strip_sources_line(call_llm(messages, temperature=0.1, provider=RCM_PROVIDER))
        cache.set(cache_key, question, reply)
        return reply, sources, False, generate_follow_ups(question, reply, provider=RCM_PROVIDER)
    except Exception:
        text = _fallback_text(docs)
        return text, sources, False, generate_follow_ups(question, text, provider=RCM_PROVIDER)


def answer_query_stream(
    question: str, history: List[Dict[str, str]], collection: str = "All"
) -> Generator[Dict, None, None]:
    """Streaming counterpart to answer_query(). Yields dict events:
      {"type": "chunk", "text": "..."}
      {"type": "done", "sources": [...], "from_cache": bool, "follow_ups": [...]}
      {"type": "error", "message": "..."}

    A direct-field hit, a cache hit, and the no-docs/not-configured fallback
    paths are all already-instant text, so each is yielded as a single chunk
    (same convention the HR bot uses for its own cache hits) rather than
    faking a token-by-token stream.
    """
    docs = search_documents(question, collection)
    sources = _sources_for(docs)

    field_hit = direct_field_answer(question, docs)
    if field_hit:
        text = field_hit["text"]
        yield {"type": "chunk", "text": text}
        yield {"type": "done", "sources": sources, "from_cache": False, "follow_ups": generate_follow_ups(question, text, provider=RCM_PROVIDER)}
        return

    if not docs:
        yield {"type": "chunk", "text": _no_docs_message(collection)}
        yield {"type": "done", "sources": [], "from_cache": False, "follow_ups": []}
        return

    if not is_configured():
        text = _fallback_text(docs)
        yield {"type": "chunk", "text": text}
        yield {"type": "done", "sources": sources, "from_cache": False, "follow_ups": generate_follow_ups(question, text, provider=RCM_PROVIDER)}
        return

    cache_key = cache.make_key(PROMPT_VERSION, question, _context_hash(docs))
    cached = cache.get(cache_key)
    if cached is not None:
        yield {"type": "chunk", "text": cached}
        yield {"type": "done", "sources": sources, "from_cache": True, "follow_ups": generate_follow_ups(question, cached, provider=RCM_PROVIDER)}
        return

    try:
        # Deliberately NOT streamed token-by-token here (unlike the HR bot):
        # the system prompt asks the model to end every reply with a
        # "Sources:" line that must never reach the user (sources are shown
        # via the `sources` chips computed above instead) - stripping that
        # line requires seeing the full reply first, so streaming raw tokens
        # would leak it on screen for a moment before the strip could apply.
        # The original standalone app was synchronous for the same reason.
        collection_names = [pretty_name(c) for c in list_namespaces()]
        messages = _build_messages(question, docs, collection_names)
        reply = strip_sources_line(call_llm(messages, temperature=0.1, provider=RCM_PROVIDER))
        cache.set(cache_key, question, reply)
        yield {"type": "chunk", "text": reply}
        yield {"type": "done", "sources": sources, "from_cache": False, "follow_ups": generate_follow_ups(question, reply, provider=RCM_PROVIDER)}
    except RuntimeError as e:
        yield {"type": "error", "message": str(e)}
    except Exception:
        text = _fallback_text(docs)
        yield {"type": "chunk", "text": text}
        yield {"type": "done", "sources": sources, "from_cache": False, "follow_ups": generate_follow_ups(question, text, provider=RCM_PROVIDER)}
