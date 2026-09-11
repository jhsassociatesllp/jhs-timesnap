"""Orchestration layer: composes data_access (Mongo), search (Pinecone/fuzzy
matching), ai (OpenAI) and cache (semantic FAQ cache) into the two
user-facing behaviors — chat and draft-a-finding.

Ported from the standalone JHS Library project, with one addition: ask_bot()
now checks/writes the semantic FAQ cache (cache.py) so a repeated or
near-duplicate question skips the OpenAI classify+answer round trip
entirely — same "don't waste tokens on repeat questions" behavior the HR
Policy bot already has (backend/chatbot/cache.py)."""
import logging

from backend.chatbot.followups import generate_follow_ups
from backend.library_chatbot import ai, cache, data_access, search

logger = logging.getLogger(__name__)


def _resolve_filters(guessed_filters: dict, facets: dict) -> dict:
    """Turns the LLM's rough filter guesses into canonical facet values via
    fuzzy matching against what's actually in the data — replaces the old
    brittle exact-case-insensitive-match approach."""
    resolved = {}
    for field, guess in (guessed_filters or {}).items():
        if not guess:
            continue
        match = search.fuzzy_match_facet(guess, facets.get(field, []))
        if match:
            resolved[field] = [match]
    return resolved


_ALL_FACET_FIELDS = [
    "sector", "audit_type", "risk", "process_area",
    "risk_theme", "coso_component", "fs_assertion", "fraud_risk_indicator",
]


def _looks_like_bare_keyword(question: str) -> bool:
    """A short, question-mark-free phrase ('banking', 'mystery') as opposed
    to an actual sentence/question ('What is the capital of France?') —
    the classifier is reliable on real questions but tends to guess
    OUT_OF_SCOPE for a bare topic word with no verb/context to judge, even
    when that word is a perfectly real audit type/sector/topic in the
    data. See _bare_keyword_lookup below."""
    q = question.strip()
    return bool(q) and "?" not in q and len(q.split()) <= 3


def _strict_facet_match(value: str, canonical_values: list):
    """Exact (case-insensitive) or clean substring match ONLY — deliberately
    skips fuzzy_match_facet's difflib closeness fallback, which is meant
    for the LLM classifier's own free-text guesses (already somewhat
    grounded) but is too loose for a raw single word: 'inventory' has a
    high enough difflib similarity to 'Investment' (a real but WRONG
    sector) to match at the normal cutoff, which would silently filter to
    the wrong facet and show misleading results. A word that isn't an
    actual substring of any real value here just isn't treated as a
    confident match — see _bare_keyword_lookup's fallback instead of
    guessing further."""
    if not value:
        return None
    value_l = value.strip().lower()
    lower_map = {c.lower(): c for c in canonical_values}
    if value_l in lower_map:
        return lower_map[value_l]
    for canon_l, canon in lower_map.items():
        if value_l in canon_l or canon_l in value_l:
            return canon
    return None


def _bare_keyword_lookup(question: str, facets: dict):
    """Called only when the classifier said OUT_OF_SCOPE for a bare-keyword-
    looking query (see above). Tries a STRICT match against the real facet
    vocabulary ('mystery' -> audit_type 'Mystery Audit') — deliberately
    never falls back to an unfiltered/broader search on a weak match,
    since that's exactly what silently diluted a specific audit-type
    question with unrelated rows before. Returns (field, value) on a
    confident hit, else None — the caller asks a clarifying question
    instead of guessing when this returns None."""
    for field in _ALL_FACET_FIELDS:
        match = _strict_facet_match(question, facets.get(field, []))
        if match:
            return field, match
    return None


def _clarifying_suggestions(question: str, facets: dict, limit: int = 4) -> list:
    """Loose (difflib-based) closest facet values across every field, for
    SUGGESTING what the employee might have meant — never used to filter
    results, only to phrase a helpful clarifying question when
    _bare_keyword_lookup found no confident match."""
    suggestions = []
    for field in _ALL_FACET_FIELDS:
        match = search.fuzzy_match_facet(question, facets.get(field, []), cutoff=0.5)
        if match and match not in suggestions:
            suggestions.append(match)
    return suggestions[:limit]


