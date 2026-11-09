# backend/resume_ranker/prefilter.py
"""
The relevance pre-filter itself — see config.py's "relevance pre-filter"
section for why this exists and its safety rules. Short version: only runs
above a minimum pool size, only ever *adds* a cheap early exit, never removes
the option to fully score anyone.
"""
from __future__ import annotations

from backend.resume_ranker import config
from backend.resume_ranker.embeddings import cosine_similarity


def split_candidates(job: dict, resumes: list[dict]) -> tuple[list[dict], list[dict]]:
    """(to_score, screened_out). Below the minimum pool size, or when the job
    has no embedding (e.g. embedding failed, or the feature found nothing to
    compare against), everyone goes to `to_score` — unchanged old behaviour.

    A resume with no embedding of its own is ALWAYS put in `to_score`: with no
    similarity signal for it, screening it out would be a guess, not a cost
    optimization, and a missed candidate is worse than a wasted LLM call.
    """
    job_vec = job.get("embedding")
    if not job_vec or len(resumes) <= config.prefilter_min_pool():
        return resumes, []

    no_vec = [r for r in resumes if not r.get("embedding")]
    scored_pool = [r for r in resumes if r.get("embedding")]
    ranked = sorted(scored_pool, key=lambda r: cosine_similarity(r["embedding"], job_vec), reverse=True)

    top_k = config.prefilter_top_k()
    to_score = no_vec + ranked[:top_k]
    screened_out = ranked[top_k:]
    return to_score, screened_out


def screened_out_result(job: dict, resume: dict) -> dict:
    """The placeholder score record for a screened-out candidate — no LLM
    call made, clearly labelled, and trivially overridable (see router.py's
    "Score anyway" path, which uses scope=selected and always fully scores)."""
    return {
        "total": None,
        "sub_scores": {},
        "flags": [],
        "capped": False,
        "meets_all_must_haves": None,
        "summary": ("Screened out by the relevance pre-filter (embedding similarity to this job's "
                    "requirements was low). No AI scoring call was made, so this costs nothing — "
                    "select it and choose \"Score anyway\" to run the full evaluation."),
        "strengths": [], "concerns": [], "masked": bool(job.get("mask_personal_info")), "model": None,
    }
