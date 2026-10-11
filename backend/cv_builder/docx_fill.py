# backend/cv_builder/docx_fill.py
"""
Fills the five Word CV templates (backend/cv_builder/templates/*.docx) with an
employee's profile + experience. The templates carry sample data and no
placeholders, so each template has a small filler that finds sections by their
headings, keeps the original run/paragraph formatting, and clones paragraphs,
rows or blocks to fit however many items the employee has.
"""

import copy
import os
import re
from datetime import date, datetime
from io import BytesIO
from typing import List, Optional

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

TEMPLATE_FILES = {
    "1": "CV_Template_1_Executive_Sidebar_1.docx",
    "2": "CV_Template_2_Classic_Corporate_1.docx",
    "3": "CV_Template_3_Modern_Banner_1.docx",
    "4": "CV_Template_4_Timeline_1.docx",
    "5": "CV_Template_5_Proposal_Profile_1.docx",
}

QUAL_NAMES = {
    "CA": "Chartered Accountant (CA)",
    "ACCA": "Association of Chartered Certified Accountants (ACCA)",
    "CMA": "Cost & Management Accountant (CMA)",
    "CPA": "Certified Public Accountant (CPA)",
    "CFA": "Chartered Financial Analyst (CFA)",
    "MBA": "Master of Business Administration (MBA)",
    "M.Com": "Master of Commerce (M.Com)",
    "B.Com": "Bachelor of Commerce (B.Com)",
    "BBA": "Bachelor of Business Administration (BBA)",
    "B.Tech": "Bachelor of Technology (B.Tech)",
    "M.Tech": "Master of Technology (M.Tech)",
    "BAF": "Bachelor of Accounting & Finance (BAF)",
    "BSc": "Bachelor of Science (BSc)",
    "MSc": "Master of Science (MSc)",
}

TOOLS = {"Tally Prime", "SAP", "Oracle ERP", "ERPNext", "Advanced Excel",
         "Power Query", "Power BI", "SQL", "Python"}

# Sections a user can show / hide / rename per template: (key, heading text in the
# template, None = no heading of its own). Keys are shared across templates so a
# user's choices carry over when they switch template.
SECTIONS = {
    "1": [("summary", "Professional Summary"), ("expertise", "Key Areas of Expertise"), ("sectors", "Sector Experience"),
          ("education", "Qualifications"), ("memberships", "Memberships"), ("other_skills", "Additional Skills"),
          ("certifications", "Certifications"), ("achievements", "Achievements & Awards"),
          ("assignments", "Key Assignments Handled")],
    "2": [("summary", "PROFILE"), ("expertise", "AREAS OF EXPERTISE"), ("sectors", "SECTOR EXPERIENCE"),
          ("education", "EDUCATION"), ("memberships", None), ("other_skills", "ADDITIONAL SKILLS"),
          ("assignments", "KEY ASSIGNMENTS"),
          ("certifications", "CERTIFICATIONS"), ("achievements", "ACHIEVEMENTS & AWARDS")],
    "3": [("summary", "ABOUT"), ("expertise", "PROFICIENCY"), ("sectors", "SECTOR EXPERIENCE"),
          ("education", "QUALIFICATIONS & MEMBERSHIPS"), ("memberships", None), ("other_skills", "OTHER SKILLS"),
          ("certifications", "CERTIFICATIONS"), ("achievements", "ACHIEVEMENTS & AWARDS"),
          ("assignments", "KEY ASSIGNMENTS")],
    "4": [("summary", "PROFILE"), ("expertise", "CORE EXPERTISE"), ("sectors", "SECTORS"), ("education", "EDUCATION"),
          ("memberships", "MEMBERSHIPS"), ("other_skills", "OTHER SKILLS"), ("certifications", "CERTIFICATIONS"),
          ("achievements", "ACHIEVEMENTS"), ("assignments", "KEY ASSIGNMENTS")],
    "5": [("summary", "Professional Summary"), ("expertise", "Key Skills to Highlight"), ("sectors", "Sector Experience"),
          ("other_skills", "Other Skills & Tools"), ("certifications", "Certifications"),
          ("achievements", "Achievements & Awards"), ("assignments", "Relevant Assignments")],
}

SECTION_LABELS = {
    "summary": "Summary", "expertise": "Key skills / expertise", "sectors": "Sector experience",
    "education": "Education / qualifications", "memberships": "Professional memberships",
    "other_skills": "Other skills & tools", "certifications": "Certifications",
    "achievements": "Achievements & awards",
    "assignments": "Key assignments",
}


def section_spec(template_id: str):
    return [{"key": k, "label": SECTION_LABELS[k], "title": t, "editable": t is not None}
            for k, t in SECTIONS.get(template_id, [])]


P_TAG, TBL_TAG, TC_TAG, TR_TAG = qn("w:p"), qn("w:tbl"), qn("w:tc"), qn("w:tr")


# ═════════════════════════════════════════════════════════════════════════════
#  Context preparation
# ═════════════════════════════════════════════════════════════════════════════
def _lines(text) -> List[str]:
    out = []
    for ln in str(text or "").replace("\r", "\n").split("\n"):
        ln = ln.strip().lstrip("•●▪◆-*–— \t").strip()
        if ln:
            out.append(ln)
    return out


def _parse(d: str) -> Optional[date]:
    try:
        return date.fromisoformat(d)
    except Exception:
        return None


def _mon(d: str) -> str:
    dt = _parse(d)
    return dt.strftime("%b %Y") if dt else (d or "")


def _years_between(a: str, b: str) -> str:
    da = _parse(a)
    if not da:
        return ""
    db = _parse(b) or date.today()
    yrs = round(max((db - da).days, 0) / 365.25, 2)
    return ("%g" % yrs)


