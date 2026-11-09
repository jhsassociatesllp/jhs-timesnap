"""
Lightweight RAG pipeline.

Why TF-IDF instead of a neural embedding model:
- No GPU/heavy download needed, ingestion is fast and cheap.
- The document is read ONCE at upload time, chunked, and a bank of
  questions is generated once and cached in MongoDB. Every quiz after
  that is just a random sample from the cached pool - so the LLM is
  never called again for the same document. This is the "cost saving"
  the RAG setup is for: one ingestion cost, unlimited quizzes.
"""
import json
import os
import random
import re
import uuid
from io import BytesIO
from typing import List

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from backend.hr_policy_quiz.config import settings

try:
    from openai import OpenAI
    _client = OpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None
except Exception:
    _client = None


def extract_text(file_bytes: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if name.endswith(".docx"):
        from docx import Document as DocxDocument
        doc = DocxDocument(BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(file_bytes), data_only=True, read_only=True)
        lines = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    lines.append(" ".join(cells))
        return "\n".join(lines)
    # fall back to plain text
    return file_bytes.decode("utf-8", errors="ignore")


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 150) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return [c.strip() for c in chunks if len(c.strip()) > 50]


def build_tfidf_matrix(chunks: List[str]):
    """Used for retrieval if we ever need to fetch the most relevant chunks
    for a specific topic. Returns the vectorizer and matrix as plain lists
    so they are JSON/Mongo friendly."""
    vectorizer = TfidfVectorizer(stop_words="english", max_features=2000)
    matrix = vectorizer.fit_transform(chunks)
    return vectorizer, matrix


def most_relevant_chunks(query: str, chunks: List[str], vectorizer, matrix, top_k: int = 3) -> List[str]:
    query_vec = vectorizer.transform([query])
    scores = cosine_similarity(query_vec, matrix).flatten()
    top_idx = np.argsort(scores)[::-1][:top_k]
    return [chunks[i] for i in top_idx]


QUESTION_PROMPT = """You are an expert HR trainer writing quiz questions for a new employee joining JHS Associates.
The excerpt below is from the document titled "{title}"{category_line}.
Write up to {n} multiple-choice question(s) that check whether the employee understood the RULES in this excerpt.

THE MOST IMPORTANT RULE - every question must be SELF-CONTAINED and SPECIFIC
A reader who has not seen the document must understand exactly what is being asked and which policy it is about.
- Name the topic or policy inside the question, for example "Under the {title}, ..." or "When an employee wants to ..., what must they do first?".
- Describe the situation ("If a client sends original documents by courier, ...").
- NEVER write vague questions such as "Where should all documents be saved?", "What does the policy say?", "What should you do?".

WHAT TO ASK
- ONE concrete rule or fact from the excerpt: a number, time limit, deadline, amount, name of a form or system, who must be informed or must approve, a required step, something that is allowed or not allowed, or a consequence.
- Only facts the excerpt actually states. Never invent anything. Never rely on outside knowledge or common sense: a question that can be answered without the document is a bad question.
- If the excerpt has no concrete rule or fact (headings, table of contents, definitions with no action, greetings, legal boilerplate), return an empty list [] - that is a good answer. Fewer than {n} questions is fine.
- Skip trivia: page numbers, section numbers, headings, formatting, minor details that do not affect the employee's work.

LANGUAGE
- Plain, simple English. Short sentences. No jargon, no copied legal wording.
- No double negatives and no "which is NOT / EXCEPT / INCORRECT" questions.
- Start with a question word (What / Who / When / How many / How long / Which / Where / How).

ANSWER OPTIONS
- Exactly 4 options and exactly 1 correct answer. The correct answer must be stated in the excerpt.
- The 3 wrong options must be REALISTIC alternatives that a careless person could believe: the same type as the right answer (all numbers, all time periods, all roles, all places, all actions), each sounding like a plausible rule in a real office - for example the same rule with a different number, role or step.
- NEVER use silly, joke or obviously wrong options (such as "On the desktop", "In random places", "Whenever you feel like it", "Nobody", "It does not matter"). Never use "All of the above" or "None of the above".
- Keep options short (under 10 words), clearly different from each other, and do not let the question's wording give the answer away.

BAD:  "Where should all documents be saved?"  with options "On the desktop / In random places / ..."
GOOD: "Under the Document Management Policy, where must client files be saved once a job is finished?"
      options: "In the client's folder on the firm's shared drive" / "In the employee's personal email" / "On a personal USB drive" / "In the employee's private cloud account"

Return ONLY valid JSON - no extra text, no markdown - in this exact shape:
[
  {{"question": "...", "options": ["...", "...", "...", "..."], "correct_index": 0, "source": "short exact quote (max 20 words) from the excerpt that proves the correct answer"}}
]
correct_index is the 0-based index of the correct option in the options array.

Excerpt:
\"\"\"{excerpt}\"\"\"
"""

