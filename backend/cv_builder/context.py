# backend/cv_builder/context.py
"""
Turns a stored CV profile into the plain values the profile slide uses
(see ppt_profile.py): qualifications, memberships, sectors, areas of expertise
(each with its detail lines) and the framework / tool chips.
"""

import re
from typing import List

MAX_AREAS = 4
MAX_AREA_LINES = 3


def _lines(text) -> List[str]:
    out = []
    for ln in re.split(r"[\r\n]+", str(text or "")):
        ln = ln.strip().lstrip("•●▪◆-*–— \t").strip()
        if ln:
            out.append(ln)
    return out


def build_context(profile: dict, emp_name: str = "") -> dict:
    qd = profile.get("qualification_details") or {}
    quals = []
    for q in profile.get("qualification") or []:
        det = qd.get(q) or {}
        quals.append({"code": q, "institute": (det.get("institute") or "").strip()})

    mems = [m for m in (profile.get("membership") or []) if m]

    areas = []
    for a in profile.get("expertise_areas") or []:
        name = (a.get("area") or "").strip()
        if not name:
            continue
        details = [d.strip() for d in (a.get("details") or []) if (d or "").strip()]
        areas.append({"area": name, "details": details[:MAX_AREA_LINES]})
    areas = areas[:MAX_AREAS]

    used = {a["area"].lower() for a in areas}
    frameworks = [s for s in (profile.get("skills_expertise") or []) if s and s.lower() not in used]
    sectors = [s.get("sector") if isinstance(s, dict) else str(s) for s in (profile.get("sector_experience") or [])]

    return {
        "name": (profile.get("employee_name") or emp_name or "").strip(),
        "empid": profile.get("empid", ""),
        "designation": (profile.get("designation") or "").strip(),
        "department": (profile.get("department") or "").strip(),
        "email": (profile.get("email") or "").strip(),
        "phone": (profile.get("phone") or "").strip(),
        "location": (profile.get("location") or "").strip(),
        "summary": (profile.get("summary") or "").strip(),
        "sectors": [s for s in sectors if s],
        "quals": quals, "mems": mems,
        "areas": areas, "frameworks": frameworks,
    }
