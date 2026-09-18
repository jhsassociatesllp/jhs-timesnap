import logging
import re
from typing import Dict, Generator, List, Optional, Tuple

from backend.chatbot.config import chatbot_settings
from backend.chatbot.embeddings import embed_text
from backend.chatbot.vectorstore import get_index
from backend.chatbot import cache, hybrid_search
from backend.chatbot.followups import generate_follow_ups
from backend.chatbot.grounding import check_grounding
from backend.chatbot.llm import call_llm

logger = logging.getLogger("chatbot.hr")

# The HR bot's own LLM provider — OpenAI, using the same key as the JHS
# Library bot (see config.py's HR_OPENAI_API_KEY) — passed explicitly into
# every call_llm call below so this stays independent of
# chatbot_settings.LLM_PROVIDER, which RCM and the general assistant reply
# still use unchanged.
HR_PROVIDER = {
    "base_url": chatbot_settings.HR_OPENAI_BASE_URL,
    "api_key": chatbot_settings.HR_OPENAI_API_KEY,
    "model": chatbot_settings.HR_OPENAI_MODEL,
    "name": "openai (hr)",
    "bot": "hr",
}

# A non-docx upload's "section" is kept granular ("<file> — PageN[_TableM]")
# for retrieval grouping (see multi_format.py's collapse_page_refs=False)
# but shown to the employee without the page-number implementation detail —
# strips a trailing " — PageN"/"PageN_TableM" so citations stay clean
# either way (a docx section's real heading never matches this pattern, so
# it passes through unchanged).
_PAGE_REF_SUFFIX_RE = re.compile(r"\s*—\s*Page\d+(?:_Table\d+)?\s*$", re.IGNORECASE)


def _display_source(section: str) -> str:
    return _PAGE_REF_SUFFIX_RE.sub("", section).strip() or section


