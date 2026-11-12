# backend/resume_ranker/roles.py
"""
"Where could this person go?" — recommends JHS departments for a parsed CV.

Plain keyword scoring over fields the parser already extracted (skills, job titles,
certifications, education, summaries). No extra AI call, so it costs nothing and can
be re-run on every CV at any time. Each department lists weighted keywords; a keyword
counts more when it appears in a job title than in a skill, and more in a skill than in
free text. The result is stored on the resume and shown as tags.
"""
from __future__ import annotations

import re

# weight 3 = defining keyword, 2 = strong signal, 1 = supporting signal
DEPARTMENTS: dict[str, dict[str, int]] = {
    "Audit & Assurance": {
        "audit": 3, "internal audit": 3, "statutory audit": 3, "concurrent audit": 3, "tax audit": 3,
        "system audit": 3, "forensic": 2, "assurance": 3, "auditor": 3, "audit executive": 3,
        "article assistant": 2, "chartered accountant": 2, "icai": 2, "ca": 2, "sox": 2,
        "internal controls": 2, "risk based audit": 2, "stock audit": 2, "bank audit": 2,
        "working papers": 1, "vouching": 1, "ifc": 1,
    },
    "Accounts & Finance": {
        "accounting": 3, "accounts": 2, "bookkeeping": 3, "tally": 3, "sap fico": 3, "sap": 1,
        "accounts payable": 3, "accounts receivable": 3, "reconciliation": 2, "financial reporting": 3,
        "financial statements": 2, "ledger": 2, "general ledger": 3, "mis": 1, "budgeting": 2,
        "fp&a": 3, "financial analysis": 2, "treasury": 2, "cash flow": 1, "finance": 2,
        "b.com": 1, "m.com": 1, "mba finance": 2, "month end close": 2, "journal entries": 2,
        "quickbooks": 2, "zoho books": 2, "busy": 1,
    },
    "Taxation & Compliance": {
        "gst": 3, "income tax": 3, "tds": 3, "itr": 3, "taxation": 3, "direct tax": 3, "indirect tax": 3,
        "transfer pricing": 3, "roc": 2, "companies act": 3, "compliance": 2, "statutory compliance": 3,
        "tax": 2, "return filing": 2, "tax planning": 2, "company secretary": 2, "fema": 2, "rbi": 1,
    },
    "Human Resources": {
        "human resources": 3, "hr": 3, "recruitment": 3, "talent acquisition": 3, "sourcing": 2,
        "onboarding": 3, "employee engagement": 3, "hrms": 2, "performance management": 2,
        "hr operations": 3, "training and development": 3, "learning and development": 3,
        "payroll": 3, "attendance": 1, "employee relations": 3, "hr policies": 3, "induction": 1,
        "interviewing": 2, "mba hr": 3, "exit formalities": 2, "pf": 1, "esi": 1, "statutory benefits": 2,
    },
    "Data Analytics": {
        "data analysis": 3, "data analytics": 3, "data analyst": 3, "python": 2, "sql": 3, "power bi": 3,
        "tableau": 3, "pandas": 3, "numpy": 2, "statistics": 2, "dashboard": 2, "dashboards": 2,
        "data visualization": 3, "machine learning": 3, "data science": 3, "etl": 2, "power query": 3,
        "business intelligence": 3, "alteryx": 3, "excel": 1, "advanced excel": 2, "vba": 2, "r": 1,
        "mysql": 2, "postgresql": 2, "data cleaning": 2, "data modelling": 2, "looker": 2, "dax": 3,
    },
    "IT & Software": {
        "java": 3, "javascript": 3, "typescript": 3, "react": 3, "reactjs": 3, "node": 2, "nodejs": 2,
        "c#": 3, ".net": 3, "asp.net": 3, "php": 3, "html": 1, "css": 1, "devops": 3, "docker": 2,
        "kubernetes": 2, "aws": 2, "azure": 2, "linux": 2, "networking": 2, "system administration": 3,
        "it support": 3, "software development": 3, "software engineer": 3, "web development": 3,
        "cybersecurity": 3, "network security": 3, "api": 1, "git": 1, "fastapi": 2, "django": 3,
        "flask": 2, "mongodb": 1, "helpdesk": 2, "hardware": 1,
    },
    "Consulting & Risk Advisory": {
        "consulting": 3, "advisory": 3, "risk advisory": 3, "risk management": 3, "business analysis": 3,
        "business analyst": 3, "process improvement": 3, "due diligence": 3, "valuation": 3,
        "erp implementation": 3, "grc": 3, "iso 27001": 3, "internal financial controls": 3,
        "process mapping": 2, "sop": 1, "governance": 2, "project management": 2, "pmp": 2,
        "business process": 2, "feasibility": 1, "financial modelling": 3, "market entry": 1,
    },
    "Business Development & Marketing": {
        "business development": 3, "sales": 3, "lead generation": 3, "client relationship": 2,
        "relationship management": 2, "marketing": 3, "digital marketing": 3, "seo": 3, "crm": 2,
        "proposals": 2, "cold calling": 3, "client acquisition": 3, "social media": 2, "branding": 2,
        "negotiation": 1, "account management": 2, "campaign": 2, "content marketing": 3, "bd": 2,
    },
    "Research & Knowledge": {
        "research": 3, "market research": 3, "knowledge management": 3, "content writing": 3,
        "report writing": 3, "technical writing": 3, "publication": 2, "editing": 2, "analysis": 1,
        "secondary research": 3, "literature review": 3, "copywriting": 3, "proofreading": 2,
        "policy research": 3, "benchmarking": 2, "newsletter": 2,
    },
}

