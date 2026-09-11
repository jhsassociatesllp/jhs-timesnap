"""All OpenAI calls for the JHS Library bot: question classification, grounded
answers/summaries, and the draft-a-finding copilot. Ported from the standalone
JHS Library project — reads its own OpenAI key from library_settings."""
import json
import logging

from openai import OpenAI

from backend.chatbot import usage
from backend.library_chatbot.config import library_settings

logger = logging.getLogger(__name__)
_openai = OpenAI(api_key=library_settings.OPENAI_API_KEY)
CHAT_MODEL = library_settings.CHAT_MODEL


def _track_usage(response) -> None:
    """Records one LLM call's token usage. Deliberately isolated from the
    caller's own try/except around parsing `response`'s content — that
    block exists to fall back gracefully if the ANSWER is malformed, not to
    silently discard an already-good answer just because `response.usage`
    happened to be missing (some OpenAI-compatible endpoints omit it).
    Never raises."""
    try:
        u = response.usage
        usage.record_call(
            "library", model=CHAT_MODEL,
            prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(u, "completion_tokens", 0) or 0,
        )
    except Exception:
        logger.exception("Failed to record library LLM usage")

HTML_FORMAT_RULES = """
CRITICAL OUTPUT FORMAT — HTML ONLY, NO EXCEPTIONS:
- Your ENTIRE response must be an HTML fragment.
- Wrap every paragraph in <p>...</p>.
- Use <strong>...</strong> for emphasis — NEVER markdown ** or __.
- Use <ul><li>...</li></ul> / <ol><li>...</li></ol> for lists.
- Use <h4>...</h4> for section headings.
- No markdown syntax (#, *, -) anywhere.
- No <html>, <head>, <body>, or <style> wrapper tags.
"""


def classify_question(question: str, facets: dict) -> dict:
    """Extracts an intent plus best-guess (uncanonicalized) filter values.
    The caller resolves each guess against the live facet vocabulary with
    search.fuzzy_match_facet — the model no longer has to know the exact
    canonical spelling, only roughly what the user meant."""
    facet_hint = "\n".join(
        f"- {field}: e.g. {', '.join(values[:12])}" for field, values in facets.items() if values
    )
    system_prompt = f"""You are a question classifier for an audit observation library.

Available filter fields and a sample of their real values (not exhaustive):
{facet_hint}

Return ONLY valid JSON:
{{
  "intent": "COUNT" | "SHOW_ALL" | "SUMMARY" | "BREAKDOWN" | "OUT_OF_SCOPE",
  "filters": {{"sector": "", "audit_type": "", "risk": "", "process_area": "", "risk_theme": "", "coso_component": "", "fs_assertion": "", "fraud_risk_indicator": ""}},
  "group_by": "",
  "keywords": ""
}}

Rules:
- COUNT: user wants ONE number for the whole (filtered) result set.
- SHOW_ALL: user wants to browse/list matching rows.
- SUMMARY: user wants themes/patterns/explanation across matching rows.
- BREAKDOWN: user wants a count SPLIT PER CATEGORY of some field, not one
  total — phrases like "category wise", "risk wise", "by sector", "per audit
  type", "how many of each", "split by", "breakdown by". Set "group_by" to
  the exact field name (sector/audit_type/risk/process_area/risk_theme/
  coso_component/fs_assertion/fraud_risk_indicator) the question wants the
  counts split by — pick the field whose NAME or an obvious synonym is
  actually named in the question (e.g. "risk category wise"/"risk wise" ->
  group_by="risk"; "sector wise" -> group_by="sector"). Still fill "filters"
  too if the question ALSO narrows the scope first (e.g. "in the banking
  sector, how many of each risk level" -> filters={{"sector":"Banking"}},
  group_by="risk"). Never use COUNT when the question asks for a per-category
  split — that silently collapses the exact breakdown the user asked for
  into one meaningless total.
- OUT_OF_SCOPE: the question is about a completely different domain that has
  nothing to do with audits, findings, risks, controls, or business/compliance
  topics at all — general trivia, geography, math, poems, coding help, or
  casual conversation (e.g. "what is the capital of France?", "write me a
  poem"). Do NOT use OUT_OF_SCOPE just because a topic isn't in the sample
  facet values shown above — that list is only a partial preview, not the
  full vocabulary. A genuine audit/finding/risk/root-cause question about ANY
  business topic (even one not shown in the samples, e.g. "inventory",
  "payroll", "vendor onboarding") is still in-scope — classify it normally
  (COUNT/SHOW_ALL/SUMMARY) like any other. Only use OUT_OF_SCOPE when the
  question itself is unambiguously not about audits/findings/risk/compliance
  at all.
- Fill a filter only if the question clearly implies it — your guess does not
  need to exactly match the sample spelling, just be close in meaning.
- "keywords" = free-text search terms for anything not covered by a filter
  (e.g. "GST mismatch", "stockout"). Leave blank if the question is fully
  covered by filters.
- Do not invent values that aren't implied by the question."""

    try:
        response = _openai.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        )
        _track_usage(response)
        result = json.loads(response.choices[0].message.content)
        result.setdefault("filters", {})
        result.setdefault("keywords", "")
        result.setdefault("group_by", "")
        result.setdefault("intent", "SHOW_ALL")
        return result
    except Exception as e:
        logger.error(f"classify_question failed: {e}")
        return {"intent": "SHOW_ALL", "filters": {}, "group_by": "", "keywords": question}


