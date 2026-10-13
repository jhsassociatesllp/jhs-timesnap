# backend/resume_ranker/config.py
"""
Settings for the Resume Ranker module. Read from the environment on every call
(not frozen at import) so .env edits and tests can change them.

OpenAI key lookup order (first non-empty wins) — reuses the key the HR chatbot
already has, so no new secret is needed on the server:
    RESUME_OPENAI_API_KEY -> HR_OPENAI_API_KEY -> LLM_API_KEY -> OPENAI_API_KEY
"""
import os
from dotenv import load_dotenv

load_dotenv()

_KEY_VARS = ("RESUME_OPENAI_API_KEY", "HR_OPENAI_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
MAX_FILE_BYTES = int(os.getenv("RESUME_MAX_FILE_MB", "10")) * 1024 * 1024
MAX_FILES_PER_REQUEST = 25
MAX_TEXT_CHARS = 60_000          # stored/searchable text cap per resume
MAX_PROMPT_CHARS = 24_000        # resume text sent to the LLM (~6k tokens)


def api_key() -> str:
    for var in _KEY_VARS:
        val = (os.getenv(var) or "").strip()
        if val:
            return val
    return ""


def base_url() -> str:
    return os.getenv("RESUME_OPENAI_BASE_URL") or os.getenv("HR_OPENAI_BASE_URL") or "https://api.openai.com/v1"


def parse_model() -> str:
    return os.getenv("RESUME_PARSE_MODEL", "gpt-4o-mini")


def score_model() -> str:
    return os.getenv("RESUME_SCORE_MODEL", "gpt-4o-mini")


def worker_count() -> int:
    return max(1, int(os.getenv("RESUME_WORKERS", "4")))


def upload_dir() -> str:
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "data", "resume_ranker", "uploads")
    return os.getenv("RESUME_UPLOAD_DIR", default)


# ── relevance pre-filter (cost control at scale) ────────────────────────────
# Parsing every resume always needs one LLM call each — that cost is fixed.
# Scoring is the part that scales: "score existing resumes against this job"
# scores the WHOLE historical database, and that database only grows over
# time (e.g. ~40 CVs/day -> ~14,000/year). Scoring all of them against every
# new job would eventually mean thousands of LLM calls per job, most spent on
# resumes that are obviously unrelated to it.
#
# The pre-filter only kicks in once a job's candidate pool is large enough for
# that cost to matter (PREFILTER_MIN_POOL) — below that, everyone is always
# fully scored by the LLM exactly as before, so nothing changes for small
# batches. Above it, only the top PREFILTER_TOP_K candidates by embedding
# similarity get the full (expensive) LLM scoring call; the rest are marked
# "screened_out" (no LLM call, near-zero cost) but are NEVER hidden — HR can
# always select a screened-out candidate and "Score anyway" to force the full
# evaluation. Embeddings are a cheap, best-effort optimization: if embedding a
# resume/job ever fails, that item simply has no embedding and is always
# fully scored (the safe fallback — never silently skipped due to a glitch).
def embed_model() -> str:
    return os.getenv("RESUME_EMBED_MODEL", "text-embedding-3-small")


def prefilter_min_pool() -> int:
    """Candidate-pool size (for one job) at/below which everyone is always
    fully LLM-scored — the pre-filter never runs for a small batch."""
    return int(os.getenv("RESUME_PREFILTER_MIN_POOL", "150"))


def prefilter_top_k() -> int:
    """Above prefilter_min_pool(), the number of top-similarity candidates
    that still get the full LLM scoring call."""
    return int(os.getenv("RESUME_PREFILTER_TOP_K", "150"))


# ── ad-hoc "AI Rank" search (no job selected) ───────────────────────────────
# Same principle as the pre-filter above, applied to the "AI Rank" search
# button: that button can be pointed at an arbitrarily large, unfiltered
# result set, so it must NEVER fan out one real LLM call per match — a search
# matching a few thousand resumes must not mean a few thousand OpenAI calls
# in a single request. Only the top ADHOC_AI_RANK_MAX candidates by embedding
# similarity get the real (expensive) LLM scoring call; everyone else gets
# the free heuristic scorer instead, so results stay complete and ranked,
# just less finely judged beyond the cap.
def adhoc_ai_rank_max() -> int:
    return int(os.getenv("RESUME_ADHOC_AI_RANK_MAX", "40"))