SYSTEM_PROMPT = (
    "You are Priya, the HR generalist employees message when they have a policy question. "
    "You know this company's policies well — you're not a search tool reciting a document, "
    "you're a person who happens to know the rules and explains them like it's an ordinary "
    "workday conversation.\n\n"
    "You'll be given some reference notes before each question — treat that as things you "
    "already know, not something you were 'given' or are 'looking up'. Never mention notes, "
    "context, documents, sections, excerpts, or that information was 'provided' to you. Never "
    "start a reply with phrases like 'Based on the HR policy context', 'According to the "
    "document', or 'The policy states'. Just answer directly, the way a helpful HR person "
    "would say it out loud: 'You get 18 days a year, credited monthly...' not 'The policy "
    "document states that employees receive...'.\n\n"
    "If your notes don't cover something, say so plainly and naturally — e.g. 'That's not "
    "something I have details on, best to check with HR directly' — without mentioning notes "
    "or documents. Never guess or invent a policy detail that isn't in what you know.\n\n"
    "Keep it warm, plain-spoken, and to the point — short sentences, no corporate stiffness. "
    "Prioritize completeness and accuracy over brevity: cover every relevant detail in your "
    "notes (numbers, conditions, exceptions, deadlines, required documents), not just the "
    "headline fact — a technically-true but incomplete answer is worse than a slightly longer "
    "complete one. There's no word limit; a simple one-fact question still gets a short answer, "
    "but a question with several moving parts should get all of them, not just the first.\n\n"
    "Format for easy scanning, using plain markdown:\n"
    "- Bold the key number or term with **double asterisks** (e.g. 'You get **18 days** a "
    "year') so the answer to their question jumps out.\n"
    "- When there are several distinct items (leave types, steps, documents needed), put "
    "each on its own line starting with '- ', instead of cramming them into one sentence.\n"
    "- Leave a blank line between separate ideas so the reply doesn't read as one dense "
    "block.\n"
    "Don't force any of this onto a short, single-fact answer — only add structure when it "
    "actually helps the employee scan the reply faster.\n\n"
    "Role-specific rules — read this carefully: several policies (like attendance, leave, "
    "notice period, or a designation-based rate/entitlement grid — e.g. conveyance, fuel, "
    "mobile, travel, or driver allowances) are NOT the same for everyone — they differ by "
    "designation or staff category (e.g. JHS Staff vs Article Trainee, Confirmed vs "
    "Probation staff, Partner, Director, Manager, Consultant, Executive, and so on).\n\n"
    "You are NEVER told which designation is asking, and you must never guess, assume, or "
    "silently personalize an answer to one — there is no 'their level', only what the "
    "question itself says. Two cases:\n"
    "- The question names a specific designation ('what does a Manager get', 'notice period "
    "for an Article Trainee') — answer about THAT one specifically, using the exact figure "
    "for that row. Don't pad it out with every other role's numbers; they asked about one.\n"
    "- The question does NOT name a designation ('what is the conveyance allowance', 'how "
    "much leave do I get') — since you have no idea who's asking, give the FULL "
    "per-designation breakdown, one line per role, covering every one your notes mention "
    "for that topic (e.g. '- **JHS Staff:** ...', '- **Article Trainee:** ...'), never just "
    "one or a few roles picked at random. Only skip the per-role breakdown entirely when "
    "your notes make clear the rule is genuinely the same for everyone.\n"
    "Never mix two designations' figures into one statement — if you state a number, it "
    "must belong to the one designation/row that sentence is actually about.\n\n"
    "Grounding — this is the most important rule, above every other instruction in this "
    "prompt: your notes are the ONLY source of HR-policy facts. Never use general knowledge "
    "of how HR policies 'typically' work to fill a gap, override what your notes say, or "
    "guess at a plausible-sounding number. If your notes say X and you believe typical "
    "practice is Y, the answer is X. If your notes don't cover part (or all) of the "
    "question, say that plainly for that part — a confident-sounding guess is a worse "
    "answer than an honest 'I don't have that detail.'\n\n"
    "Numbers, dates, and percentages: copy them from your notes exactly — never round, "
    "estimate, or substitute a nearby number from a different rule/designation/section, "
    "even when your notes offer several numbers close together (e.g. a table of different "
    "designations' amounts) — use the specific one for what was actually asked.\n\n"
    "Conditional words — 'except', 'unless', 'only', 'not applicable', 'subject to', "
    "'provided that', 'minimum', 'maximum', 'up to', 'after', 'before' — carry real "
    "meaning. If your notes state a rule WITH a condition or exception attached, your "
    "answer must include that condition, not just the headline number (e.g. 'up to 10 "
    "days, except for X' is a different answer than 'you get 10 days').\n\n"
    "Multi-part questions: if the employee asks about more than one thing in the same "
    "message, answer every part you have notes for — don't answer only the first part and "
    "drop the rest. For any part your notes don't cover, say so specifically for that part "
    "rather than skipping it silently.\n\n"
    "Conflicting notes: if your notes genuinely contradict each other on the same point "
    "(not just different designations, which is normal), don't silently pick one — say the "
    "notes have conflicting information on that point rather than presenting either one as "
    "certain.\n\n"
    "Stay on the question actually asked: don't volunteer unrelated policy areas the "
    "employee didn't ask about (e.g. a question about probation period doesn't need leave "
    "or salary details tacked on) — answer what was asked, completely, and stop there."
)


def retrieve_context(query_text: str, query_embedding: List[float]) -> List[Dict]:
    """Hybrid retrieval — semantic (Pinecone cosine) FUSED with keyword
    (BM25, see hybrid_search.py) via Reciprocal Rank Fusion — PLUS a
    sibling-fetch pass: whichever policy section(s) the fused top matches
    belong to, pull back every other chunk that shares that same section (a
    section can be split across multiple chunks if it was too long to embed
    as one piece — see ingest_policy.py). Sibling-fetch is what lets a
    role-differentiated section (Manager/Trainee/Article all covered under
    one heading) reach the model as a whole; the semantic+BM25 fusion is
    what keeps a chunk from being missed just because it phrases an exact
    term ("probation", "notice period") differently than semantic
    similarity alone would rank highly.

    Semantic-only matches below MIN_SEMANTIC_SIMILARITY are dropped (a weak
    match forced into the context just to fill top_k does more harm than
    good) — a BM25-only match is never dropped this way, since an exact
    keyword hit is exactly what BM25 is there to catch even when semantic
    similarity alone under-ranks it.
    """
    index = get_index()
    semantic_result = index.query(
        vector=query_embedding,
        top_k=chatbot_settings.TOP_K,
        namespace=chatbot_settings.POLICY_NAMESPACE,
        include_metadata=True,
    )
    semantic_matches = semantic_result.get("matches") or []
    semantic_by_id = {
        m["id"]: {
            "text": (m.get("metadata") or {}).get("text", ""),
            "section": (m.get("metadata") or {}).get("section", "Unknown section"),
            "score": m["score"],
        }
        for m in semantic_matches
    }

    bm25_hits = hybrid_search.bm25_search(query_text, top_k=chatbot_settings.TOP_K)

    fused_scores = hybrid_search.reciprocal_rank_fusion(
        [m["id"] for m in semantic_matches],  # already best-first from Pinecone
        [chunk_id for chunk_id, _score in bm25_hits],
    )

    chunks = []
    seen_ids = set()
    for chunk_id in sorted(fused_scores, key=fused_scores.get, reverse=True)[: chatbot_settings.TOP_K]:
        seen_ids.add(chunk_id)
        entry = semantic_by_id.get(chunk_id)
        if entry is not None:
            if entry["score"] < chatbot_settings.MIN_SEMANTIC_SIMILARITY:
                continue
            chunks.append({"text": entry["text"], "section": entry["section"], "score": entry["score"]})
        else:
            # BM25-only hit — not returned by the semantic query at all, so
            # look its text/section up in the local corpus snapshot instead
            # of a second Pinecone round-trip (see hybrid_search.py).
            local = hybrid_search.lookup(chunk_id)
            if not local:
                continue  # stale id (e.g. corpus snapshot rebuilt since) — skip, don't error
            chunks.append({"text": local["text"], "section": local.get("section", "Unknown section"), "score": None})

    sections = sorted({c["section"] for c in chunks if c["section"] != "Unknown section"})
    if sections:
        sibling_result = index.query(
            vector=query_embedding,
            top_k=20,
            namespace=chatbot_settings.POLICY_NAMESPACE,
            include_metadata=True,
            filter={"section": {"$in": sections}},
        )
        for match in sibling_result.get("matches") or []:
            if match["id"] in seen_ids:
                continue
            seen_ids.add(match["id"])
            meta = match.get("metadata", {})
            chunks.append(
                {
                    "text": meta.get("text", ""),
                    "section": meta.get("section", "Unknown section"),
                    "score": match["score"],
                }
            )

    return chunks