def build_context(profile: dict, experiences: List[dict], emp_name: str = "", template_id: str = "") -> dict:
    skills = [s for s in (profile.get("skills_expertise") or []) if s]
    key = [s for s in (profile.get("key_skills") or []) if s in skills] or skills[:6]
    rest = [s for s in skills if s not in key]
    tools = [s for s in rest if s in TOOLS]
    other = [s for s in rest if s not in TOOLS]

    qd = profile.get("qualification_details") or {}
    quals = []
    for q in profile.get("qualification") or []:
        det = qd.get(q) or {}
        quals.append({
            "code": q,
            "name": QUAL_NAMES.get(q, q),
            "institute": (det.get("institute") or "").strip(),
            "year": (det.get("year") or "").strip(),
        })

    md = profile.get("membership_details") or {}
    mems = []
    for i, m in enumerate(profile.get("membership") or []):
        det = md.get(m) or {}
        number = (det.get("number") or "").strip()      # the number is entered against each membership
        mems.append({"name": m, "level": (det.get("level") or "").strip(), "number": number})

    exps = []
    for e in experiences or []:
        yrs = (e.get("experience_years") or "").strip() or _years_between(e.get("from_date", ""), e.get("to_date", ""))
        exps.append({
            "employer": e.get("employer", ""),
            "designation": e.get("designation", ""),
            "from": _mon(e.get("from_date", "")),
            "to": _mon(e.get("to_date", "")) if e.get("to_date") else "Present",
            "years": yrs,
            "bullets": _lines(e.get("responsibilities")),
            "_sort": e.get("from_date") or "",
        })
    exps.sort(key=lambda x: x["_sort"], reverse=True)

    name = (profile.get("employee_name") or emp_name or "").strip()
    exp_total = str(profile.get("total_experience") or "").strip()
    sectors = [s.get("sector") if isinstance(s, dict) else str(s) for s in (profile.get("sector_experience") or [])]

    ctx = {
        "name": name,
        "empid": profile.get("empid", ""),
        "designation": (profile.get("designation") or "").strip(),
        "department": (profile.get("department") or "").strip(),
        "email": (profile.get("email") or "").strip(),
        "phone": (profile.get("phone") or "").strip(),
        "location": (profile.get("location") or "").strip(),
        "linkedin": (profile.get("linkedin") or "").strip(),
        "portfolio": (profile.get("portfolio") or "").strip(),
        "layout": "1" if str(profile.get("page_layout") or "2") == "1" else "2",
        "summary": (profile.get("summary") or "").strip(),
        "exp_total": exp_total,
        "exp_text": (exp_total + " Years") if exp_total else "",
        "key_skills": key, "other_skills": other, "tools": tools, "all_other": rest,
        "sectors": [s for s in sectors if s],
        "quals": quals, "mems": mems,
        "certs": _lines(profile.get("certifications")),
        "achievements": _lines(profile.get("achievements")),
        "experiences": [],              # work experience was removed from the CV builder
        "assignments": [a for a in (profile.get("key_assignments") or [])
                        if any((a.get(k) or "").strip() for k in ("assignment", "client", "sector", "role"))],
    }

    # user's section choices (only keys this template actually has are honoured)
    cfg = profile.get("section_config") or {}
    spec = dict(SECTIONS.get(template_id, []))
    hidden = {k for k in (cfg.get("hidden") or []) if k in spec}
    wipe = {
        "summary": {"summary": ""}, "expertise": {"key_skills": []}, "sectors": {"sectors": []},
        "education": {"quals": []}, "memberships": {"mems": []},
        "other_skills": {"other_skills": [], "tools": [], "all_other": []},
        "certifications": {"certs": []}, "achievements": {"achievements": []},
        "assignments": {"assignments": []},
    }
    for k in hidden:
        ctx.update(wipe[k])
    ctx["titles"] = {k: (v or "").strip() for k, v in (cfg.get("titles") or {}).items()
                     if k in spec and spec[k] and (v or "").strip()}
    ctx["custom"] = []
    for sec in cfg.get("custom") or []:
        if sec.get("visible", True) is False:
            continue
        lines = _lines(sec.get("text"))
        title = (sec.get("title") or "").strip()
        if lines or title:
            ctx["custom"].append({"title": title or "Additional Information", "lines": lines})
    return ctx


def li_text(c):
    return f"LinkedIn: {c['linkedin']}" if c["linkedin"] else ""


def pf_text(c):
    return f"Portfolio: {c['portfolio']}" if c["portfolio"] else ""


def drop_cells(table_el, drop):
    """Remove columns `drop` (indexes) from a one-row table and re-spread the
    remaining widths so the table keeps its full width."""
    grid = table_el.find(qn("w:tblGrid"))
    cols = list(grid)
    tr = [r for r in table_el if r.tag == TR_TAG][0]
    tcs = [x for x in tr if x.tag == TC_TAG]
    keep = [i for i in range(len(tcs)) if i not in drop]
    if not keep:
        remove(table_el)
        return
    if len(keep) == len(tcs):
        return
    widths = [int(g.get(qn("w:w"))) for g in cols]
    total, kept = sum(widths), sum(widths[i] for i in keep)
    for i in sorted(drop, reverse=True):
        remove(tcs[i])
        grid.remove(cols[i])
    for g, tc, i in zip(list(grid), [x for x in tr if x.tag == TC_TAG], keep):
        w = str(int(widths[i] * total / kept))
        g.set(qn("w:w"), w)
        tcw = tc.find(".//" + qn("w:tcW"))
        if tcw is not None:
            tcw.set(qn("w:w"), w)


def _title_line(c, sep):
    return sep.join(x for x in (c["designation"], c["department"]) if x)


def _join(items, sep):
    return sep.join(i for i in items if i)


# ═════════════════════════════════════════════════════════════════════════════
#  Low-level helpers (all operate on lxml elements so structure is preserved)
# ═════════════════════════════════════════════════════════════════════════════
def par(el) -> Paragraph:
    return Paragraph(el, None)


def tbl(el) -> Table:
    return Table(el, None)


def kids(container):
    """Direct paragraph/table children of a body / cell / element."""
    return [c for c in container if c.tag in (P_TAG, TBL_TAG)]


def ptext(el) -> str:
    return par(el).text if el.tag == P_TAG else ""


def set_runs(el, *texts):
    """Set text per run, keeping run formatting; surplus runs are blanked."""
    runs = par(el).runs
    if not runs:
        if texts and texts[0]:
            par(el).add_run(texts[0])
        return
    for i, r in enumerate(runs):
        r.text = texts[i] if i < len(texts) else ""


def set_last_run(el, text):
    runs = par(el).runs
    if runs:
        runs[-1].text = text


def set_alternating(el, items, sep):
    """Paragraph made of item run, separator run, item run, ... (template 4)."""
    p = par(el)
    runs = p.runs
    if len(runs) < 2:
        set_runs(el, sep.join(items))
        return
    item_r, sep_r = copy.deepcopy(runs[0]._r), copy.deepcopy(runs[1]._r)
    for r in runs:
        r._r.getparent().remove(r._r)
    for i, it in enumerate(items):
        if i:
            s = copy.deepcopy(sep_r)
            p._p.append(s)
            from docx.text.run import Run
            Run(s, p).text = sep
        r = copy.deepcopy(item_r)
        p._p.append(r)
        from docx.text.run import Run
        Run(r, p).text = it


def clone_after(el, anchor):
    new = copy.deepcopy(el)
    anchor.addnext(new)
    return new


def remove(*els):
    for e in els:
        if e is not None and e.getparent() is not None:
            e.getparent().remove(e)


def find_par(container, text, start=0):
    for c in kids(container)[start:]:
        if c.tag == P_TAG and text in ptext(c):
            return c
    return None


def find_tbl_with(container, text):
    """Top-level table in container whose text contains `text`."""
    for c in kids(container):
        if c.tag == TBL_TAG and text in "".join(t.text for t in c.iter(qn("w:t")) if t.text):
            return c
    return None


def next_of(el, tag):
    n = el.getnext()
    while n is not None and n.tag != tag:
        n = n.getnext()
    return n


