# backend/resume_ranker/worker.py
"""
Background processing.

Uploading only stores the file and queues a task, so the HTTP request returns
immediately no matter how many CVs come in. A small pool of daemon threads
inside the API process drains the queue (MongoDB `Tasks` collection):

  parse  extract text -> LLM parse -> duplicate check -> queue scoring
  score  one (resume, job) pair -> LLM verdicts -> weighted score

Claiming is an atomic find_one_and_update, so it stays correct even if the API
runs with several uvicorn workers. Tasks are durable: if the server restarts,
tasks that were mid-flight are put back in the queue at startup. Rate-limit /
timeout errors retry with backoff; corrupt files and bad keys fail once and are
recorded against the file (never blocking the rest of the batch).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from bson import ObjectId

from backend.resume_ranker import config, llm
from backend.resume_ranker.db import jobs, resumes, scores, tasks
from backend.resume_ranker.duplicates import apply_duplicate_flags, name_key
from backend.resume_ranker.embeddings import embed_resume
from backend.resume_ranker import filestore
from backend.resume_ranker.extract import ExtractionError, extract_text
from backend.resume_ranker.parser import general_score, parse_resume, phone_key, skill_key, EDU_RANKS
from backend.resume_ranker.scoring import criteria_signature, score_resume

log = logging.getLogger("resume_ranker.worker")

MAX_ATTEMPTS = 4
STALE_RUNNING_AFTER = timedelta(minutes=6)


def _now() -> datetime:
    return datetime.utcnow()


# ── queue primitives ────────────────────────────────────────────────────────

def enqueue(kind: str, resume_id, job_id=None, batch_id: str | None = None) -> None:
    resume_id, job_id = str(resume_id), (str(job_id) if job_id else None)
    if kind == "score":
        # one live score task per (resume, job) — re-clicking "score" must not pile up work
        if tasks.find_one({"kind": "score", "resume_id": resume_id, "job_id": job_id,
                           "status": {"$in": ["queued", "running"]}}):
            return
    tasks.insert_one({"kind": kind, "resume_id": resume_id, "job_id": job_id, "batch_id": batch_id,
                      "status": "queued", "attempts": 0, "error": None,
                      "created_at": _now(), "run_after": _now()})


def claim_next() -> dict | None:
    return tasks.find_one_and_update(
        {"status": "queued", "run_after": {"$lte": _now()}},
        {"$set": {"status": "running", "started_at": _now()}, "$inc": {"attempts": 1}},
        sort=[("created_at", 1)], return_document=True)


def recover_stuck() -> int:
    """Put tasks that were 'running' when the process died back in the queue.
    The age threshold is longer than the slowest legitimate task (a model call
    with its retries), so a live worker's task is never stolen."""
    res = tasks.update_many({"status": "running", "started_at": {"$lt": _now() - STALE_RUNNING_AFTER}},
                            {"$set": {"status": "queued", "run_after": _now()}})
    return res.modified_count


def _finish(task: dict, status: str = "done", error: str | None = None) -> None:
    tasks.update_one({"_id": task["_id"]}, {"$set": {"status": status, "error": error, "finished_at": _now()}})


def _retry_or_fail(task: dict, message: str) -> bool:
    """Returns True if re-queued, False if attempts are exhausted."""
    if task["attempts"] >= MAX_ATTEMPTS:
        _finish(task, "failed", message)
        return False
    delay = timedelta(seconds=20 * task["attempts"])
    tasks.update_one({"_id": task["_id"]},
                     {"$set": {"status": "queued", "run_after": _now() + delay, "error": message}})
    return True


# ── task handlers ───────────────────────────────────────────────────────────

def run_task(task: dict) -> None:
    try:
        if task["kind"] == "parse":
            _handle_parse(task)
        elif task["kind"] == "score":
            _handle_score(task)
        else:
            _finish(task, "failed", f"unknown task kind {task['kind']}")
    except Exception as exc:  # never let one task kill the worker thread
        log.exception("task %s crashed", task.get("_id"))
        _fail_target(task, f"Internal error: {exc}")
        _finish(task, "failed", str(exc))


def _fail_target(task: dict, message: str) -> None:
    if task["kind"] == "parse":
        resumes.update_one({"_id": ObjectId(task["resume_id"])},
                           {"$set": {"status": "failed", "error": message, "failed_at": _now()}})
    elif task["kind"] == "score" and task.get("job_id"):
        _save_score_error(task["resume_id"], task["job_id"], message)