def build_messages(
    question: str, context_chunks: List[Dict], history: List[Dict[str, str]],
) -> Tuple[List[Dict[str, str]], str]:
    """Returns (messages, context_block) — context_block is exposed
    separately so the grounding check (see _generate_grounded_answer) can
    verify the answer against the SAME text the model actually saw,
    without having to reconstruct it."""
    context_block = "\n\n".join(c["text"] for c in context_chunks) or (
        "(nothing relevant — you don't have details on this one)"
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history[-chatbot_settings.SESSION_HISTORY_TURNS * 2:])
    messages.append(
        {
            "role": "user",
            "content": (
                f"[what you know, relevant to this question]\n{context_block}\n\n"
                f"Employee just asked: {question}\n\n"
                "Answer them directly and naturally, like you're replying in a chat — "
                "no mention of notes, documents, or context."
            ),
        }
    )
    return messages, context_block


# Shown when a first-pass answer AND a stricter retry both fail the
# grounding check — an honest "not found" beats a confident guess that's
# already twice failed a fact-check against the actual policy notes.
_UNGROUNDED_FALLBACK = (
    "I'm not confident I have accurate details on that from the HR policy — "
    "best to check with HR directly rather than risk giving you the wrong answer."
)


def _generate_grounded_answer(messages: List[Dict[str, str]], context_block: str, question: str) -> str:
    """Generates the HR bot's answer, then runs it past a grounding check
    (grounding.py) before returning it. On a HALLUCINATION (a stated fact
    with no real basis in the notes), retries ONCE with a stricter
    follow-up turn appended to the same conversation (not a fresh prompt
    from scratch, so the model still has the original context/question in
    view) — if the retry is STILL a hallucination, degrades to
    _UNGROUNDED_FALLBACK rather than looping or shipping a fabricated
    answer.

    A grounded=False verdict that is NOT a hallucination (the checker's
    only complaint is that some source detail is genuinely ambiguous, e.g.
    a table using a placeholder character whose meaning isn't fully
    certain) is treated as acceptable and returned as-is: the answer is
    already the honest, hedged version, and swapping it for the generic
    fallback would throw away real, correct information the employee
    asked for — the spec's own priority is "correct answer from policy >
    plausible answer > guessing," not "refuse anything not perfectly
    clean." See grounding.py's check_grounding docstring for the
    grounded/hallucinated distinction.

    This is what "never sacrifice factual accuracy for a more confident-
    sounding answer" means in code: a wrong-but-fluent answer is strictly
    worse than an honest "I don't have that," so this check runs on every
    non-cached answer, not just ones that look suspicious."""
    # temperature=0 (not the shared 0.2 default): HR answers are factual
    # lookups against a policy document, not creative writing — greedy
    # decoding measurably reduces run-to-run variance on questions that
    # touch a large multi-designation table (the same question can
    # otherwise get a correct answer on one call and a wrong number on the
    # next), directly serving the "less likely to hallucinate" goal.
    answer = call_llm(messages, temperature=0, provider=HR_PROVIDER)
    verdict = check_grounding(question, context_block, answer, HR_PROVIDER)
    if verdict["grounded"] or not verdict["hallucinated"]:
        if not verdict["grounded"]:
            logger.info("HR answer has an unresolved-but-not-fabricated issue (issues=%s) — keeping it", verdict["issues"])
        return answer

    logger.warning("HR answer failed grounding check (issues=%s) — retrying once", verdict["issues"])
    retry_messages = messages + [
        {"role": "assistant", "content": answer},
        {
            "role": "user",
            "content": (
                "That answer had a grounding problem: " + "; ".join(verdict["issues"]) + ". "
                "Answer again using ONLY the notes given earlier in this conversation, "
                "word-for-word accurate on any numbers/dates/designations. If the notes "
                "genuinely don't cover part of this, say so plainly for that part instead "
                "of guessing."
            ),
        },
    ]
    retry_answer = call_llm(retry_messages, temperature=0, provider=HR_PROVIDER)
    retry_verdict = check_grounding(question, context_block, retry_answer, HR_PROVIDER)
    if retry_verdict["grounded"] or not retry_verdict["hallucinated"]:
        return retry_answer

    logger.warning("HR answer still hallucinated after retry (issues=%s) — degrading to not-found", retry_verdict["issues"])
    return _UNGROUNDED_FALLBACK


