"""
JHS Chatbot evaluation suite — runs the curated questions in cases.py
against each bot's REAL, live answer function (same code path the actual
chat endpoints use — no mocking), checks the answers two ways, and writes
a report.

  1. Deterministic checks (must_contain / must_not_contain): fast, exact,
     zero ambiguity — e.g. "the personalized answer must say 1,500 and must
     NOT mention Sr. Partner". These catch regressions of specific known
     facts/behaviors (like the earlier prompt-anchoring bug where the model
     said "as an Audit Executive" with no designation given).
  2. An LLM-judge pass (judge_criteria, or a generic quality rubric when
     none is given): scores the answer 0-5 against the standard rubric
     below, and separately flags groundedness/hallucination — since most
     answer quality questions ("is this actually grounded in the retrieved
     policy text, not just plausible-sounding?") can't be reduced to a
     substring check.

Scoring rubric (matches the HR-bot accuracy spec this suite was built for):
  5 = Fully correct and grounded
  4 = Correct with minor omission
  3 = Partially correct
  2 = Significant issue
  1 = Mostly incorrect
  0 = Unsupported/hallucinated answer

A case only PASSES overall if the deterministic checks (when present) hold
AND the judge score is >= 4 AND the judge found it grounded.

Usage:
    venv/Scripts/python.exe -m backend.chatbot.eval.run_eval

Writes a Markdown report to backend/chatbot/eval/reports/<timestamp>.md and
prints a summary table to stdout. Exits with status 1 if any case failed
(so this is CI-friendly).
"""
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from backend.chatbot import rag
from backend.chatbot.eval.cases import CASES, TestCase
from backend.chatbot.llm import call_llm

REPORTS_DIR = Path(__file__).parent / "reports"


@dataclass
class CaseResult:
    case: TestCase
    answer: str
    sources: List[str]
    contain_failures: List[str]
    forbidden_hits: List[str]
    judge_score: int          # 0-5, per the rubric above
    judge_correct: bool
    judge_grounded: bool
    judge_hallucination: bool
    judge_reasoning: str
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        return (
            not self.contain_failures
            and not self.forbidden_hits
            and self.judge_score >= 4
            and self.judge_grounded
        )


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Per-bot runners — call the exact same functions the live endpoints use
# ─────────────────────────────────────────────────────────────────────────────

def _run_hr(case: TestCase) -> tuple:
    answer, sources, _from_cache, _follow_ups = rag.answer_query(case.question, [])
    return answer, sources


def _run_rcm(case: TestCase) -> tuple:
    from backend.rcm_chatbot import answer as rcm_answer
    text, sources, _from_cache, _follow_ups = rcm_answer.answer_query(case.question, history=[])
    return text, sources


def _run_library(case: TestCase) -> tuple:
    from backend.library_chatbot import audit_bot
    result = audit_bot.ask_bot(case.question, page=1, page_size=10)
    text = _strip_html(result.get("answer", ""))
    if result.get("intent") == "COUNT":
        text = f"{text} [Result Count: {result.get('total')}]"
    sources = [f"Sr. No. {r['sr_no']}" for r in (result.get("rows") or [])[:5]]
    return text, sources


_RUNNERS = {"hr": _run_hr, "rcm": _run_rcm, "library": _run_library}


# ─────────────────────────────────────────────────────────────────────────────
# LLM judge
# ─────────────────────────────────────────────────────────────────────────────

JUDGE_SYSTEM_PROMPT = (
    "You are a strict QA evaluator for an internal company chatbot's answers. You will be given "
    "a question, the bot's actual answer, and grading notes. Judge ONLY what's asked — do not "
    "penalize style, tone, or brevity unless the notes say completeness matters. Be skeptical of "
    "vague answers that dodge the question, and especially of anything that reads like it's "
    "making up a specific fact (a number, date, designation-specific rule) rather than reporting "
    "one that's actually grounded in evidence the bot would have had.\n\n"
    "Score the answer 0-5 using EXACTLY this rubric:\n"
    "  5 = Fully correct and grounded\n"
    "  4 = Correct with only a minor omission\n"
    "  3 = Partially correct\n"
    "  2 = Significant issue (wrong number/rule, missed a real exception, etc.)\n"
    "  1 = Mostly incorrect\n"
    "  0 = Unsupported/hallucinated answer (invented a fact/number with no real basis)\n\n"
    "Also judge separately:\n"
    "- grounded: could every factual claim plausibly come from a real retrieved policy/knowledge "
    "excerpt, with nothing invented? (A correct 'I don't have that information' IS grounded — "
    "honesty about a gap is not hallucination.)\n"
    "- hallucination_detected: did the answer state a SPECIFIC fact (number, date, rule, "
    "designation-specific detail) that has no real basis, presented with confidence?\n\n"
    "Respond with ONLY a JSON object, no other text, no markdown fences:\n"
    '{"score": 0-5, "correct": true|false, "grounded": true|false, '
    '"hallucination_detected": true|false, "reasoning": "one or two sentences"}'
)


