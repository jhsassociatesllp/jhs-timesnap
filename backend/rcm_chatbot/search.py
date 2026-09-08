"""
Retrieval (Pinecone semantic search) + answer-shaping logic for the RCM
chatbot. Ported from the standalone Sentinel app's backend/search.py —
the field-extraction / product-detection / ranking logic here is kept as
close to verbatim as possible; the only real change is *how* candidate rows
are found (search_documents queries the RCM Pinecone index instead of
MongoDB $text/regex — see backend/rcm_chatbot/vectorstore.py). Everything
downstream of that (ranking, direct_field_answer, formatting) works on the
same row shape {file, sheet, header, row, collection, text} regardless of
where it came from, so it's unchanged.

The actual LLM call (backend/chatbot/answer.py in this port) is kept out of
this module — see answer.py for that, and for why.
"""
import re
import math
from itertools import zip_longest
from typing import List, Dict, Any, Optional

from backend.chatbot.embeddings import embed_text
from backend.rcm_chatbot.config import rcm_settings
from backend.rcm_chatbot.vectorstore import get_index, list_namespaces

STOPWORDS = {
    "the", "and", "for", "are", "what", "which", "checklist", "list", "show",
    "give", "tell", "about", "with", "from", "that", "this", "how", "does",
    "under", "item", "items",
}


def pretty_name(name: str) -> str:
    """Turn an auto-generated slug namespace name (e.g. category_filename,
    underscore-separated) into a readable label, collapsing words repeated
    from the category+filename concatenation so it doesn't read twice as long."""
    seen = set()
    out = []
    for w in (name or "").split("_"):
        if not w:
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return " ".join(out) or name


def _tokenize(q: str) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9]+", q.lower())
    return [w for w in words if len(w) > 2 and w not in STOPWORDS]