def cell_el(table_el, r, c):
    return tbl(table_el).cell(r, c)._tc


def region(container, start_el, end_el=None):
    """Elements strictly between start_el and end_el (or to end of container)."""
    out, n = [], start_el.getnext()
    while n is not None and n is not end_el:
        if n.tag in (P_TAG, TBL_TAG):
            out.append(n)
        n = n.getnext()
    return out


def fill_lines(start_el, end_el, items, container=None, proto=None, drop_heading=True):
    """
    Replace the paragraphs between a heading and the next heading with one
    clone of the first paragraph per item. Removes the heading if empty.
    """
    els = [e for e in region(None, start_el, end_el) if e.tag == P_TAG]
    proto = proto if proto is not None else (copy.deepcopy(els[0]) if els else None)
    remove(*els)
    if not items:
        if drop_heading:
            remove(start_el)
        return
    anchor = start_el
    for it in items:
        n = copy.deepcopy(proto)
        set_runs(n, it)
        anchor.addnext(n)
        anchor = n


def fill_pairs(start_el, end_el, pairs):
    """Heading followed by (title, subtitle) paragraph pairs (templates 1 & 3)."""
    els = [e for e in region(None, start_el, end_el) if e.tag == P_TAG]
    if len(els) < 2:
        return
    pa, pb = copy.deepcopy(els[0]), copy.deepcopy(els[1])
    remove(*els)
    anchor = start_el
    for a, b in pairs:
        n = copy.deepcopy(pa)
        set_runs(n, a)
        anchor.addnext(n)
        anchor = n
        if b:
            m = copy.deepcopy(pb)
            set_runs(m, b)
            anchor.addnext(m)
            anchor = m
    if not pairs:
        remove(start_el)


def fill_cell_pairs(tc, pairs):
    """Cell that holds only (title, subtitle) paragraph pairs, no heading."""
    els = [e for e in tc if e.tag == P_TAG]
    pa, pb = copy.deepcopy(els[0]), copy.deepcopy(els[1])
    remove(*els)
    for a, b in pairs:
        n = copy.deepcopy(pa)
        set_runs(n, a)
        tc.append(n)
        if b:
            m = copy.deepcopy(pb)
            set_runs(m, b)
            tc.append(m)
    if not pairs:
        tc.append(copy.deepcopy(pa))
        set_runs(tc[-1], "")


def fill_cell_lines(tc, items, keep=1):
    """Cell with `keep` heading paragraph(s) then bullet paragraphs."""
    ps = [e for e in tc if e.tag == P_TAG]
    heads, body = ps[:keep], ps[keep:]
    proto = copy.deepcopy(body[0]) if body else None
    remove(*body)
    if proto is None:
        return
    for it in items:
        n = copy.deepcopy(proto)
        set_runs(n, it)
        tc.append(n)
    if not items:
        remove(*heads)
        from docx.oxml import OxmlElement
        tc.append(OxmlElement("w:p"))