def _handle_parse(task: dict) -> None:
    rid = ObjectId(task["resume_id"])
    resume = resumes.find_one({"_id": rid})
    if not resume:
        return _finish(task, "done")
    resumes.update_one({"_id": rid}, {"$set": {"status": "processing", "error": None}})

    def fail(message: str):
        log.warning("resume %s (%s) failed: %s", rid, resume.get("filename"), message)
        resumes.update_one({"_id": rid}, {"$set": {"status": "failed", "error": message, "failed_at": _now()}})
        _finish(task, "failed", message)

    text = resume.get("text")
    if not text:
        try:
            text = extract_text(filestore.read(resume), resume.get("filename", ""))
        except ExtractionError as exc:
            return fail(str(exc))
        except (OSError, FileNotFoundError):
            return fail("Stored file is missing — please upload this CV again")

    try:
        parsed = parse_resume(text)
    except llm.LLMTransientError as exc:
        if _retry_or_fail(task, str(exc)):
            resumes.update_one({"_id": rid}, {"$set": {"status": "queued", "text": text}})
        else:
            fail(f"AI parsing kept failing: {exc}")
        return
    except llm.LLMError as exc:
        return fail(str(exc))

    if not (parsed["skills"] or parsed["experience"] or parsed["education"]):
        return fail("Doesn't look like a resume — no skills, experience or education could be found")

    update = {
        "status": "parsed", "error": None, "text": text, "parsed": parsed, "parsed_at": _now(),
        "name": parsed["name"] or _name_from_filename(resume.get("filename", "")),
        "email": parsed["email"], "phone": parsed["phone"], "phone_key": phone_key(parsed["phone"]),
        "location": parsed["location"],
        "total_years": parsed["total_years_experience"],
        "skills_key": sorted({skill_key(s) for s in parsed["skills"] if skill_key(s)}),
        "education_rank": EDU_RANKS.get(parsed["highest_education_level"], 0),
    }
    update["name_key"] = name_key(update["name"])
    # Job-independent ranking score ("upload CVs, AI ranks every one") — free,
    # computed from the fields already extracted above (see parser.general_score).
    gs = general_score(parsed)
    update["general_score"] = gs["total"]
    update["general_breakdown"] = gs["breakdown"]
    # Best-effort: powers the relevance pre-filter only (see prefilter.py). A
    # failure here never fails parsing — this resume just won't be
    # pre-filterable and will always be fully LLM-scored, the safe fallback.
    try:
        update["embedding"] = embed_resume(parsed)
    except Exception:
        log.exception("resume embedding failed for %s", rid)
    resumes.update_one({"_id": rid}, {"$set": update})

    fresh = resumes.find_one({"_id": rid})
    try:
        apply_duplicate_flags(fresh)
    except Exception:
        log.exception("duplicate check failed for %s", rid)

    for job_id in fresh.get("pending_job_ids") or []:
        enqueue("score", rid, job_id, fresh.get("batch_id"))
    resumes.update_one({"_id": rid}, {"$set": {"pending_job_ids": []}})
    _finish(task, "done")


def _handle_score(task: dict) -> None:
    rid, jid = task["resume_id"], task["job_id"]
    resume = resumes.find_one({"_id": ObjectId(rid)})
    job = jobs.find_one({"_id": ObjectId(jid)}) if jid else None
    if not resume or not job:
        return _finish(task, "done")                       # resume or job deleted meanwhile
    if resume.get("status") != "parsed":
        return _finish(task, "failed", "Resume was not parsed, nothing to score")

    try:
        result = score_resume(job, resume["parsed"])
    except llm.LLMTransientError as exc:
        if not _retry_or_fail(task, str(exc)):
            _save_score_error(rid, jid, f"AI scoring kept failing: {exc}")
        return
    except llm.LLMError as exc:
        _save_score_error(rid, jid, str(exc))
        return _finish(task, "failed", str(exc))

    scores.update_one(
        {"job_id": jid, "resume_id": rid},
        {"$set": {**result, "status": "scored", "error": None, "criteria_sig": criteria_signature(job),
                  "scored_at": _now()},
         "$setOnInsert": {"stage": "new", "created_at": _now()}},
        upsert=True)
    _finish(task, "done")


def _save_score_error(rid: str, jid: str, message: str) -> None:
    scores.update_one(
        {"job_id": jid, "resume_id": rid},
        {"$set": {"status": "error", "error": message, "scored_at": _now()},
         "$setOnInsert": {"stage": "new", "created_at": _now(), "total": None}},
        upsert=True)


def _name_from_filename(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    return stem.replace("_", " ").replace("-", " ").strip() or "Unknown"


# ── the pool ────────────────────────────────────────────────────────────────

class WorkerPool:
    def __init__(self):
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self, n: int | None = None) -> None:
        with self._lock:
            if any(t.is_alive() for t in self._threads):
                return
            self._stop.clear()
            recovered = recover_stuck()
            if recovered:
                log.info("re-queued %d interrupted tasks", recovered)
            self._threads = [threading.Thread(target=self._loop, name=f"resume-worker-{i}", daemon=True)
                             for i in range(n or config.worker_count())]
            for t in self._threads:
                t.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        last_sweep = _now()
        while not self._stop.is_set():
            if _now() - last_sweep > timedelta(minutes=1):
                last_sweep = _now()
                try:
                    recover_stuck()
                except Exception:
                    log.exception("recover_stuck failed")
            try:
                task = claim_next()
            except Exception:
                log.exception("claim failed")
                self._stop.wait(5)
                continue
            if task is None:
                self._stop.wait(1.0)
                continue
            run_task(task)


pool = WorkerPool()