REVIEW_PROMPT = """You are a strict quality reviewer of HR quiz questions about the document "{title}".
For EACH question below decide whether it is good enough to give to a new employee. A question is good only if ALL of these are true:
1. SELF-CONTAINED: it names the topic / policy or the situation, so someone who has not read the document knows exactly what is asked. (Bad: "Where should all documents be saved?")
2. SENSIBLE: it asks about a real rule, number, step, role, deadline or consequence that matters in the employee's work - not trivia, not common sense, not something anyone could guess without the document.
3. ONE clearly correct answer; the other three are realistic alternatives of the same type. No silly or joke options (such as "On the desktop", "In random places", "Whenever you like"), no "All of the above".
{support}Return ONLY JSON: [{{"i": 0, "keep": true, "reason": "..."}}, ...] with one entry per question, in order.

Questions:
{questions}
"""

_SILLY_OPTION = re.compile(
    r"\b(random(ly)?|whenever (you|they|he|she) (feel|want|like)|nobody|no one|it does not matter|doesn't matter|anywhere|any way|"
    r"all of the above|none of the above|both a and b|don't care|do not care)\b", re.I)
_VAGUE_QUESTION = re.compile(r"\bwhat (does|do) (the|this) (policy|document|text|passage|excerpt) (say|state|mention)\b|"
                             r"\baccording to the (excerpt|passage|text) above\b", re.I)
_NEGATIVE_QUESTION = re.compile(r"\b(NOT|EXCEPT|INCORRECT|FALSE)\b")


def looks_bad(item: dict) -> str:
    """A reason (non-empty) when a question fails a cheap, certain check; '' when it passes."""
    q = (item.get("question") or "").strip()
    opts = [str(o).strip() for o in item.get("options") or []]
    if len(q) < 30:
        return "question is too short to be specific"
    if len(q) > 320:
        return "question is too long"
    if _VAGUE_QUESTION.search(q) or _NEGATIVE_QUESTION.search(q):
        return "vague or negative wording"
    if len(opts) != 4 or any(not o for o in opts):
        return "needs exactly 4 options"
    if len({o.lower() for o in opts}) != 4:
        return "two options are the same"
    if any(len(o) > 110 for o in opts):
        return "an option is too long"
    if any(_SILLY_OPTION.search(o) for o in opts):
        return "a silly / non-answer option"
    return ""


def _json_from(raw: str):
    raw = (raw or "").strip().strip("`")
    if raw.lower().startswith("json"):
        raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        return json.loads(match.group(0)) if match else []


def _chat(prompt: str, max_tokens: int) -> str:
    if _client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured. Add it to .env to enable question generation.")
    resp = _client.chat.completions.create(model=os.getenv("HR_QUIZ_QUESTION_MODEL", "").strip() or "gpt-4o-mini",
                                           max_tokens=max_tokens, temperature=0.2,
                                           messages=[{"role": "user", "content": prompt}])
    return resp.choices[0].message.content or ""