def _judge(case: TestCase, answer: str, ground_truth_ok: bool) -> dict:
    criteria = case.judge_criteria or (
        "General quality bar: the answer must directly address the question, stay grounded in "
        "facts a real internal knowledge base would contain (no invented specifics), and not be "
        "evasive when the information is plausibly available."
    )
    ground_truth_note = (
        "An automated fact-check already confirmed every required piece of content "
        f"({case.must_contain}) IS present in the answer below, and none of the forbidden content "
        f"({case.must_not_contain}) is present. Do NOT lower the score for missing or incomplete "
        "content that was just confirmed present — judge only the criteria above (style, "
        "reasoning, whether it actually answers the question), not content-completeness the "
        "fact-check already settled.\n\n"
        if (case.must_contain or case.must_not_contain) and ground_truth_ok else ""
    )
    user_prompt = (
        f"Question: {case.question}\n\n"
        f"Grading notes (what this case is specifically testing): {case.notes}\n\n"
        f"Pass/fail criteria: {criteria}\n\n"
        f"{ground_truth_note}"
        f"Bot's actual answer:\n{answer}\n\n"
        "Return the JSON verdict now."
    )
    raw = call_llm(
        [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        provider=rag.HR_PROVIDER,
    )
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(json)?", "", raw).rstrip("`").strip()
    try:
        data = json.loads(raw)
        return {
            "score": max(0, min(5, int(data.get("score", 0)))),
            "correct": bool(data.get("correct")),
            "grounded": bool(data.get("grounded", True)),
            "hallucination_detected": bool(data.get("hallucination_detected")),
            "reasoning": str(data.get("reasoning", "")),
        }
    except Exception:
        return {
            "score": 0, "correct": False, "grounded": False, "hallucination_detected": False,
            "reasoning": f"Judge returned unparseable output: {raw[:200]}",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

def run_case(case: TestCase) -> CaseResult:
    try:
        answer, sources = _RUNNERS[case.bot](case)
    except Exception as e:
        return CaseResult(case, "", [], [], [], 0, False, False, False, "", error=f"{type(e).__name__}: {e}")

    lower = answer.lower()
    contain_failures = [kw for kw in case.must_contain if kw.lower() not in lower]
    forbidden_hits = [kw for kw in case.must_not_contain if kw.lower() in lower]
    ground_truth_ok = not contain_failures and not forbidden_hits

    verdict = _judge(case, answer, ground_truth_ok)

    return CaseResult(
        case, answer, sources, contain_failures, forbidden_hits,
        verdict["score"], verdict["correct"], verdict["grounded"], verdict["hallucination_detected"],
        verdict["reasoning"],
    )


def run_all() -> List[CaseResult]:
    results = []
    for i, case in enumerate(CASES, 1):
        print(f"[{i}/{len(CASES)}] ({case.bot}/{case.category}) {case.question!r} ...", flush=True)
        t0 = time.time()
        result = run_case(case)
        dt = time.time() - t0
        status = "PASS" if result.passed else "FAIL"
        print(f"    -> {status} score={result.judge_score}/5 ({dt:.1f}s)", flush=True)
        results.append(result)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate metrics (spec: Answer Accuracy, Groundedness, Hallucination Rate,
# Unknown Question Accuracy, Citation Accuracy) — computed per bot, with HR
# broken down further by category (basic/intermediate/advanced/hallucination/
# security/adversarial).
# ─────────────────────────────────────────────────────────────────────────────

def _pct(n: int, d: int) -> str:
    return f"{(100 * n / d):.0f}%" if d else "n/a"


def compute_metrics(results: List[CaseResult]) -> dict:
    n = len(results)
    if n == 0:
        return {}
    hallucination_cases = [r for r in results if r.case.category == "hallucination"]
    return {
        "n": n,
        "answer_accuracy": _pct(sum(1 for r in results if r.judge_correct), n),
        "groundedness": _pct(sum(1 for r in results if r.judge_grounded), n),
        "hallucination_rate": _pct(sum(1 for r in results if r.judge_hallucination), n),
        "unknown_question_accuracy": (
            _pct(sum(1 for r in hallucination_cases if r.passed), len(hallucination_cases))
            if hallucination_cases else "n/a"
        ),
        "citation_accuracy": _pct(
            sum(1 for r in results if r.sources and r.sources != ["No matching policy section"]), n
        ),
        "avg_score": f"{(sum(r.judge_score for r in results) / n):.1f}/5",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────

def write_report(results: List[CaseResult]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"{stamp}.md"

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    by_bot = {}
    for r in results:
        by_bot.setdefault(r.case.bot, [0, 0])
        by_bot[r.case.bot][1] += 1
        if r.passed:
            by_bot[r.case.bot][0] += 1

    lines = [
        f"# JHS Chatbot Evaluation Report — {stamp}",
        "",
        f"**Overall: {passed}/{total} passed**",
        "",
        "| Bot | Passed |",
        "|---|---|",
    ]
    for bot, (p, t) in sorted(by_bot.items()):
        lines.append(f"| {bot} | {p}/{t} |")
    lines.append("")

    # HR-specific aggregate metrics + per-category breakdown (spec §18).
    hr_results = [r for r in results if r.case.bot == "hr"]
    if hr_results:
        m = compute_metrics(hr_results)
        lines += [
            "## HR bot — aggregate metrics",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Answer Accuracy | {m['answer_accuracy']} |",
            f"| Groundedness | {m['groundedness']} |",
            f"| Hallucination Rate | {m['hallucination_rate']} |",
            f"| Unknown-Question Accuracy | {m['unknown_question_accuracy']} |",
            f"| Citation Accuracy | {m['citation_accuracy']} |",
            f"| Average Score | {m['avg_score']} |",
            "",
            "### By category",
            "",
            "| Category | Passed | Avg Score |",
            "|---|---|---|",
        ]
        by_cat = {}
        for r in hr_results:
            by_cat.setdefault(r.case.category, []).append(r)
        for cat, rs in sorted(by_cat.items()):
            p = sum(1 for r in rs if r.passed)
            avg = sum(r.judge_score for r in rs) / len(rs)
            lines.append(f"| {cat} | {p}/{len(rs)} | {avg:.1f}/5 |")
        lines.append("")

    for i, r in enumerate(results, 1):
        status = "✅ PASS" if r.passed else "❌ FAIL"
        lines.append(f"## {i}. [{r.case.bot}/{r.case.category}] {status}")
        lines.append(f"**Question:** {r.case.question}")
        lines.append(f"**Testing:** {r.case.notes}")
        lines.append("")
        if r.error:
            lines.append(f"**ERROR:** {r.error}")
        else:
            lines.append(f"**Answer:**\n> {r.answer.replace(chr(10), chr(10) + '> ')}")
            lines.append("")
            if r.sources:
                lines.append(f"**Sources:** {', '.join(r.sources)}")
            if r.contain_failures:
                lines.append(f"**Missing required content:** {r.contain_failures}")
            if r.forbidden_hits:
                lines.append(f"**Contains forbidden content:** {r.forbidden_hits}")
            lines.append(
                f"**Judge:** score={r.judge_score}/5, correct={r.judge_correct}, "
                f"grounded={r.judge_grounded}, hallucination_detected={r.judge_hallucination}"
            )
            lines.append(f"**Judge reasoning:** {r.judge_reasoning}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    print(f"Running {len(CASES)} test case(s) across HR / RCM / Library ...\n")
    results = run_all()

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    print(f"\n{'=' * 60}\nRESULT: {passed}/{total} passed\n{'=' * 60}")

    hr_results = [r for r in results if r.case.bot == "hr"]
    if hr_results:
        m = compute_metrics(hr_results)
        print(
            f"HR metrics: accuracy={m['answer_accuracy']} groundedness={m['groundedness']} "
            f"hallucination_rate={m['hallucination_rate']} "
            f"unknown_q_accuracy={m['unknown_question_accuracy']} avg_score={m['avg_score']}"
        )

    for r in results:
        if not r.passed:
            reason = r.error or (
                f"score={r.judge_score}/5 grounded={r.judge_grounded} "
                f"contain_failures={r.contain_failures} forbidden_hits={r.forbidden_hits} "
                f"judge={r.judge_reasoning}"
            )
            print(f"FAIL [{r.case.bot}/{r.case.category}] {r.case.question!r} -> {reason}")

    report_path = write_report(results)
    print(f"\nFull report written to: {report_path}")

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