def generate_answer(question: str, intent: str, filters: dict, count: int, sample_sr_nos: list) -> str:
    prompt = f"""You are an assistant for an audit observation library.
{HTML_FORMAT_RULES}
Answer the user's question clearly and thoroughly — state the headline fact first, then explain
what it means in context (which filters narrowed it, what that implies, anything the user should
know before acting on the number). Typically 2-5 sentences; more if the question genuinely has
several parts. Prioritize accuracy and completeness over brevity, but don't pad with filler.
Use ONLY the Result Count and Applied Filters given below — do not recompute or guess numbers.
Do NOT cite Sr. No. references in your answer — no "(Sr. No. X)" mentions anywhere.

User Question: {question}
Intent: {intent}
Applied Filters: {filters}
Result Count: {count}

Respond now using HTML only."""
    try:
        response = _openai.chat.completions.create(
            model=CHAT_MODEL, temperature=0.3, messages=[{"role": "user", "content": prompt}]
        )
        _track_usage(response)
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"generate_answer failed: {e}")
        return f"<p>Found <strong>{count}</strong> observations matching your query.</p>"


def generate_breakdown_answer(question: str, group_by_label: str, breakdown: list, filters: dict) -> str:
    """breakdown: [{"value": ..., "count": ...}, ...] — the EXACT,
    already-computed counts (see data_access.get_breakdown). Renders the
    per-category list deterministically in Python rather than asking the
    LLM to restate the numbers — with several counts in one answer instead
    of just one, the risk of the model mistyping/rounding/dropping a row
    compounds, so it only ever writes a short framing sentence around
    numbers it never actually has to reproduce."""
    total = sum(b["count"] for b in breakdown)
    list_html = "<ul>" + "".join(
        f"<li><strong>{b['value']}</strong>: {b['count']}</li>" for b in breakdown
    ) + "</ul>"

    prompt = f"""You are an assistant for an audit observation library.
Write ONE short introductory sentence (as a single <p> tag, HTML only, no markdown) framing a
breakdown of observation counts by {group_by_label} that will be shown right after your sentence
as a separate list — do NOT restate the individual category numbers yourself, only mention the
overall total below and, if any filters were applied, what they were.

User Question: {question}
Grouped by: {group_by_label}
Applied Filters: {filters}
Total: {total}

Respond with ONLY the one <p> sentence, HTML only."""
    try:
        response = _openai.chat.completions.create(
            model=CHAT_MODEL, temperature=0.3, messages=[{"role": "user", "content": prompt}]
        )
        _track_usage(response)
        intro = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"generate_breakdown_answer failed: {e}")
        intro = f"<p>Here's the breakdown by {group_by_label} (total: <strong>{total}</strong>):</p>"

    return intro + list_html


