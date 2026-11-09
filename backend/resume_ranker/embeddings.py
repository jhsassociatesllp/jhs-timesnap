# backend/resume_ranker/embeddings.py
"""
Embeddings — used ONLY as a cost pre-filter before full LLM scoring, never as
a replacement for it (see config.py's "relevance pre-filter" section for the
full reasoning).

Every function here is best-effort: embedding a resume/job is an optimization,
not a requirement. A resume or job with no embedding (API hiccup, feature
disabled, embedded before this feature existed) is simply always fully
scored — see prefilter.py, which treats a missing embedding as "can't screen
this one out, so don't."
"""
from __future__ import annotations

import math

from backend.resume_ranker import config, llm


def embed_text(text: str) -> list[float]:
    """Raises llm.LLMError / llm.LLMTransientError on failure — same error
    classes as chat calls, so callers can reuse the same retry handling."""
    client = llm.get_client()
    text = (text or "").strip()[:8000] or "empty"
    try:
        resp = client.embeddings.create(model=config.embed_model(), input=text)
    except Exception as exc:
        raise llm.classify_error(exc) from exc
    return resp.data[0].embedding


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    """Returns 0.0 (not -1) for missing/mismatched vectors — treated by
    callers as "no similarity signal", never as "actively dissimilar"."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def resume_embedding_text(parsed: dict) -> str:
    """Compact text capturing what makes a candidate matchable to a job —
    deliberately excludes name/contact/dates, which are irrelevant to (and
    would only dilute) a relevance comparison."""
    parts = [
        parsed.get("headline") or "",
        "Skills: " + ", ".join(parsed.get("skills") or []),
        "Certifications: " + ", ".join(parsed.get("certifications") or []),
        "Industries: " + ", ".join(parsed.get("industries") or []),
    ]
    for e in (parsed.get("experience") or [])[:8]:
        parts.append(" - ".join(filter(None, [e.get("title"), e.get("industry"), e.get("summary")])))
    for e in (parsed.get("education") or [])[:4]:
        parts.append(" - ".join(filter(None, [e.get("degree"), e.get("field")])))
    return "\n".join(p for p in parts if p and p.strip())


def job_embedding_text(job: dict) -> str:
    """Compact text capturing what a job is looking for — mirrors
    resume_embedding_text's shape so the two sides compare like with like."""
    parts = [
        job.get("title") or "",
        "Required skills: " + ", ".join(s["name"] for s in job.get("required_skills") or []),
        "Preferred skills: " + ", ".join(job.get("preferred_skills") or []),
        "Required certifications: " + ", ".join(c["name"] for c in job.get("required_certifications") or []),
        "Industries: " + ", ".join(job.get("industries") or []),
        (job.get("description") or "")[:2000],
    ]
    return "\n".join(p for p in parts if p and p.strip())


def embed_resume(parsed: dict) -> list[float] | None:
    """None on any failure — the resume just won't be pre-filterable; it will
    always be fully scored instead (the safe default)."""
    try:
        return embed_text(resume_embedding_text(parsed))
    except Exception:
        return None


def embed_job(job: dict) -> list[float] | None:
    try:
        return embed_text(job_embedding_text(job))
    except Exception:
        return None
