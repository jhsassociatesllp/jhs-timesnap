"""
Conservative data cleaning for the JHS observation library.

Scope, deliberately narrow: fix formatting noise (whitespace, stray casing)
and collapse only the handful of cases where two literal values in the
source file are unambiguously the same concept at different verbosity
(e.g. "Internal" vs "Internal Audit"). Nothing here reclassifies, merges
ambiguous near-duplicates (e.g. "Banking" vs "Financial Services - Banking"),
or derives any new field that isn't already a column in the source file.

Ported unchanged from the standalone JHS Library project.
"""

# Source column -> DB field name, in source-file order.
COLUMN_MAP = {
    "Sr. No.": "sr_no",
    "Headline": "headline",
    "Observation": "observation",
    "Risk": "risk",
    "Root Cause": "root_cause",
    "Recommendation": "recommendation",
    "Management Action Plan": "management_action",
    "Sector": "sector",
    "Audit Type": "audit_type",
    "Financial Caption Bucket": "financial_caption_bucket",
    "Process Area": "process_area",
    "Root Cause Category": "root_cause_category",
    "Risk Theme": "risk_theme",
    "Financial Statement Caption": "financial_statement_caption",
    "IFC Control Objective": "ifc_control_objective",
    "COSO Component": "coso_component",
    "Fraud Risk Indicator": "fraud_risk_indicator",
    "FS Assertion": "fs_assertion",
}

# Free-text narrative fields — embedded and full-text searched, never merged.
TEXT_FIELDS = [
    "headline", "observation", "root_cause", "recommendation", "management_action",
]

# Fields exposed as facets in /facets and /observations. Everything else in
# COLUMN_MAP is trimmed but left as detail-only (e.g. root_cause_category is
# ~1,295 near-unique free text, unusable as a filter without reclassifying it,
# which is out of scope).
FACET_FIELDS = [
    "sector", "audit_type", "risk", "process_area",
    "risk_theme", "coso_component", "fs_assertion", "fraud_risk_indicator",
]

# Explicit, reviewable verbosity merges — same concept, different verbosity,
# both literally present in the source data. Everything not listed here is
# left exactly as it appears in the source file (after whitespace trimming).
AUDIT_TYPE_MERGE = {
    "internal": "Internal Audit",
    "concurrent": "Concurrent Audit",
    "statutory": "Statutory Audit",
}
SECTOR_MERGE = {
    "it": "Information Technology",
}

# Severity ordering for default result sort — higher first. Derived purely
# from the existing Risk values, nothing invented.
RISK_SEVERITY_ORDER = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
    "Improvement Opportunity": 4,
    "N.A.": 5,
}


def _clean_str(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if s.lower() in ("nan", "none"):
        return ""
    # collapse internal runs of whitespace from wrapped Excel cells
    return " ".join(s.split())


def normalize_row(raw: dict) -> dict:
    """raw: a dict keyed by the original Excel column names (one pandas row)."""
    row = {}
    for src_col, field in COLUMN_MAP.items():
        row[field] = _clean_str(raw.get(src_col))

    row["sr_no"] = int(raw["Sr. No."])

    # Risk: trim/normalize casing only, keep all 6 distinct existing values.
    if row["risk"]:
        row["risk"] = row["risk"].strip()
        # canonical-case match against the known literal set so e.g. "high"
        # or "HIGH" (if it ever occurs) lines up with "High" for the facet list
        for canon in RISK_SEVERITY_ORDER:
            if row["risk"].lower() == canon.lower():
                row["risk"] = canon
                break

    # Audit Type: collapse the three verbosity duplicates only.
    key = row["audit_type"].lower()
    if key in AUDIT_TYPE_MERGE:
        row["audit_type"] = AUDIT_TYPE_MERGE[key]

    # Sector: expand the one unambiguous abbreviation only.
    key = row["sector"].lower()
    if key in SECTOR_MERGE:
        row["sector"] = SECTOR_MERGE[key]

    return row


def embedding_text(row: dict) -> str:
    """Wider grounding context than the old 4-field blob, still only the
    row's own existing text — used for both semantic search and the
    draft-a-finding copilot's retrieval step."""
    parts = [
        f"Headline: {row.get('headline', '')}",
        f"Sector: {row.get('sector', '')}",
        f"Audit Type: {row.get('audit_type', '')}",
        f"Process Area: {row.get('process_area', '')}",
        f"Risk Theme: {row.get('risk_theme', '')}",
        f"Observation: {row.get('observation', '')}",
        f"Root Cause: {row.get('root_cause', '')}",
        f"Recommendation: {row.get('recommendation', '')}",
        f"Management Action Plan: {row.get('management_action', '')}",
        f"IFC Control Objective: {row.get('ifc_control_objective', '')}",
    ]
    return "\n".join(p for p in parts if p.split(": ", 1)[-1])