def generate_summary(question: str, rows: list) -> str:
    context = "\n".join(
        f"- Sr. No. {r.get('sr_no')}: {r.get('headline','')}\n"
        f"  Sector: {r.get('sector','')} | Audit Type: {r.get('audit_type','')} | Risk: {r.get('risk','')}\n"
        f"  Observation: {r.get('observation','')}\n"
        f"  Root Cause: {r.get('root_cause','')}\n"
        f"  Recommendation: {r.get('recommendation','')}"
        for r in rows[:25]
    )
    prompt = f"""You are an audit assistant. {HTML_FORMAT_RULES}

STRICT RULES:
- Use ONLY the observations listed below — do not invent numbers, percentages, or regulations.
- Do NOT cite Sr. No. references anywhere in your answer — no "(Sr. No. X)" mentions. Ground every
  claim in the observations below without naming which row it came from.
- Be thorough: scan every observation listed below, not just the first few — surface every
  distinct recurring theme or control weakness you can actually find grounded in them, not just
  the single most obvious one. A pattern shared by only two observations is still worth a
  sentence if it's real; don't drop it for the sake of brevity.

Structure your response with exactly these <h4> sections: Recurring Themes, Common Control Weaknesses, Risk Implications.

Question: {question}

Observations:
{context}

Respond now using HTML only."""
    try:
        response = _openai.chat.completions.create(
            model=CHAT_MODEL, temperature=0.2, messages=[{"role": "user", "content": prompt}]
        )
        _track_usage(response)
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"generate_summary failed: {e}")
        return "<p>Unable to generate summary. Please try again.</p>"


def generate_draft(sector: str, process_area: str, description: str, grounding_rows: list) -> dict:
    """Drafts an editable finding skeleton grounded in similar historical
    observations. Nothing is written back to the library — this is a
    scratch suggestion for the auditor to edit and use."""
    context = "\n".join(
        f"- Sr. No. {r.get('sr_no')} [{r.get('sector','')} / {r.get('process_area','')}]\n"
        f"  Headline: {r.get('headline','')}\n"
        f"  Observation: {r.get('observation','')}\n"
        f"  Root Cause: {r.get('root_cause','')}\n"
        f"  Recommendation: {r.get('recommendation','')}\n"
        f"  Management Action Plan: {r.get('management_action','')}"
        for r in grounding_rows
    )
    prompt = f"""You are drafting a FIRST DRAFT of a new audit finding for a human auditor to review and edit.
Ground your language and structure in the similar historical findings provided below — match their tone,
specificity, and level of detail. Do not fabricate numbers or facts that aren't plausible given the context.

New finding context:
- Sector: {sector}
- Process Area: {process_area}
- Auditor's description: {description}

Similar historical findings for grounding:
{context if context else "(none found — draft from the sector/process area/description alone, keep it generic)"}

Return ONLY valid JSON:
{{
  "headline": "short finding title",
  "observation": "the finding narrative",
  "root_cause": "why it happened",
  "recommendation": "proposed fix",
  "management_action": "suggested action plan language",
  "grounded_on": [list of Sr. No. integers actually used for grounding]
}}"""
    try:
        response = _openai.chat.completions.create(
            model=CHAT_MODEL,
            temperature=0.4,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        _track_usage(response)
        draft = json.loads(response.choices[0].message.content)
        draft.setdefault("grounded_on", [r["sr_no"] for r in grounding_rows])
        return draft
    except Exception as e:
        logger.error(f"generate_draft failed: {e}")
        return {
            "headline": "", "observation": "", "root_cause": "",
            "recommendation": "", "management_action": "",
            "grounded_on": [], "error": "Draft generation failed, please try again.",
        }