def review_questions(title: str, items: List[dict], excerpt: str = "") -> List[bool]:
    """One model call that says, for each question, whether it is good enough (see REVIEW_PROMPT).
    Best effort: if the review itself fails, every question is kept rather than lost."""
    if not items:
        return []
    listing = "\n\n".join(
        f"[{i}] {it['question']}\n" + "\n".join(f"   {'ABCD'[j]}. {o}" for j, o in enumerate(it["options"])) +
        f"\n   Correct answer: {'ABCD'[it['correct_index']]}" for i, it in enumerate(items))
    support = (f'4. SUPPORTED: the marked correct answer is clearly stated in this excerpt:\n"""{excerpt}"""\n' if excerpt else "")
    try:
        verdicts = _json_from(_chat(REVIEW_PROMPT.format(title=title or "the policy", support=support, questions=listing), 1500))
        keep = {int(v["i"]): bool(v.get("keep")) for v in verdicts if isinstance(v, dict) and "i" in v}
        return [keep.get(i, True) for i in range(len(items))]
    except RuntimeError:
        raise
    except Exception:
        return [True] * len(items)


def generate_questions_for_chunk(chunk: str, n: int, title: str = "", category: str = "") -> List[dict]:
    category_line = f' (category: {category})' if category else ""
    raw = _chat(QUESTION_PROMPT.format(n=n, excerpt=chunk, title=title or "this policy", category_line=category_line), 1800)
    try:
        data = _json_from(raw)
    except Exception:
        data = []

    cleaned = []
    for item in data if isinstance(data, list) else []:
        if (
            isinstance(item, dict)
            and item.get("question")
            and isinstance(item.get("options"), list)
            and len(item["options"]) == 4
            and isinstance(item.get("correct_index"), int)
            and 0 <= item["correct_index"] <= 3
        ):
            options = [str(o).strip() for o in item["options"]]
            cand = {"question": str(item["question"]).strip(), "options": options, "correct_index": item["correct_index"]}
            if looks_bad(cand):
                continue
            # The model tends to always place the correct answer first, so
            # shuffle option order here rather than trust its positioning.
            correct_answer = options[item["correct_index"]]
            random.shuffle(options)
            cleaned.append(
                {
                    "id": str(uuid.uuid4()),
                    "question": cand["question"],
                    "options": options,
                    "correct_index": options.index(correct_answer),
                    "source": str(item.get("source") or "")[:240],
                }
            )
    # second opinion on what is left: drops vague / trivial / silly questions
    if cleaned:
        keep = review_questions(title, cleaned, chunk)
        cleaned = [q for q, k in zip(cleaned, keep) if k]
    return cleaned


def build_question_pool(chunks: List[str], per_chunk: int = 3, title: str = "", category: str = "") -> List[dict]:
    """Calls the LLM once per chunk (small excerpts, not the whole document
    at once) so every part of the document gets read and gets a chance to
    contribute questions. The document title is given to the model so each
    question can name the policy it is about. No cap on the total - the pool
    size scales with how long the document is. A random 15 are picked from
    this pool for each candidate's actual quiz."""
    pool: List[dict] = []
    seen = set()
    for chunk in chunks:
        try:
            for q in generate_questions_for_chunk(chunk, per_chunk, title, category):
                key = re.sub(r"\W+", " ", q["question"].lower()).strip()
                if key not in seen:                                   # the same question twice is not two questions
                    seen.add(key)
                    pool.append(q)
        except RuntimeError:
            raise
        except Exception:
            continue
    return pool


def clean_pool(title: str, pool: List[dict]):
    """Remove the weak questions from a question bank that was generated earlier.
    Returns (kept, removed) where removed = [{"question", "reason"}]. Uses the cheap checks first, then the
    reviewer in batches of 12 (without the source excerpt, which is not stored)."""
    kept, removed, candidates = [], [], []
    for q in pool:
        reason = looks_bad(q)
        (removed.append({"question": q["question"], "reason": reason}) if reason else candidates.append(q))
    for i in range(0, len(candidates), 12):
        batch = candidates[i:i + 12]
        for q, ok in zip(batch, review_questions(title, batch)):
            (kept.append(q) if ok else removed.append({"question": q["question"], "reason": "reviewer: vague, trivial or unclear"}))
    return kept, removed