def fill_grid(table_el, items, prefix=""):
    """Fill an n-column grid left-to-right, cloning/removing rows as needed."""
    t = tbl(table_el)
    ncols = len(t.rows[0].cells)
    rows = [r._tr for r in t.rows]
    proto_row = copy.deepcopy(rows[0])
    n_rows = max(1, -(-len(items) // ncols))
    for r in rows[1:]:
        remove(r)
    for _ in range(n_rows - 1):
        table_el.append(copy.deepcopy(proto_row))
    trs = [r._tr for r in tbl(table_el).rows]
    for ri, tr in enumerate(trs):
        tcs = [c for c in tr if c.tag == TC_TAG]
        for ci, tc in enumerate(tcs):
            idx = ri * ncols + ci
            p = next(e for e in tc if e.tag == P_TAG)
            if idx < len(items):
                runs = par(p).runs
                if len(runs) >= 2:
                    set_last_run(p, items[idx])
                else:
                    set_runs(p, prefix + items[idx])
            elif ri == n_rows - 1 and ncols > 3 and ci > 0:
                remove(tc)          # chip rows: drop unused chips
            else:
                set_runs(p, "")


def fill_rows(table_el, rows):
    """Keep header row, clone data row 1 per entry. rows = list of cell-text lists."""
    t = tbl(table_el)
    trs = [r._tr for r in t.rows]
    proto = copy.deepcopy(trs[1])
    for r in trs[1:]:
        remove(r)
    for data in rows:
        tr = copy.deepcopy(proto)
        table_el.append(tr)
        tcs = [c for c in tr if c.tag == TC_TAG]
        for tc, txt in zip(tcs, data):
            p = next(e for e in tc if e.tag == P_TAG)
            set_runs(p, txt)


def assignment_rows(c, with_role=False):
    out = []
    for a in c["assignments"]:
        row = [a.get("assignment", ""), a.get("client", ""), a.get("sector", "")]
        if with_role:
            row.append(a.get("role", ""))
        out.append(row)
    return out


def period(e):
    return f"{e['from']} – {e['to']}" if e["from"] else e["to"]


def years_txt(e):
    return f"{e['years']} yrs" if e["years"] else ""


def rebuild_blocks(proto_els, anchor, items, fill):
    """
    Clone a block (list of elements) for each item after `anchor`.
    `fill(block_els, item)` customises the clone and returns the elements to insert.
    """
    protos = [copy.deepcopy(e) for e in proto_els]
    for e in proto_els:
        remove(e)
    for it in items:
        block = fill([copy.deepcopy(p) for p in protos], it)
        for e in block:
            anchor.addnext(e)
            anchor = e
    return anchor


def with_bullets(block, bullet_idx, bullets):
    """Replace the bullet paragraph at block[bullet_idx] by one per bullet."""
    proto = block[bullet_idx]
    out = block[:bullet_idx]
    for b in bullets:
        n = copy.deepcopy(proto)
        set_runs(n, b)
        out.append(n)
    out.extend(block[bullet_idx + 1:])
    return out


def nth_par(tc, i):
    return [e for e in tc if e.tag == P_TAG][i]


# ═════════════════════════════════════════════════════════════════════════════
#  Template 1 — Executive Sidebar
# ═════════════════════════════════════════════════════════════════════════════
def _fit_t1_layout(doc):
    """
    The sidebar tables are a full page tall, which pushes the page-break
    paragraph onto an extra blank page, and the nested tables are as wide as
    their cell (padding included) so the right edge is clipped. Trim both.
    """
    for h in doc.element.body.iter(qn("w:trHeight")):
        h.set(qn("w:val"), "14500")
    for t_el in doc.element.body.iter(TBL_TAG):
        if t_el.getparent().tag != TC_TAG:
            continue
        for el in t_el.iter():
            if el.tag in (qn("w:tblW"), qn("w:gridCol"), qn("w:tcW")):
                key = qn("w:w")
                if el.get(key) and el.get(key).isdigit():
                    el.set(key, str(int(int(el.get(key)) * 0.93)))


def fill_t1(doc, c):
    _fit_t1_layout(doc)
    tA, tB = doc.tables[0], doc.tables[1]
    L, R = tA.cell(0, 0)._tc, tA.cell(0, 1)._tc
    L2, R2 = tB.cell(0, 0)._tc, tB.cell(0, 1)._tc

    # contact lines
    for glyph, val in (("✉", c["email"]), ("☎", c["phone"]), ("⌂", c["location"])):
        p = find_par(L, glyph)
        set_runs(p, f"{glyph}  {val}") if val else remove(p)
    p = find_par(L, "in  ")
    set_runs(p, li_text(c)) if c["linkedin"] else remove(p)
    p = find_par(L, "◎")
    set_runs(p, pf_text(c)) if c["portfolio"] else remove(p)
    if not (c["email"] or c["phone"] or c["location"] or c["linkedin"] or c["portfolio"]):
        remove(find_par(L, "Contact"))

    remove(find_par(L, "Employee ID:"))                 # the employee code is not shown on the CV
    for label, val in (("Department:", c["department"]), ("Total Experience:", c["exp_text"])):
        p_ = find_par(L, label)
        set_runs(p_, label + " ", val) if val else remove(p_)
    if not (c["department"] or c["exp_text"]):
        remove(find_par(L, "Employee Details"))

    h_q, h_m = find_par(L, "Qualifications"), find_par(L, "Memberships")
    fill_pairs(h_q, h_m, [(q["name"], _join([q["institute"], q["year"]], ", ")) for q in c["quals"]])
    fill_pairs(h_m, None, [(_join([m["name"], m["level"]], " — "), m["number"]) for m in c["mems"]])

    # right column header
    ps = [e for e in R if e.tag == P_TAG]
    set_runs(ps[0], c["name"].upper())
    set_runs(ps[1], _title_line(c, "  •  "))
    set_runs(ps[2], _join([_join([q["code"] for q in c["quals"]], "  |  "), (c["exp_text"] + " Experience") if c["exp_text"] else ""], "  |  "))

    h = find_par(R, "Professional Summary")
    if c["summary"]:
        set_runs(h.getnext(), c["summary"])
    else:
        remove(h.getnext(), h)

    h = find_par(R, "Key Areas of Expertise")
    t_el = next_of(h, TBL_TAG)
    if c["key_skills"]:
        fill_grid(t_el, c["key_skills"])
    else:
        remove(t_el, h)
    h = find_par(R, "Sector Experience")
    t_el = next_of(h, TBL_TAG)
    if c["sectors"]:
        fill_grid(t_el, c["sectors"])
    else:
        remove(t_el, h)
    h = find_par(R, "Additional Skills")
    if c["other_skills"]:
        set_runs(h.getnext(), "  •  ".join(c["other_skills"]))
    else:
        remove(h.getnext(), h)
    fill_lines(find_par(R, "Achievements & Awards"), None, c["achievements"])

    # second table — left
    fill_lines(find_par(L2, "Certifications"), find_par(L2, "Tools & Technology"), c["certs"])
    fill_lines(find_par(L2, "Tools & Technology"), find_par(L2, "Social"), c["tools"])
    hs = find_par(L2, "Social")
    ps = [e for e in L2 if e.tag == P_TAG and e is not hs][-2:]
    set_runs(ps[0], li_text(c)) if c["linkedin"] else remove(ps[0])
    set_runs(ps[1], pf_text(c)) if c["portfolio"] else remove(ps[1])
    if not (c["linkedin"] or c["portfolio"]):
        remove(hs)

    # experience blocks
    head = find_par(R2, "Professional Experience")
    end = find_par(R2, "Key Assignments Handled")
    els = region(R2, head, end)
    tb = [e for e in els if e.tag == TBL_TAG][0]
    ps = [e for e in els if e.tag == P_TAG]
    company_p = ps[0]
    bullet_p = ps[1]
    spacer = next(e for e in ps if not par(e).runs)
    proto = [tb, company_p, bullet_p, spacer]

    def fill(block, e):
        t0 = tbl(block[0])
        set_runs(t0.cell(0, 0).paragraphs[0]._p, e["designation"])
        set_runs(t0.cell(0, 1).paragraphs[0]._p, period(e))
        set_runs(block[1], _join([e["employer"], years_txt(e)], "  ·  "))
        return with_bullets(block, 2, e["bullets"])

    # remove everything between head and end, rebuild
    for e in els:
        if e not in proto:
            remove(e)
    rebuild_blocks(proto, head, c["experiences"], fill)
    if not c["experiences"]:
        remove(head)

    # assignments
    h = find_par(R2, "Key Assignments Handled")
    t_el = next_of(h, TBL_TAG)
    if c["assignments"]:
        fill_rows(t_el, assignment_rows(c))
    else:
        remove(t_el, h)


# ═════════════════════════════════════════════════════════════════════════════
#  Template 2 — Classic Corporate
# ═════════════════════════════════════════════════════════════════════════════
def fill_t2(doc, c):
    body = doc.element.body
    hdr = doc.tables[0].cell(0, 0)._tc
    ps = [e for e in hdr if e.tag == P_TAG]
    set_runs(ps[0], c["name"])
    set_runs(ps[1], _title_line(c, ", "))
    set_runs(ps[2], _join([", ".join(q["code"] for q in c["quals"]),
                           (", ".join(m["name"] for m in c["mems"]) + " Member") if c["mems"] else "",
                           c["exp_total"] and c["exp_total"] + " Years"], "  ·  "))
    contact = _join([c["email"], c["phone"], c["location"]], "   |   ")
    set_runs(ps[3], contact) if contact else remove(ps[3])

    h = find_par(body, "PROFILE")
    if c["summary"]:
        set_runs(h.getnext(), c["summary"])
    else:
        remove(h.getnext(), h)

    # details table
    t_el = find_tbl_with(body, "Employee ID")
    t = tbl(t_el)
    rows = {r.cells[0].text.strip(): r._tr for r in t.rows}

    def setrow(label, val, new_label=None):
        tr = rows[label]
        if not val:
            remove(tr)
            return
        tcs_ = [c_ for c_ in tr if c_.tag == TC_TAG]
        if new_label:
            set_runs(next(e for e in tcs_[0] if e.tag == P_TAG), new_label)
        set_runs(next(e for e in tcs_[1] if e.tag == P_TAG), val)

    setrow("Employee ID", "")                           # the employee code is not shown on the CV
    setrow("Designation", c["designation"])
    setrow("Department / Team", c["department"])
    setrow("Total Experience", (c["exp_total"] + " years") if c["exp_total"] else "")
    setrow("Qualification", ", ".join(q["code"] for q in c["quals"]))
    setrow("LinkedIn", c["linkedin"])
    setrow("Instagram", c["portfolio"], "Portfolio")
    # membership rows: clone ICAI row per membership
    proto = copy.deepcopy(rows["ICAI Membership"])
    anchor = rows["ICAI Membership"]
    remove(rows["CISA Membership"])
    for m in c["mems"]:
        tr = copy.deepcopy(proto)
        anchor.addnext(tr)
        anchor = tr
        tcs = [x for x in tr if x.tag == TC_TAG]
        set_runs(next(e for e in tcs[0] if e.tag == P_TAG), f"{m['name']} Membership")
        set_runs(next(e for e in tcs[1] if e.tag == P_TAG), _join([m["level"], m["number"]], " — ") or "—")
    remove(rows["ICAI Membership"])
    if not tbl(t_el).rows:
        remove(t_el, find_par(body, "PERSONAL & PROFESSIONAL DETAILS"))

    h = find_par(body, "AREAS OF EXPERTISE")
    t_el = next_of(h, TBL_TAG)
    fill_grid(t_el, ["◆  " + s for s in c["key_skills"]], "") if c["key_skills"] else remove(t_el, h)
    h = find_par(body, "SECTOR EXPERIENCE")
    t_el = next_of(h, TBL_TAG)
    fill_grid(t_el, ["◆  " + s for s in c["sectors"]], "") if c["sectors"] else remove(t_el, h)

    # education: paragraphs with 3 runs
    h = find_par(body, "EDUCATION")
    end = find_par(body, "ADDITIONAL SKILLS")
    els = [e for e in region(body, h, end) if e.tag == P_TAG]
    proto = copy.deepcopy(els[0])
    remove(*els)
    anchor = h
    for q in c["quals"]:
        n = copy.deepcopy(proto)
        set_runs(n, q["name"], ("  —  " + q["institute"]) if q["institute"] else "", ("\t" + q["year"]) if q["year"] else "")
        anchor.addnext(n)
        anchor = n
    if not c["quals"]:
        remove(h)

    h = find_par(body, "ADDITIONAL SKILLS")
    if c["all_other"]:
        set_runs(h.getnext(), "  ·  ".join(c["all_other"]))
    else:
        remove(h.getnext(), h)

    set_runs(find_par(body, "Curriculum Vitae (continued)"), c["name"].upper(), "   ·   Curriculum Vitae (continued)")

    # experience
    head = find_par(body, "PROFESSIONAL EXPERIENCE")
    end = find_par(body, "KEY ASSIGNMENTS")
    els = region(body, head, end)
    ps = [e for e in els if e.tag == P_TAG]
    proto = [ps[0], ps[1], ps[2], next(e for e in ps if not par(e).runs)]

    def fill(block, e):
        set_runs(block[0], e["employer"], "\t" + period(e))
        set_runs(block[1], _join([e["designation"], f"({e['years']} years)" if e["years"] else ""], "  "))
        return with_bullets(block, 2, e["bullets"])

    for e in els:
        if e not in proto:
            remove(e)
    rebuild_blocks(proto, head, c["experiences"], fill)
    if not c["experiences"]:
        remove(head)

    h = find_par(body, "KEY ASSIGNMENTS")
    t_el = next_of(h, TBL_TAG)
    fill_rows(t_el, assignment_rows(c)) if c["assignments"] else remove(t_el, h)

    fill_lines(find_par(body, "CERTIFICATIONS"), find_par(body, "ACHIEVEMENTS & AWARDS"), c["certs"])
    h = find_par(body, "ACHIEVEMENTS & AWARDS")
    end = find_par(body, "I hereby confirm")
    # keep the trailing spacer paragraph (no runs) before the declaration
    els = [e for e in region(body, h, end) if e.tag == P_TAG]
    spacer = [e for e in els if not par(e).runs]
    texts = [e for e in els if par(e).runs]
    proto = copy.deepcopy(texts[0])
    remove(*texts)
    anchor = h
    for a in c["achievements"]:
        n = copy.deepcopy(proto)
        set_runs(n, a)
        anchor.addnext(n)
        anchor = n
    if not c["achievements"]:
        remove(h)

    sig = find_par(body, "Signature:")
    set_runs(sig, "Signature: ____________________", "\tDate: " + datetime.now().strftime("%B %Y"))


# ═════════════════════════════════════════════════════════════════════════════
#  Template 3 — Modern Banner
# ═════════════════════════════════════════════════════════════════════════════
def _heading_tbl(body, text):
    t = find_tbl_with(body, text)
    return t


def fill_t3(doc, c):
    body = doc.element.body
    hdr = doc.tables[0].rows[0].cells[-1]._tc
    ps = [e for e in hdr if e.tag == P_TAG]
    set_runs(ps[0], c["name"])
    set_runs(ps[1], _title_line(c, "  ·  ").upper())
    contact = "    ".join(x for x in (c["email"], c["phone"], c["location"]) if x)
    social = "    ".join(x for x in (li_text(c), pf_text(c)) if x)
    set_runs(ps[2], contact) if contact else remove(ps[2])
    set_runs(ps[3], social) if social else remove(ps[3])

    stats = doc.tables[1]
    vals = [c["exp_total"], str(len(c["sectors"])) if c["sectors"] else "",
            c["quals"][0]["code"] if c["quals"] else "", str(len(c["certs"])) if c["certs"] else ""]
    for i, v in enumerate(vals):
        if v:
            set_runs(stats.cell(0, i).paragraphs[0]._p, v)
    drop_cells(stats._tbl, {i for i, v in enumerate(vals) if not v})

    h = _heading_tbl(body, "ABOUT")
    sp = next_of(h, P_TAG)
    if c["summary"]:
        set_runs(sp, c["summary"])
    else:
        remove(sp, h)

    # proficiency + sectors
    ht = _heading_tbl(body, "CORE EXPERTISE & SECTORS")
    two = next_of(ht, TBL_TAG)
    Lc, Rc = tbl(two).cell(0, 0)._tc, tbl(two).cell(0, 1)._tc
    inner = next_of(nth_par(Lc, 0), TBL_TAG)
    if not c["key_skills"]:
        remove(inner, nth_par(Lc, 0))
    else:
        proto = copy.deepcopy([r._tr for r in tbl(inner).rows][0])
        for r in [r._tr for r in tbl(inner).rows]:
            remove(r)
        for s in c["key_skills"]:
            tr = copy.deepcopy(proto)
            inner.append(tr)
            tcs = [x for x in tr if x.tag == TC_TAG]
            set_runs(next(e for e in tcs[0] if e.tag == P_TAG), s)
            set_runs(next(e for e in tcs[1] if e.tag == P_TAG), "●●●●●", "")
    inner2 = next_of(nth_par(Rc, 0), TBL_TAG)
    if c["sectors"]:
        fill_grid(inner2, c["sectors"])
    else:
        remove(inner2, nth_par(Rc, 0))
    if not c["key_skills"] and not c["sectors"]:
        remove(two, ht)

    # qualifications & memberships
    ht = _heading_tbl(body, "QUALIFICATIONS & MEMBERSHIPS")
    two = next_of(ht, TBL_TAG)
    if c["quals"] or c["mems"]:
        fill_cell_pairs(tbl(two).cell(0, 0)._tc, [(q["name"], _join([q["institute"], q["year"]], " · ")) for q in c["quals"]])
        fill_cell_pairs(tbl(two).cell(0, 1)._tc, [(_join([m["name"], m["level"]], " — "), m["number"]) for m in c["mems"]])
    else:
        remove(two, ht)

    ht = _heading_tbl(body, "OTHER SKILLS")
    sp = next_of(ht, P_TAG)
    if c["all_other"]:
        set_runs(sp, "   |   ".join(c["all_other"]))
    else:
        remove(sp, ht)

    ct = [x for x in kids(body) if x.tag == TBL_TAG and "CERTIFICATIONS" in "".join(w.text for w in x.iter(qn("w:t")) if w.text) and "ACHIEVEMENTS" in "".join(w.text for w in x.iter(qn("w:t")) if w.text)][0]
    if c["certs"] or c["achievements"]:
        fill_cell_lines(tbl(ct).cell(0, 0)._tc, c["certs"])
        fill_cell_lines(tbl(ct).cell(0, 1)._tc, c["achievements"])
    else:
        remove(ct)

    # repeated name strip
    strip = [x for x in kids(body) if x.tag == TBL_TAG and len(tbl(x).rows) == 1 and len(tbl(x).rows[0].cells) == 1][-1]
    set_runs(tbl(strip).cell(0, 0).paragraphs[0]._p, c["name"], "   " + _title_line(c, " · "))

    # career journey
    hj = _heading_tbl(body, "CAREER JOURNEY")
    ha = _heading_tbl(body, "KEY ASSIGNMENTS")
    els = [e for e in region(body, hj, ha) if e.tag == TBL_TAG]
    proto = [els[0]]

    def fill(block, e):
        t0 = tbl(block[0])
        dl = [p._p for p in t0.cell(0, 0).paragraphs]
        set_runs(dl[0], (e["from"] + " –") if e["from"] else "")
        set_runs(dl[1], e["to"])
        set_runs(dl[2], years_txt(e))
        rc = t0.cell(0, 1)._tc
        rp = [x for x in rc if x.tag == P_TAG]
        set_runs(rp[0], e["designation"])
        set_runs(rp[1], e["employer"])
        newp = with_bullets(rp[:3], 2, e["bullets"])
        for x in rp[2:]:
            remove(x)
        for x in newp[2:]:
            rc.append(x)
        return [block[0]]

    for e in els[1:]:
        remove(e)
    anchor = els[0].getprevious()
    rebuild_blocks(proto, anchor, c["experiences"], fill)
    if not c["experiences"]:
        remove(hj)

    t_el = next_of(ha, TBL_TAG)
    fill_rows(t_el, assignment_rows(c)) if c["assignments"] else remove(t_el, ha)


# ═════════════════════════════════════════════════════════════════════════════
#  Template 4 — Timeline
# ═════════════════════════════════════════════════════════════════════════════
def _label_row(body, label):
    for x in kids(body):
        if x.tag == TBL_TAG and len(tbl(x).rows) == 1 and len(tbl(x).rows[0].cells) == 2:
            if tbl(x).cell(0, 0).text.strip() == label:
                return x
    return None


def fill_t4(doc, c):
    body = doc.element.body
    hc = doc.tables[0].cell(0, 0)._tc
    ps = [e for e in hc if e.tag == P_TAG]
    set_runs(ps[1], c["name"])
    set_runs(ps[2], _title_line(c, "  —  "))
    if c["email"] and c["phone"]:
        set_runs(ps[3], c["email"], "   •   ", c["phone"])
    else:
        set_runs(ps[3], c["email"] or c["phone"], "", "") if (c["email"] or c["phone"]) else remove(ps[3])
    if c["linkedin"] and c["portfolio"]:
        set_runs(ps[4], li_text(c), "   •   ", pf_text(c))
    else:
        set_runs(ps[4], li_text(c) or pf_text(c), "", "") if (c["linkedin"] or c["portfolio"]) else remove(ps[4])

    stats = doc.tables[1]
    # (employee code is not shown on the CV: its box is dropped, as are boxes with nothing in them)
    sv = [None, c["exp_text"], " / ".join(q["code"] for q in c["quals"]), " / ".join(m["name"] for m in c["mems"])]
    for i, v in enumerate(sv):
        if v:
            set_runs(stats.cell(0, i).paragraphs[1]._p, v)
    drop_cells(stats._tbl, {i for i, v in enumerate(sv) if not v})

    def right(label):
        x = _label_row(body, label)
        return x, (tbl(x).cell(0, 1)._tc if x is not None else None)

    x, tc = right("PROFILE")
    if c["summary"]:
        set_runs(nth_par(tc, 0), c["summary"])
    else:
        remove(x)
    x, tc = right("CORE EXPERTISE")
    set_alternating(nth_par(tc, 0), c["key_skills"], "   /   ") if c["key_skills"] else remove(x)
    x, tc = right("SECTORS")
    set_alternating(nth_par(tc, 0), c["sectors"], "   /   ") if c["sectors"] else remove(x)

    x, tc = right("EDUCATION")
    if c["quals"]:
        proto = copy.deepcopy(nth_par(tc, 0))
        for p_ in [e for e in tc if e.tag == P_TAG]:
            remove(p_)
        for q in c["quals"]:
            n = copy.deepcopy(proto)
            set_runs(n, q["name"], (", " + q["institute"]) if q["institute"] else "", ("\t" + q["year"]) if q["year"] else "")
            tc.append(n)
    else:
        remove(x)

    x, tc = right("MEMBERSHIPS")
    if c["mems"]:
        proto = copy.deepcopy(nth_par(tc, 0))
        for p_ in [e for e in tc if e.tag == P_TAG]:
            remove(p_)
        for m in c["mems"]:
            n = copy.deepcopy(proto)
            set_runs(n, _join([m["name"], m["level"]], " — "), ("\t" + m["number"]) if m["number"] else "")
            tc.append(n)
    else:
        remove(x)

    x, tc = right("OTHER SKILLS")
    set_runs(nth_par(tc, 0), ", ".join(c["all_other"])) if c["all_other"] else remove(x)
    x, tc = right("CERTIFICATIONS")
    fill_cell_lines(tc, c["certs"], keep=0) if c["certs"] else remove(x)
    x, tc = right("ACHIEVEMENTS")
    fill_cell_lines(tc, c["achievements"], keep=0) if c["achievements"] else remove(x)

    # closing name strip (paragraph with tab)
    set_runs(find_par(body, "Manager · Audit & Assurance") if find_par(body, "Manager · Audit & Assurance") is not None
             else find_par(body, "\t"), c["name"].upper(), "\t" + _title_line(c, " · "))

    # timeline
    hp = find_par(body, "EXPERIENCE TIMELINE")
    ha = find_tbl_with(body, "KEY ASSIGNMENTS")
    els = [e for e in region(body, hp, ha) if e.tag == TBL_TAG]
    proto = [els[0]]

    def fill(block, e):
        t0 = tbl(block[0])
        dl = [p._p for p in t0.cell(0, 0).paragraphs]
        set_runs(dl[0], e["from"])
        set_runs(dl[1], "to " + e["to"])
        set_runs(dl[2], years_txt(e))
        rc = t0.cell(0, 1)._tc
        rp = [x for x in rc if x.tag == P_TAG]
        set_runs(rp[0], "●  ", e["designation"])
        set_runs(rp[1], e["employer"])
        newp = with_bullets(rp[:3], 2, e["bullets"])
        for x in rp[2:]:
            remove(x)
        for x in newp[2:]:
            rc.append(x)
        return [block[0]]

    for e in els[1:]:
        remove(e)
    anchor = els[0].getprevious()
    rebuild_blocks(proto, anchor, c["experiences"], fill)
    if not c["experiences"]:
        remove(hp)

    inner = [e for e in tbl(ha).cell(0, 1)._tc if e.tag == TBL_TAG][0]
    if c["assignments"]:
        fill_rows(inner, assignment_rows(c))
    else:
        remove(ha)


# ═════════════════════════════════════════════════════════════════════════════
#  Template 5 — Proposal Profile
# ═════════════════════════════════════════════════════════════════════════════
def fill_t5(doc, c):
    body = doc.element.body
    hc = doc.tables[0].cell(0, 0)._tc
    ps = [e for e in hc if e.tag == P_TAG]
    set_runs(ps[1], c["name"])
    set_runs(ps[2], _title_line(c, " | "))

    # "Profile at a Glance": only the facts that are filled in, packed two per row
    g = doc.tables[1]
    mem_nums = "; ".join(f"{m['name']} {m['number']}" for m in c["mems"] if m["number"])
    pairs = [(l, v) for l, v in (
        ("Total Experience", (c["exp_total"] + " years") if c["exp_total"] else ""),
        ("Qualification", ", ".join(q["code"] for q in c["quals"])),
        ("Department", c["department"]),
        ("Membership", ", ".join(m["name"] for m in c["mems"])),
        ("Membership No.", mem_nums),
        ("Email", c["email"]), ("Phone", c["phone"]),
        ("LinkedIn", c["linkedin"]), ("Portfolio", c["portfolio"]),
    ) if v]
    grid_el = g._tbl
    rows_ = [r._tr for r in g.rows]
    need = -(-len(pairs) // 2)
    for r in rows_[need:]:
        remove(r)
    for ri, tr in enumerate(rows_[:need]):
        tcs_ = [x for x in tr if x.tag == TC_TAG]
        for ci in range(2):
            idx = ri * 2 + ci
            if idx < len(pairs):
                set_runs(next(e for e in tcs_[ci * 2] if e.tag == P_TAG), pairs[idx][0])
                set_runs(next(e for e in tcs_[ci * 2 + 1] if e.tag == P_TAG), pairs[idx][1])
            else:
                remove(tcs_[ci * 2], tcs_[ci * 2 + 1])
    if not pairs:
        remove(grid_el, find_par(body, "Profile at a Glance"))

    h = find_par(body, "Professional Summary")
    if c["summary"]:
        set_runs(h.getnext(), c["summary"])
    else:
        remove(h.getnext(), h)

    h = find_par(body, "Key Skills to Highlight")
    t_el = next_of(h, TBL_TAG)
    fill_grid(t_el, c["key_skills"]) if c["key_skills"] else remove(t_el, h)
    h = find_par(body, "Sector Experience")
    t_el = next_of(h, TBL_TAG)
    fill_grid(t_el, c["sectors"]) if c["sectors"] else remove(t_el, h)
    h = find_par(body, "Other Skills & Tools")
    if c["all_other"]:
        set_runs(h.getnext(), "  ·  ".join(c["all_other"]))
    else:
        remove(h.getnext(), h)

    ct = [x for x in kids(body) if x.tag == TBL_TAG and "Certifications" in "".join(w.text for w in x.iter(qn("w:t")) if w.text) and "Achievements" in "".join(w.text for w in x.iter(qn("w:t")) if w.text)][0]
    if c["certs"] or c["achievements"]:
        fill_cell_lines(tbl(ct).cell(0, 0)._tc, c["certs"])
        fill_cell_lines(tbl(ct).cell(0, 1)._tc, c["achievements"])
    else:
        remove(ct)

    strip = [x for x in kids(body) if x.tag == TBL_TAG and len(tbl(x).rows) == 1 and len(tbl(x).rows[0].cells) == 1][-1]
    set_runs(tbl(strip).cell(0, 0).paragraphs[0]._p, c["name"], "  —  Team Profile (continued)")

    h = find_par(body, "Employment History")
    t_el = next_of(h, TBL_TAG)
    if c["experiences"]:
        fill_rows(t_el, [[e["employer"], e["designation"], e["from"], e["to"], e["years"]] for e in c["experiences"]])
    else:
        remove(t_el, h)

    head = find_par(body, "Key Responsibilities")
    end = find_par(body, "Relevant Assignments")
    els = region(body, head, end)
    ps = [e for e in els if e.tag == P_TAG]
    proto = [ps[0], ps[1], next(e for e in ps if not par(e).runs)]

    def fill(block, e):
        set_runs(block[0], e["employer"], "  —  " + e["designation"])
        return with_bullets(block, 1, e["bullets"])

    for e in els:
        if e not in proto:
            remove(e)
    rebuild_blocks(proto, head, c["experiences"], fill)
    if not c["experiences"]:
        remove(head)

    h = find_par(body, "Relevant Assignments")
    t_el = next_of(h, TBL_TAG)
    fill_rows(t_el, assignment_rows(c, with_role=True)) if c["assignments"] else remove(t_el, h)


def _all_pars(doc):
    return list(doc.element.body.iter(P_TAG))


def _norm(el) -> str:
    return re.sub(r"^\d{2}\s+", "", par(el).text.strip())


def _is_numbered(el) -> bool:
    runs = par(el).runs
    return len(runs) >= 2 and re.fullmatch(r"\d{2}\s+", runs[0].text or "") is not None


def apply_titles(doc, template_id, titles):
    """Rename section headings the user edited."""
    pars = _all_pars(doc)
    for key, default in SECTIONS.get(template_id, []):
        new = titles.get(key)
        if not new or not default:
            continue
        hits = [e for e in pars if _norm(e) == default]
        if not hits:
            continue                      # section is hidden / empty, nothing to rename
        h = hits[-1]                      # last match: T3 has a stats caption with the same word
        if default.isupper():
            new = new.upper()             # keep the template's all-caps heading look
        if _is_numbered(h):
            set_runs(h, par(h).runs[0].text, new)
        else:
            set_runs(h, new)


def renumber_headings(doc):
    """Template 5 numbers its headings (01, 02, ...): keep them consecutive."""
    n = 0
    for e in _all_pars(doc):
        if _is_numbered(e):
            n += 1
            runs = par(e).runs
            runs[0].text = f"{n:02d}  "


def capture_custom_protos(doc, template_id):
    """Copies of an 'Achievements' heading + bullet (or label table in T4), taken
    before filling so they exist even if that section ends up removed."""
    body = doc.element.body
    cp = copy.deepcopy
    if template_id == "1":
        R = doc.tables[0].cell(0, 1)._tc
        h = find_par(R, "Achievements & Awards")
        return {"h": cp(h), "b": cp(h.getnext())}
    if template_id == "2":
        h = find_par(body, "ACHIEVEMENTS & AWARDS")
        return {"h": cp(h), "b": cp(h.getnext())}
    if template_id in ("3", "5"):
        key = ("CERTIFICATIONS", "ACHIEVEMENTS") if template_id == "3" else ("Certifications", "Achievements")
        ct = next(x for x in kids(body) if x.tag == TBL_TAG and all(
            k in "".join(w.text for w in x.iter(qn("w:t")) if w.text) for k in key))
        ps = [e for e in tbl(ct).cell(0, 1)._tc if e.tag == P_TAG]
        return {"h": cp(ps[0]), "b": cp(ps[1])}
    if template_id == "4":
        return {"t": cp(_label_row(body, "ACHIEVEMENTS"))}
    return {}


def add_custom_sections(doc, template_id, protos, custom):
    if not custom or not protos:
        return
    body = doc.element.body
    cp = copy.deepcopy
    sect = body.find(qn("w:sectPr"))

    def make_par_block(sec):
        h = cp(protos["h"])
        title = sec["title"].upper() if _norm(h).isupper() else sec["title"]
        if _is_numbered(h):
            set_runs(h, "00  ", title)
        else:
            set_runs(h, title)
        out = [h]
        for line in sec["lines"]:
            b = cp(protos["b"])
            set_runs(b, line)
            out.append(b)
        return out

    for sec in custom:
        if template_id == "4":
            t = cp(protos["t"])
            label_tc, right_tc = tbl(t).cell(0, 0)._tc, tbl(t).cell(0, 1)._tc
            set_runs(nth_par(label_tc, 0), sec["title"].upper())
            if sec["lines"]:
                fill_cell_lines(right_tc, sec["lines"], keep=0)
            sect.addprevious(t)
            continue
        els = make_par_block(sec)
        if template_id == "1":
            tc = doc.tables[1].cell(0, 1)._tc
            for e in els:
                tc.append(e)
        elif template_id == "2":
            anchor = find_par(body, "I hereby confirm")
            for e in els:
                anchor.addprevious(e)
        else:                                   # 3, 5: after the last section
            for e in els:
                sect.addprevious(e)


def _break_par(body):
    for e in body:
        if e.tag == P_TAG and e.xpath('.//w:br[@w:type="page"]'):
            return e
    return None


def _text_of(*els):
    return "".join(t.text for e in els for t in e.iter(qn("w:t")) if t.text).strip()


def _page2_has_content(doc, template_id):
    body = doc.element.body
    br = _break_par(body)
    if br is None:
        return False
    after = [e for e in br.itersiblings() if e.tag in (P_TAG, TBL_TAG)]
    if template_id == "1":                       # the whole second table is page-2 content
        return bool(after) and bool(_text_of(after[0]))
    rest = after[1:]                             # first element after the break is the "continued" strip
    keep = []
    for e in rest:
        t = _text_of(e)
        if e.tag == P_TAG and (t.startswith("I hereby confirm") or t.startswith("Signature:")):
            continue
        keep.append(e)
    return bool(_text_of(*keep))


def remove_page_two(doc, template_id, merge=True):
    """Flow everything onto one page: drop the page break and the
    'continued' header; template 1 moves its second table into the first."""
    body = doc.element.body
    br = _break_par(body)
    if br is None:
        return
    nxt = br.getnext()
    if template_id == "1" and nxt is not None and nxt.tag == TBL_TAG:
        if merge:
            tA, tB = doc.tables[0], doc.tables[1]
            for cell_a, cell_b in ((tA.cell(0, 0)._tc, tB.cell(0, 0)._tc), (tA.cell(0, 1)._tc, tB.cell(0, 1)._tc)):
                for e in [x for x in cell_b if x.tag in (P_TAG, TBL_TAG)]:
                    cell_a.append(e)
        remove(nxt)
    elif nxt is not None:
        remove(nxt)
    remove(br)


def compact(doc, font=0.9, spacing=0.55):
    """Tighten fonts and paragraph spacing so more fits on a page."""
    for el in doc.element.body.iter(qn("w:sz"), qn("w:szCs")):
        v = el.get(qn("w:val"))
        if v and v.isdigit():
            el.set(qn("w:val"), str(max(14, int(int(v) * font))))
    for el in doc.element.body.iter(qn("w:spacing")):
        for attr in ("w:before", "w:after"):
            v = el.get(qn(attr))
            if v and v.isdigit():
                el.set(qn(attr), str(int(int(v) * spacing)))


def remove_footers(doc):
    """The templates ship with a "JHS & Associates LLP | Confidential | CV last updated"
    footer (plus page numbers); the CV is meant to carry none."""
    for sect in doc.element.body.iter(qn("w:sectPr")):
        for ref in sect.findall(qn("w:footerReference")):
            sect.remove(ref)


def _ensure_cell_paragraphs(doc):
    """Word rejects a table cell that does not end with a paragraph."""
    from docx.oxml import OxmlElement
    for tc in doc.element.body.iter(TC_TAG):
        if len(tc) == 0 or tc[-1].tag != P_TAG:
            tc.append(OxmlElement("w:p"))


FILLERS = {"1": fill_t1, "2": fill_t2, "3": fill_t3, "4": fill_t4, "5": fill_t5}


def render_docx(template_id: str, profile: dict, experiences: List[dict], emp_name: str = "") -> bytes:
    if template_id not in FILLERS:
        raise ValueError("Invalid template id")
    doc = Document(os.path.join(TEMPLATE_DIR, TEMPLATE_FILES[template_id]))
    ctx = build_context(profile, experiences, emp_name, template_id)
    protos = capture_custom_protos(doc, template_id) if ctx["custom"] else {}
    FILLERS[template_id](doc, ctx)
    apply_titles(doc, template_id, ctx["titles"])
    add_custom_sections(doc, template_id, protos, ctx["custom"])
    if ctx["layout"] == "1":                        # user asked for a single page
        remove_page_two(doc, template_id)
        compact(doc, font=0.85, spacing=0.4) if template_id == "2" else compact(doc)
    elif not _page2_has_content(doc, template_id):  # nothing on page 2: don't leave a near-empty page
        remove_page_two(doc, template_id, merge=False)
    if template_id == "5":
        renumber_headings(doc)
    remove_footers(doc)
    _ensure_cell_paragraphs(doc)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