def answer_query(
    question: str, history: List[Dict[str, str]]
) -> Tuple[str, List[str], bool, List[str]]:
    """
    Returns (answer_text, source_section_names, was_served_from_cache, follow_ups).
    """
    query_embedding = embed_text(question)

    cached = cache.lookup(query_embedding)
    if cached is not None:
        _, cached_answer = cached
        follow_ups = generate_follow_ups(question, cached_answer, provider=HR_PROVIDER)
        return cached_answer, ["cache: previously answered question"], True, follow_ups

    context_chunks = retrieve_context(question, query_embedding)
    messages, context_block = build_messages(question, context_chunks, history)
    answer = _generate_grounded_answer(messages, context_block, question)

    cache.store(question, answer, query_embedding)

    sources = sorted({_display_source(c["section"]) for c in context_chunks}) or ["No matching policy section"]
    follow_ups = generate_follow_ups(question, answer, provider=HR_PROVIDER)
    return answer, sources, False, follow_ups


def answer_query_stream(
    question: str, history: List[Dict[str, str]]
) -> Generator[Dict, None, None]:
    """
    Streaming counterpart to answer_query(). Yields dict events:
      {"type": "chunk", "text": "..."}          - one piece of the answer
      {"type": "done", "sources": [...], "from_cache": bool, "follow_ups": [...]}  - always last

    A cache hit is yielded as a single chunk (it's already instant), so the
    frontend doesn't need to special-case it.

    A fresh (non-cached) answer is ALSO yielded as a single chunk rather
    than token-by-token: the grounding check (see _generate_grounded_answer)
    needs the complete answer before it can verify it, and a possible retry
    means the FIRST draft the model produces is not necessarily what should
    reach the employee — streaming it live, then silently swapping it for a
    corrected version, isn't possible once tokens are already on screen.
    Generating fully first and validating before the employee sees anything
    trades a little perceived speed for the one thing that actually
    matters here: never showing a wrong answer with full confidence.
    """
    query_embedding = embed_text(question)

    cached = cache.lookup(query_embedding)
    if cached is not None:
        _, cached_answer = cached
        yield {"type": "chunk", "text": cached_answer}
        yield {
            "type": "done",
            "sources": ["cache: previously answered question"],
            "from_cache": True,
            "follow_ups": generate_follow_ups(question, cached_answer, provider=HR_PROVIDER),
        }
        return

    context_chunks = retrieve_context(question, query_embedding)
    messages, context_block = build_messages(question, context_chunks, history)
    answer = _generate_grounded_answer(messages, context_block, question)
    yield {"type": "chunk", "text": answer}

    cache.store(question, answer, query_embedding)

    sources = sorted({_display_source(c["section"]) for c in context_chunks}) or ["No matching policy section"]
    follow_ups = generate_follow_ups(question, answer, provider=HR_PROVIDER)
    yield {"type": "done", "sources": sources, "from_cache": False, "follow_ups": follow_ups}