def ask_bot(question: str, page: int = 1, page_size: int = 20) -> dict:
    logger.info(f"Processing question: {question}")

    # Only the first page of a fresh question is cache-eligible — later pages
    # of the same browse session are cheap (no LLM generation beyond the
    # first answer) and paginate over live data, so they always hit Mongo.
    query_embedding = None
    if page == 1:
        query_embedding = search.embed(question)
        cached = cache.lookup(query_embedding)
        if cached is not None:
            return cached

    facets = data_access.get_facets()

    try:
        parsed = ai.classify_question(question, facets)
        intent = parsed["intent"]
        filters = _resolve_filters(parsed.get("filters"), facets)
        keywords = parsed.get("keywords", "")

        # "keywords" is exposed too (not just used internally) so the
        # frontend can offer a "View all in Browse" link that reopens this
        # exact scope (filters + free-text search) in the full paginated
        # Browse tab — this chat panel only ever shows a capped sample.
        response = {"intent": intent, "filters": filters, "keywords": keywords, "answer": "", "rows": [], "total": 0, "page": page, "follow_ups": []}

        if intent == "OUT_OF_SCOPE" and _looks_like_bare_keyword(question):
            # A bare word ('mystery', 'banking') with no verb/question
            # shape often trips the classifier into OUT_OF_SCOPE even when
            # it's a real audit type/sector/topic — try a STRICT facet
            # match before accepting that refusal. Deliberately never
            # widens to an unfiltered search on a weak/no match (that's
            # what previously diluted a specific audit-type question with
            # unrelated rows) — a confident match gets scoped real results,
            # anything less gets a clarifying question instead of a guess.
            hit = _bare_keyword_lookup(question, facets)
            if hit:
                field, value = hit
                filters = {field: [value]}
                rows, total = data_access.query_observations(filters, text_query="", page=page, page_size=page_size)
                response["intent"] = "SHOW_ALL"
                response["filters"] = filters
                response["total"] = total
                response["answer"] = ai.generate_summary(question, rows)
                response["rows"] = rows
            else:
                suggestions = _clarifying_suggestions(question, facets)
                suggestion_html = (
                    "<p>Closest matches in the data: " + ", ".join(f"<strong>{s}</strong>" for s in suggestions) + ".</p>"
                    if suggestions else ""
                )
                response["answer"] = (
                    f"<p>I couldn't find an exact match for \"{question}\" in the audit observation library "
                    "(sectors, audit types, risk themes, and similar). Could you tell me a bit more about what "
                    "you're looking for?</p>" + suggestion_html
                )

        # Only run the normal per-intent handling below if the bare-keyword
        # lookup above didn't already produce an answer — see its own
        # comment for why this needs to be a hard gate rather than relying
        # on the elif/else conditions alone.
        if not response["answer"]:
            if intent == "OUT_OF_SCOPE":
                # Fixed, deterministic refusal — no LLM call needed (and none of
                # the risk an LLM call carries of answering the off-topic
                # question anyway, or fabricating an audit-sounding "count" for
                # something that was never a real query against the data).
                response["answer"] = (
                    "<p>That's outside what I can help with here — I can only answer questions about "
                    "the audit observation library (findings, risks, root causes, recommendations, "
                    "sectors, audit types, and similar). Try rephrasing around one of those.</p>"
                )
            elif intent == "SUMMARY":
                pinecone_filters = {k: v[0] for k, v in filters.items() if k != "fraud_risk_indicator"}
                # top_k matches generate_summary's rows[:25] cap — no point retrieving
                # fewer candidates than the summary prompt is actually willing to use.
                matches = search.similar_by_text(keywords or question, filters=pinecone_filters, top_k=25)
                sr_nos = [m[0] for m in matches]
                rows = data_access.get_many_by_sr_no(sr_nos)
                response["answer"] = ai.generate_summary(question, rows)
                response["rows"] = rows
                response["total"] = len(rows)
            elif intent == "BREAKDOWN" and parsed.get("group_by") in _ALL_FACET_FIELDS:
                group_by = parsed["group_by"]
                breakdown = data_access.get_breakdown(group_by, filters)
                response["answer"] = ai.generate_breakdown_answer(question, group_by, breakdown, filters)
                response["total"] = sum(b["count"] for b in breakdown)
                response["rows"] = []
            else:
                rows, total = data_access.query_observations(filters, text_query=keywords, page=page, page_size=page_size)
                response["total"] = total
                response["answer"] = ai.generate_answer(question, intent, filters, total, [r["sr_no"] for r in rows])
                response["rows"] = [] if intent == "COUNT" else rows

        # Only for a fresh, in-scope, first-page answer — no point suggesting
        # follow-ups to a refusal, an error, or a pagination request.
        if page == 1 and intent != "OUT_OF_SCOPE" and response["answer"]:
            response["follow_ups"] = generate_follow_ups(question, response["answer"])

        if page == 1 and query_embedding is not None:
            cache.store(question, response, query_embedding)
        return response

    except Exception as e:
        logger.error(f"ask_bot failed: {e}")
        return {
            "intent": "ERROR", "filters": {},
            "answer": "<p>I encountered an error processing your question. Please try again.</p>",
            "rows": [], "total": 0, "page": page, "follow_ups": [],
        }


def draft_bot(sector: str, process_area: str, description: str) -> dict:
    logger.info(f"Drafting: sector={sector} process_area={process_area}")
    try:
        query_text = " ".join(p for p in (sector, process_area, description) if p)
        pinecone_filters = {"sector": sector} if sector else None
        matches = search.similar_by_text(query_text, filters=pinecone_filters, top_k=5)
        if not matches and pinecone_filters:
            # sector filter too narrow — fall back to unfiltered similarity
            matches = search.similar_by_text(query_text, top_k=5)
        sr_nos = [m[0] for m in matches]
        grounding_rows = data_access.get_many_by_sr_no(sr_nos)
        return ai.generate_draft(sector, process_area, description, grounding_rows)
    except Exception as e:
        logger.error(f"draft_bot failed: {e}")
        return {
            "headline": "", "observation": "", "root_cause": "",
            "recommendation": "", "management_action": "", "grounded_on": [],
            "error": "Draft generation failed, please try again.",
        }