def _singularize(word: str) -> str:
    """Cheap depluralization so "buyers" (query wording) and "buyer" (a
    namespace's own name) count as the same word for product-name matching -
    just enough to cover the common case, not a real stemmer."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def _detect_product_collection(query: str, target_names: List[str]) -> Optional[str]:
    """When a query names a specific product/process that closely matches ONE
    namespace's own distinguishing NAME words (not its row content), commit
    retrieval to that namespace alone instead of searching everything.

    This is what actually distinguishes two DIFFERENT checklists that happen
    to share vocabulary in their row content - e.g. a generic "Buyers Credit"
    sub-process nested inside the Import LC checklist (whose own namespace
    name never says "buyer" or "loan" - only rows inside it happen to) versus
    a dedicated "...Buyer_Credit_Loan" namespace (whose name says exactly
    that). Content-based scoring alone can't tell these apart, since both
    mention "buyer"/"credit" throughout their rows - but only one of them IS,
    by name, the product actually being asked about.

    Returns None (falls through to normal cross-namespace search) unless one
    namespace has a real, distinctive MULTI-word name-match AND a clear lead
    over the next-best candidate. Multi-word, not just "distinctive", matters:
    a single coincidentally-rare word is not enough. Requiring at least 2
    matched name-words is what tells "this namespace's own name IS the
    subject" apart from "one ambient word happens to overlap." An ambiguous
    query that doesn't actually name one specific product this clearly
    should search broadly, not commit to a guess."""
    if len(target_names) < 2:
        return None
    name_tokens = {name: {_singularize(t) for t in _tokenize(name.replace("_", " "))} for name in target_names}
    doc_freq: Dict[str, int] = {}
    for tokens in name_tokens.values():
        for t in tokens:
            doc_freq[t] = doc_freq.get(t, 0) + 1
    n = len(target_names)
    query_tokens = {_singularize(t) for t in _tokenize(query)}
    if not query_tokens:
        return None
    scores = {}
    for name, tokens in name_tokens.items():
        matched = query_tokens & tokens
        if len(matched) >= 2:  # a single shared word is never enough - see docstring
            scores[name] = sum(math.log((n + 1) / (doc_freq[t] + 1)) + 1 for t in matched)
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_name, best_score = ranked[0]
    if best_score < 2.5:  # not a real, distinctive match - just noise
        return None
    if len(ranked) > 1 and ranked[1][1] >= best_score * 0.7:  # no clear single winner
        return None
    return best_name


def _match_to_doc(match: dict, namespace: str) -> Dict[str, Any]:
    meta = match.get("metadata") or {}
    return {
        "_id": match.get("id"),
        "collection": namespace,
        "file": meta.get("file"),
        "sheet": meta.get("sheet"),
        "header": meta.get("header") or [],
        "row": meta.get("row") or [],
        "text": meta.get("text", ""),
    }


def search_documents(query: str, collection: Optional[str] = "All", limit: int = None) -> List[Dict[str, Any]]:
    """Each named collection is a Pinecone namespace, so when scope is "All"
    we fan out the query across every one and merge by relevance.

    `limit` is generous by default (not the handful you'd need for a single-
    fact lookup) so a broad/synthesis-style question ("what criteria should
    I check for X") - whose real answer is often scattered across dozens of
    rows, not concentrated in one - still surfaces enough candidates for the
    LLM to actually synthesize from."""
    limit = limit or rcm_settings.TOP_K
    target_names = [collection] if collection and collection != "All" else list_namespaces()
    terms = _tokenize(query)

    candidates: List[Dict[str, Any]] = []
    seen_ids = set()

    def _collect(doc):
        key = (doc["collection"], doc["_id"])
        if key in seen_ids:
            return
        seen_ids.add(key)
        candidates.append(doc)

    if not target_names:
        return []

    index = get_index()
    query_vector = embed_text(query)

    # If the query names one specific product/process clearly enough to
    # identify a single namespace by NAME, commit to it entirely and widen
    # `limit` - every row in the right checklist is relevant by construction
    # once the right product is identified, so this pulls (effectively) the
    # whole namespace directly rather than depending on similarity-ranking,
    # which could still under-rank rows whose own wording just doesn't
    # happen to closely echo the question.
    product_locked = False
    if collection == "All" or not collection:
        detected = _detect_product_collection(query, target_names)
        if detected:
            target_names = [detected]
            limit = max(limit, rcm_settings.PRODUCT_LOCK_TOP_K)
            product_locked = True

    for name in target_names:
        try:
            result = index.query(
                vector=query_vector,
                top_k=limit if product_locked else limit * 2,
                namespace=name,
                include_metadata=True,
            )
        except Exception:
            continue
        for match in result.get("matches") or []:
            _collect(_match_to_doc(match, name))

    if not terms or not candidates:
        return candidates[:limit]

    # Rank the merged candidate pool by a signal that's actually comparable
    # across many different namespaces: how many of the question's own
    # significant terms it contains, weighted by each term's rarity ACROSS
    # THIS CANDIDATE POOL - a cheap post-hoc IDF, on top of (not instead of)
    # Pinecone's own similarity ranking that already shaped which candidates
    # made it into the pool.
    doc_freq = {t: 0 for t in terms}
    texts = [d.get("text", "") for d in candidates]
    for text in texts:
        for t in terms:
            if t in text:
                doc_freq[t] += 1
    n = len(candidates)
    weights = {t: math.log((n + 1) / (doc_freq[t] + 1)) + 1 for t in terms}
    max_score = sum(weights.values()) or 1
    for doc, text in zip(candidates, texts):
        doc["_rank_score"] = sum(w for t, w in weights.items() if t in text) / max_score

    candidates.sort(key=lambda d: d["_rank_score"], reverse=True)
    return candidates[:limit]


def row_pairs(header, row):
    """Pair every header/value cell, including cells with a blank header (labeled
    positionally instead of dropped) and any values trailing past the header's
    length - so no detail actually present in the row is ever silently lost."""
    pairs = []
    for i, (h, v) in enumerate(zip_longest(header, row, fillvalue=""), start=1):
        v = str(v).strip() if v is not None else ""
        if not v:
            continue
        label = str(h).strip() if h else f"Field {i}"
        pairs.append((label, v))
    return pairs


def format_doc_for_context(doc: Dict[str, Any]) -> str:
    # Cells in this data can legitimately run to several thousand characters (a
    # whole procedure write-up in one field, e.g. ending in "Conclusion: ..."),
    # so this needs headroom well past a low cutoff or the AI silently never
    # sees the tail of the cell - including exactly the part being asked about.
    pairs = row_pairs(doc.get("header", []), doc.get("row", []))
    lines = [f"{h}: {v[:5000]}" for h, v in pairs]
    return f"[Source: {pretty_name(doc.get('collection', ''))} › {doc.get('file')} › {doc.get('sheet')}]\n" + "\n".join(lines)


# Sub-labels that recur inline within a single checklist cell (e.g. one cell's
# text reads "Objective: ...\nData Receipt: ...\n...\nConclusion: ..."). When a
# question names one of these directly ("What is the Conclusion for X"), pull
# that field's real value straight from the data instead of asking the LLM to
# pick it out - repeated testing (on the original app) showed the model
# unreliably substitutes a full procedure walkthrough instead of answering
# the specific field asked about.
FIELD_LABELS = [
    "Conclusion", "Objective", "Frequency", "Check points",
    "System Reports and Documents", "Data Receipt", "Data Extraction",
    "Data Validation", "Agreed Upon Procedures", "Verification Methodology",
]

# Shorter natural phrasings a user actually types that should resolve to one
# of the real FIELD_LABELS above ("procedure"/"procedures" almost never comes
# with the full "Agreed Upon Procedures" wording attached, so the plain
# substring check below would otherwise miss it and fall through to the LLM's
# general-summary path, which drifts toward describing the Objective instead).
_FIELD_SYNONYMS = {
    "procedures": "Agreed Upon Procedures",
    "procedure": "Agreed Upon Procedures",
    "methodology": "Verification Methodology",
}

# All recognized terms, matched longest-first so multi-word labels win over a
# shorter synonym/label that happens to be a substring of them.
_ALL_FIELD_TERMS = sorted(set(FIELD_LABELS) | set(_FIELD_SYNONYMS), key=len, reverse=True)
_FIELD_TERMS_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in _ALL_FIELD_TERMS) + r")\b",
    re.IGNORECASE,
)


def _detect_field_request(query: str) -> Optional[str]:
    q = query.lower()
    matches = [label for label in FIELD_LABELS if label.lower() in q]
    matches += [
        canonical for term, canonical in _FIELD_SYNONYMS.items()
        if re.search(rf"\b{re.escape(term)}\b", q)
    ]
    return max(matches, key=len) if matches else None


_FIELD_QUESTION_STOPWORDS = {
    "what", "is", "the", "of", "for", "tell", "me", "show", "give", "please",
    "in", "a", "an", "and", "conclusion", "item",
}


def _significant_tokens(s: str) -> set:
    words = re.findall(r"[a-zA-Z0-9]+", s.lower())
    return {w for w in words if w not in _FIELD_QUESTION_STOPWORDS and len(w) > 1}


def _item_name_from_query(query: str) -> str:
    q = _FIELD_TERMS_RE.sub(" ", query)
    words = re.findall(r"[a-zA-Z0-9]+", q)
    kept = [w for w in words if w.lower() not in _FIELD_QUESTION_STOPWORDS]
    return " ".join(kept).strip()


_SUBLABEL_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z /&]{1,40}):\s*(.*)$")

_CONTAINER_LABELS = {"agreed upon procedures", "system reports and documents"}


def _split_into_points(raw_span: str) -> List[List[str]]:
    lines = [ln.strip() for ln in raw_span.split("\n") if ln.strip()]
    points = []  # list of [label, body]
    pending_header = False
    swallow_rest = False
    for ln in lines:
        if swallow_rest:
            points[-1][1] = f"{points[-1][1]} {ln}".strip()
            continue
        m = _SUBLABEL_LINE_RE.match(ln)
        if m:
            label_part, content_part = m.group(1).strip(), m.group(2).strip()
            points.append([label_part, content_part])
            pending_header = not content_part
            if label_part.lower() == "system reports and documents":
                swallow_rest = True
        elif pending_header and points:
            points[-1][1] = f"{points[-1][1]} {ln}".strip()
        else:
            points.append(["", ln])
    return points


def _format_points_as_list(points: List[List[str]]) -> str:
    formatted = [f"**{lbl}:** {body}" if lbl else body for lbl, body in points]
    return "\n".join(f"{i + 1}. {pt}" for i, pt in enumerate(formatted))


def _extract_field_value(full_text: str, label: str) -> Optional[str]:
    if label.lower() in _CONTAINER_LABELS:
        boundary = r"\nConclusion\s*:|\Z"
    else:
        boundary = r"\n[A-Z][A-Za-z ]{2,40}:|\Z"
    starts = list(re.finditer(rf"{re.escape(label)}\s*:\s*", full_text, re.IGNORECASE))
    if not starts:
        return None
    value_start = starts[-1].end()
    m = re.compile(rf"(.*?)(?={boundary})", re.IGNORECASE | re.DOTALL).match(full_text, value_start)
    if not m:
        return None
    points = _split_into_points(m.group(1))
    if len(points) >= 2:
        return _format_points_as_list(points) or None
    value = re.sub(r"\s+", " ", m.group(1)).strip(" \t\n-•")
    return value or None


_KEY_FINDINGS_REF_RE = re.compile(
    r"refer\s+(?:to\s+)?point\s*(?:no\.?)?\s*(\d+)\s+of\s+(?:the\s+)?key\s*findings",
    re.IGNORECASE,
)

_REVIEW_BLOCK_RE = re.compile(
    r"[A-Za-z][A-Za-z ]*\breview\s*:\s*\n?(.*?)(?=\n[A-Z][A-Za-z ]{2,40}:|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _resolve_key_findings_point(value: str, full_text: str) -> str:
    m = _KEY_FINDINGS_REF_RE.search(value)
    if not m:
        return value
    point_no = int(m.group(1))
    for block_m in _REVIEW_BLOCK_RE.finditer(full_text):
        lines = [ln.strip(" \t-•") for ln in block_m.group(1).split("\n") if ln.strip()]
        if len(lines) >= 2 and point_no <= len(lines):
            return lines[point_no - 1]
    return value


def direct_field_answer(query: str, docs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """If the question names a specific field AND a checklist item name, and a
    retrieved row actually matches both, return {"text": ..., "doc": ...} for a
    guaranteed-correct answer bypassing the LLM. Returns None if no confident
    match applies, in which case the caller should fall back to the normal
    LLM/fallback answer path."""
    label = _detect_field_request(query)
    if not label or not docs:
        return None
    item_name = _item_name_from_query(query)
    if not item_name:
        return None
    item_name_lower = item_name.lower()
    item_tokens = _significant_tokens(item_name)
    for doc in docs:
        pairs = row_pairs(doc.get("header", []), doc.get("row", []))
        matched_title = next(
            (v.strip() for h, v in pairs
             if v.strip().lower() == item_name_lower or
             (len(v.strip()) <= len(item_name_lower) + 15 and item_tokens and
              item_tokens <= _significant_tokens(v))),
            None,
        )
        if matched_title is None:
            continue
        full_text = "\n".join(f"{h}: {v}" for h, v in pairs)
        value = _extract_field_value(full_text, label)
        if value:
            value = _resolve_key_findings_point(value, full_text)
            sep = "\n" if "\n" in value else " "
            return {"text": f"**{label}:**{sep}{value}", "doc": doc}
    return None


def markdown_to_html(text: str) -> str:
    """Minimal, safe markdown -> HTML renderer (headers, bullets, numbered lists, bold, paragraphs)."""
    import html
    escaped = html.escape(text)
    lines = escaped.split("\n")
    out = []
    list_tag = None

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^#{1,4}\s+", line):
            close_list()
            header_text = re.sub(r'^#{1,4}\s+', '', line)
            out.append(f"<h4>{header_text}</h4>")
            continue
        if re.match(r"^[-*•]\s+", line):
            if list_tag != "ul":
                close_list()
                out.append("<ul>")
                list_tag = "ul"
            item_text = re.sub(r'^[-*•]\s+', '', line)
            out.append(f"<li>{_boldify(item_text)}</li>")
            continue
        if re.match(r"^\d+[.)]\s+", line):
            if list_tag != "ol":
                close_list()
                out.append("<ol>")
                list_tag = "ol"
            item_text = re.sub(r'^\d+[.)]\s+', '', line)
            out.append(f"<li>{_boldify(item_text)}</li>")
            continue
        close_list()
        out.append(f"<p>{_boldify(line)}</p>")
    close_list()
    return "".join(out)


def _boldify(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