# Too short / ambiguous to find in free text: only count when a skill, certification or
# degree is exactly this word (e.g. the certification "CA"), never inside a sentence.
EXACT_ONLY = {"ca", "r", "bd", "pf", "esi", "ifc", "sap", "api", "css", "html", "git", "busy", "sop", "mis", "roc", "itr"}

# a keyword is worth more the more deliberate the place it was found
SOURCE_MULT = {"title": 1.6, "skill": 1.0, "cert": 1.2, "edu": 1.0, "text": 0.5}
FIT_LEVELS = (("Strong", 60.0), ("Good", 35.0), ("Possible", 20.0))
NORMALISER = 12.0          # raw points that equal a 100% fit
MAX_ROLES = 3


def _pattern(term: str) -> re.Pattern:
    # lookarounds, not \b, so "c#", ".net", "fp&a" and "b.com" still match
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)


_PATTERNS = {kw: _pattern(kw) for kws in DEPARTMENTS.values() for kw in kws}


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def _sources(parsed: dict) -> dict[str, list[str]]:
    exp = parsed.get("experience") or []
    titles = [_norm(e.get("title")) for e in exp if e.get("title")]
    if parsed.get("headline"):
        titles.append(_norm(parsed["headline"]))
    edu = [_norm(" ".join(str(e.get(k) or "") for k in ("degree", "field"))) for e in parsed.get("education") or []]
    text = [_norm(e.get("summary")) for e in exp if e.get("summary")]
    text += [_norm(e.get("industry")) for e in exp if e.get("industry")]
    text += [_norm(i) for i in parsed.get("industries") or []]
    text += [_norm(a) for a in parsed.get("achievements") or []]
    return {
        "title": [t for t in titles if t],
        "skill": [_norm(s) for s in parsed.get("skills") or [] if s],
        "cert": [_norm(c) for c in parsed.get("certifications") or [] if c],
        "edu": [e for e in edu if e],
        "text": [t for t in text if t],
    }


def recommend_roles(parsed: dict | None) -> list[dict]:
    """Up to 3 departments this CV fits, best first:
    [{"department", "fit": "Strong"|"Good"|"Possible", "score": 0-100, "reasons": [keywords]}]"""
    if not parsed:
        return []
    src = _sources(parsed)
    results = []
    for dept, keywords in DEPARTMENTS.items():
        raw, hits = 0.0, []
        for kw, weight in keywords.items():
            best = 0.0
            for source, items in src.items():
                if kw in EXACT_ONLY:
                    found = source in ("skill", "cert", "edu") and any(i == kw for i in items)
                else:
                    pat = _PATTERNS[kw]
                    found = any(pat.search(i) for i in items)
                if found:
                    best = max(best, weight * SOURCE_MULT[source])
            if best:
                raw += best
                hits.append((best, kw))
        score = round(min(raw / NORMALISER * 100.0, 100.0), 1)
        fit = next((name for name, floor in FIT_LEVELS if score >= floor), None)
        if fit:
            hits.sort(reverse=True)
            results.append({"department": dept, "fit": fit, "score": score,
                            "reasons": [kw for _, kw in hits[:4]]})
    results.sort(key=lambda r: -r["score"])
    return results[:MAX_ROLES]
