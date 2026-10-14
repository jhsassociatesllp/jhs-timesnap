# backend/cv_builder/resume_parser.py
"""
Reads an old resume (.pdf / .docx) and suggests values for the CV profile form.

* Everything happens in memory: the file is never written to disk or the
  database and nothing is logged. Only the suggested values go back to the
  browser, where the employee reviews / edits them before saving.
* No external service is called - the parsing is rule based (headings,
  patterns and the dropdown master lists), so a resume never leaves the server.
  It is a best-effort helper: the employee always checks the result.
"""

import re
from datetime import date
from io import BytesIO
from typing import Dict, List, Optional

MAX_PDF_PAGES = 15
MAX_TEXT = 80_000

# ── text extraction ───────────────────────────────────────────────────────────


def _find_gutter(words, width):
    """x position of an empty vertical band between two text columns, or None for a single column."""
    n = len(words)
    if n < 20:
        return None
    best, hits = None, []
    for x in range(int(width * 0.2), int(width * 0.75), 3):
        left = sum(1 for w in words if w["x1"] <= x)
        right = sum(1 for w in words if w["x0"] >= x)
        if left < 0.12 * n or right < 0.12 * n:
            continue
        crossing = sum(1 for w in words if w["x0"] < x < w["x1"])
        if best is None or crossing < best:
            best, hits = crossing, [x]
        elif crossing == best:
            hits.append(x)
    if best is not None and best <= 0.03 * n:
        return hits[len(hits) // 2]                 # middle of the empty band
    return None


def _columns_text(page):
    """Two-column page -> left column then right column, working on whole words so nothing is
    cut in half. A line that runs across the gutter (a title, a header) is kept whole and
    separates one column block from the next. Returns None for a single-column page."""
    words = page.extract_words()
    split = _find_gutter(words, float(page.width))
    if split is None:
        return None
    rows: List[list] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(rows[-1][0] - w["top"]) <= 3:
            rows[-1][1].append(w)
        else:
            rows.append([w["top"], [w]])
    out, left, right = [], [], []

    def flush():
        out.extend(left)
        out.extend(right)
        left.clear()
        right.clear()

    for _, ws in rows:
        ws.sort(key=lambda w: w["x0"])
        if any(w["x0"] < split < w["x1"] for w in ws):          # full-width line
            flush()
            out.append(" ".join(w["text"] for w in ws))
            continue
        lw = [w["text"] for w in ws if (w["x0"] + w["x1"]) / 2 < split]
        rw = [w["text"] for w in ws if (w["x0"] + w["x1"]) / 2 >= split]
        if lw:
            left.append(" ".join(lw))
        if rw:
            right.append(" ".join(rw))
    flush()
    return "\n".join(out)


def _normalise(text: str) -> str:
    return text.replace("\r", "\n").replace("\u00a0", " ")[:MAX_TEXT]


def extract_texts(data: bytes, ext: str) -> List[str]:
    """Candidate readings of the file (best guess first). PDFs give a plain top-to-bottom
    reading and, when a two-column layout is detected, a column-by-column one as well;
    parse_resume_texts() keeps whichever yields more."""
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("This PDF is password protected")
        plain_pages, col_pages, any_cols = [], [], False
        try:
            import pdfplumber
            with pdfplumber.open(BytesIO(data)) as pdf:
                for page in pdf.pages[:MAX_PDF_PAGES]:
                    plain = page.extract_text() or ""
                    cols = _columns_text(page)
                    plain_pages.append(plain)
                    col_pages.append(cols if cols is not None else plain)
                    any_cols = any_cols or cols is not None
                    if sum(len(x) for x in plain_pages) > MAX_TEXT:
                        break
        except Exception:
            plain_pages, col_pages, any_cols = [], [], False
        texts = ["\n".join(plain_pages)]
        if any_cols:
            texts.append("\n".join(col_pages))
        if len(texts[0].strip()) < 40:                          # pdfplumber found nothing: plain pypdf
            texts = ["\n".join((pg.extract_text() or "") for pg in reader.pages[:MAX_PDF_PAGES])]
        return [_normalise(t) for t in texts]
    if ext == ".docx":
        import docx
        d = docx.Document(BytesIO(data))
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:                                   # many resumes are laid out in tables
            for row in t.rows:
                seen = set()
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    parts.extend(cell.text.split("\n"))
        return [_normalise("\n".join(parts))]
    raise ValueError("Unsupported file type")


def extract_text(data: bytes, ext: str) -> str:
    return extract_texts(data, ext)[0]


# ── helpers ───────────────────────────────────────────────────────────────────
_BULLET = re.compile(r"^[\s•●▪◦○■□◆►➢✓✔\-–—*·]+")
_HEADINGS = {
    "summary": ["professional summary", "career summary", "summary", "profile", "career objective", "objective", "about me", "about"],
    "skills": ["core expertise", "key expertise", "key skills to highlight", "additional skills", "other skills",
               "other skills & tools", "expertise & skills", "technical skills", "core skills", "skill set", "key competencies", "key skills", "core competencies", "areas of expertise", "skills & tools", "skills", "expertise", "competencies", "tools & technologies", "tools"],
    "education": ["education & qualifications", "educational qualifications", "academic qualifications", "academic background", "education", "academics", "qualifications", "qualification"],
    "certifications": ["certifications", "certification", "certificates", "licenses & certifications", "courses", "training"],
    "achievements": ["achievements", "achievement", "awards & achievements", "awards", "accomplishments", "honours", "honors", "awards and honours"],
    "experience": ["professional experience", "work experience", "employment history", "work history", "experience", "employment", "internships", "internship"],
    "other": ["sectors", "sector experience", "memberships", "membership", "key assignments",
              "key assignments handled", "relevant assignments", "assignments", "projects", "personal details", "personal information", "declaration", "languages", "interests", "hobbies", "references", "extra curricular", "extracurricular", "contact"],
}
_HEADING_LOOKUP = {h: k for k, hs in _HEADINGS.items() for h in hs}


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", _BULLET.sub("", line)).strip()


# Headings are matched exactly first, then by keyword, so "Professional Profile:",
# "Technical Skill Set", "Key Strengths", "Awards & Recognition" ... are all understood.
_FUZZY = [
    ("other", r"personal (?:details|information|data)|declaration|references?|languages?(?: known)?|interests?|hobbies|contact|address|projects?"),
    ("certifications", r"certif|licen[cs]e|courses?\b|training|workshops?"),
    ("achievements", r"achiev|awards?\b|honou?rs?|accomplish|recogni|accolades"),
    ("skills", r"skills?\b|competenc|expertise|technolog|tools?\b|strengths|proficienc"),
    ("education", r"education|academic|qualification|scholastic"),
    ("experience", r"experience|employment|work history|internships?|career history|professional background"),
    ("summary", r"summary|profile|objective|about me|overview|introduction|career goal"),
]
_SMALL_WORDS = {"and", "of", "the", "in", "for", "&", "a", "to", "on"}


_HEAD_MODS = {"professional", "technical", "key", "core", "personal", "career", "academic", "educational", "work",
              "additional", "other", "relevant", "details", "set", "history", "background", "areas", "area", "my",
              "about", "me", "extra", "curricular", "activities", "functional", "domain", "major", "main", "total"}


def _heading_words_only(raw: str) -> bool:
    """True when every word is a generic heading word - so "Technical Skill Set" is a heading
    but "IFRS Certificate" (a certification item) is not."""
    for w in re.split(r"[\s/&,]+", raw.lower()):
        if not w or w in _SMALL_WORDS or w in _HEAD_MODS:
            continue
        if not any(re.search(pat, w) for _, pat in _FUZZY):
            return False
    return True


def _headingish(raw: str, line: str) -> bool:
    if line.rstrip().endswith(":"):
        return True
    words = [w for w in re.split(r"[\s/]+", raw) if w and w.lower() not in _SMALL_WORDS]
    return bool(words) and all(w[0].isupper() for w in words if w[0].isalpha())


def _heading_key(line: str, allow_generic: bool = True) -> Optional[str]:
    raw = re.sub(r"[:\-–—_|]+$", "", _clean_line(line)).strip()
    if re.fullmatch(r"(?:\S ){3,}\S", raw):                     # "E D U C A T I O N" (letter-spaced headings)
        raw = raw.replace(" ", "")
    t = re.sub(r"\s*&\s*", " & ", raw.lower())
    if len(t) > 45 or not t:
        return None
    key = _HEADING_LOOKUP.get(t)
    if key:
        return key
    if allow_generic and not _BULLET.match(line):
        short = len(raw.split()) <= 5 and not re.search(r"[.!?;@]|\d{4}", raw)
        if short and _headingish(raw, line) and _heading_words_only(raw):
            for k, pat in _FUZZY:
                if re.search(pat, t):
                    return k
        # any other short ALL-CAPS line is a heading we do not use: it still ends the previous section
        if re.fullmatch(r"[A-Z][A-Z &/]{5,38}", raw) and 1 <= len(raw.split()) <= 4:
            return "other"
    return None


_FOOTER = re.compile(r"confidential|cv last updated|last updated|^page \d+( of \d+)?$|^\d+ ?/ ?\d+$|\|\s*page\s*\d", re.I)


def _split_label_row(line: str):
    """"PROFILE Results-driven analyst..." (a label and its first line of text on one row, as in
    label | text layouts) -> ("PROFILE", "Results-driven analyst...")."""
    words = line.split()
    for n in range(min(4, len(words) - 1), 0, -1):
        phrase = " ".join(words[:n])
        if phrase.isupper() and re.sub(r"\s*&\s*", " & ", phrase.lower()) in _HEADING_LOOKUP:
            rest = " ".join(words[n:])
            if rest.isupper() and re.sub(r"\s*&\s*", " & ", rest.lower()) in _HEADING_LOOKUP:
                return None                      # "SKILLS PROFILE": two column headings on one row
            return phrase, rest
    return None


def prepare_lines(text: str) -> List[str]:
    out: List[str] = []
    for raw in text.split("\n"):
        ln = raw.strip()
        if not ln or _FOOTER.search(ln):
            continue
        row = _split_label_row(ln)
        if row:
            out.extend(row)
        else:
            out.append(ln)
    # a running header such as "ASHA VERMA  Senior Manager" repeated on page 2 is not content
    name = next((l for l in out[:6] if 2 <= len(l.split()) <= 4 and all(re.fullmatch(r"[A-Za-z.'\-]+", w) for w in l.split())), "")
    if name:
        low = name.lower()
        out = [l for n, l in enumerate(out) if not (l.lower().startswith(low) and len(l) > len(name) and len(l) < 90 and l != name)]
    return out


def is_label_layout(text: str) -> bool:
    """True for "LABEL | text" layouts where the section name and its first line share a row."""
    n = 0
    for ln in text.split("\n"):
        if _split_label_row(ln.strip()):
            n += 1
    return n >= 2


def _sections(lines: List[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {"header": []}
    cur = "header"
    for n, ln in enumerate(lines):
        key = _heading_key(ln, allow_generic=n > 2)               # the first lines are the name / title
        if key:
            cur = key
            out.setdefault(cur, [])
            continue
        out.setdefault(cur, []).append(ln)
    return out


def _word_re(term: str, flags=re.I) -> "re.Pattern":
    return re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w])", flags)


# ── individual extractors ─────────────────────────────────────────────────────
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\d])(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{2,5}\)?[\s\-.]?)?\d{3,5}[\s\-.]?\d{3,5}(?![\d])")
_URL = re.compile(r"(?:https?://|www\.)[^\s,;|)>\]]+", re.I)
_LINKEDIN = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub|company)/[\w\-%./]+", re.I)
_CITIES = ["Navi Mumbai", "Mumbai", "Thane", "Pune", "Delhi", "New Delhi", "Gurgaon", "Gurugram", "Noida", "Bengaluru",
           "Bangalore", "Hyderabad", "Chennai", "Kolkata", "Ahmedabad", "Surat", "Jaipur", "Lucknow", "Indore",
           "Nagpur", "Kochi", "Chandigarh", "Dubai", "Abu Dhabi", "Singapore", "London"]


def _contact(text: str, header: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    # PDFs often break a long LinkedIn URL ("priya -sharma -ca" or a line break after a hyphen)
    for _ in range(3):
        text = re.sub(r"(linkedin\.com/in/[\w%.\-]*)\s+(-[\w%.\-]+)", r"\1\2", text, flags=re.I)
    text = re.sub(r"(linkedin\.com/in/[\w%.]*-)\s*\n\s*([\w\-%.]+)", r"\1\2", text, flags=re.I)
    m = _EMAIL.search(text)
    if m:
        out["email"] = m.group(0)
    li = _LINKEDIN.search(text)
    if li:
        out["linkedin"] = re.sub(r"^https?://(www\.)?", "", li.group(0)).rstrip("/.,")
    for u in _URL.findall(text):
        if "linkedin.com" in u.lower():
            continue
        out["portfolio"] = u.rstrip("/.,")
        break
    if "linkedin" not in out:
        m = re.search(r"linked\s?in\s*[:\-]\s*([^\s|•,;]+)", text, re.I)
        if m:
            out["linkedin"] = m.group(1).rstrip("/.,")
    if "portfolio" not in out:
        m = re.search(r"(?:portfolio|website|github|behance)\s*[:\-]\s*([^\s|•,;]+)", text, re.I)
        if m:
            out["portfolio"] = m.group(1).rstrip("/.,")
    head = "\n".join(header[:12]) or text[:600]
    for m in _PHONE.finditer(head):
        digits = re.sub(r"\D", "", m.group(0))
        if 10 <= len(digits) <= 13 and not re.search(r"(19|20)\d\d\s*[-–]\s*(19|20)\d\d", m.group(0)):
            out["phone"] = m.group(0).strip(" -.")
            break
    for city in _CITIES:
        if re.search(r"(?<![\w])" + re.escape(city) + r"(?![\w])", head, re.I):
            out["location"] = city + (", India" if city not in ("Dubai", "Abu Dhabi", "Singapore", "London") else "")
            break
    return out


_QUAL_SYNONYMS = {                       # master value -> phrases that mean it
    "CA": [r"chartered accountant", r"\bC\.?A\.?\b(?!\w)", r"\bICAI\b"],
    "ACCA": [r"\bACCA\b"], "CMA": [r"\bCMA\b", r"cost (?:and|&) management accountant"],
    "CPA": [r"\bCPA\b"], "CFA": [r"\bCFA\b(?! Institute)", r"chartered financial analyst"],
    "MBA": [r"\bMBA\b", r"master of business administration", r"\bPGDM\b"],
    "M.Com": [r"\bM\.?\s?com\b", r"master of commerce"], "B.Com": [r"\bB\.?\s?com\b", r"bachelor of commerce"],
    "BBA": [r"\bBBA\b", r"bachelor of business administration"],
    "B.Tech": [r"\bB\.?\s?tech\b", r"bachelor of technology"], "M.Tech": [r"\bM\.?\s?tech\b", r"master of technology"],
    "BAF": [r"\bBAF\b", r"bachelor of accounting (?:and|&) finance"],
    "BSc": [r"\bB\.?\s?sc\b", r"bachelor of science"], "MSc": [r"\bM\.?\s?sc\b", r"master of science"],
}
_INSTITUTE = re.compile(r"universit|institute|college|school|academy|\bICAI\b|\bIIM\b|\bIIT\b|board", re.I)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def _first_year(strings) -> str:
    for w in strings:
        m = _YEAR.search(w)
        if m:
            return m.group(1)
    return ""


def _matches(master: str, pattern: str, line: str) -> bool:
    flags = 0 if (master == "CA" and pattern.startswith("\\bC")) else re.I   # "CA" is case-sensitive
    return re.search(pattern, line, flags) is not None


def _education(sections: Dict[str, List[str]], all_lines: List[str], masters: List[str]):
    edu = sections.get("education") or []
    pool = edu if edu else all_lines
    quals, details = [], {}
    for master in masters:
        pats = _QUAL_SYNONYMS.get(master)
        if not pats:
            continue
        if master == "CA" and not edu:
            pats = pats[:1]                      # outside an education section only the full phrase counts
        for i, ln in enumerate(pool):
            if not any(_matches(master, p, ln) for p in pats):
                continue
            quals.append(master)
            window = pool[i:i + 3]
            inst = ""
            for w in window:
                for seg in re.split(r"\s[–—\-|]\s|\s[–—|]|[|,]", _clean_line(w)):
                    seg = re.sub(r"\(?\b(?:19|20)\d{2}\b\)?", "", seg).strip(" ,-–|")
                    if _INSTITUTE.search(seg) and not re.search(r"\b(member|years?)\b", seg, re.I) and len(seg) <= 80:
                        inst = seg
                        break
                if inst:
                    break
            details[master] = {"institute": inst, "year": _first_year(window)}
            break
    return quals, details


def _skills(sections: Dict[str, List[str]], text: str, masters: List[str]):
    found: List[str] = []
    for m in masters:
        if len(m) >= 3 and _word_re(m).search(text) and m not in found:
            found.append(m)
    # skills the resume lists that are not in our master list (shown as hints, not auto-added)
    extra: List[str] = []
    for ln in sections.get("skills", []):
        for part in re.split(r"[,;|•●▪/]|\s{3,}", _clean_line(ln)):
            part = part.strip(" .:-")
            if 2 < len(part) <= 30 and len(part.split()) <= 3 and re.search(r"[A-Za-z]", part):
                if not any(part.lower() == f.lower() for f in found) and part not in extra:
                    extra.append(part)
    return found[:25], extra[:12]


_MEMBERSHIPS = ["ICAI", "ICMAI", "ICSI", "CISA", "CISSP", "OSCP", "CFA Institute"]


def _memberships(text: str, masters: List[str]):
    out = [m for m in masters if m in _MEMBERSHIPS and _word_re(m, 0).search(text)]
    num = re.search(r"(?:membership|member|m\.?\s?no\.?)\s*(?:no\.?|number|#)?\s*[:\-]?\s*(\d{5,8})", text, re.I)
    return out, (num.group(1) if num else "")


_SECTOR_WORDS = {
    "Financial Services": ["financial services", "nbfc", "fintech", "asset management", "wealth management"],
    "Banking": ["bank", "banking"], "Insurance": ["insurance", "insurer"],
    "Manufacturing": ["manufactur"], "Real Estate": ["real estate", "construction", "housing finance"],
    "Education": ["edtech", "education sector", "schools"], "Healthcare": ["healthcare", "hospital", "medical"],
    "Retail": ["retail"], "FMCG": ["fmcg"], "Technology": ["technology sector", "saas"],
    "IT / ITES": ["it services", "ites", "software"], "Infrastructure": ["infrastructure"],
    "Pharmaceuticals": ["pharma"], "Automotive": ["automotive", "auto-component", "automobile"],
    "Energy": ["energy", "oil & gas", "oil and gas", "power sector"],
    "Government / Public Sector": ["government", "public sector", "psu"],
    "Professional Services": ["professional services", "consulting"],
}


def _sectors(text: str, masters: List[str]) -> List[str]:
    low = text.lower()
    scored = []
    for sector, words in _SECTOR_WORDS.items():
        if sector in masters:
            n = sum(low.count(w) for w in words)
            if n:
                scored.append((n, sector))
    scored.sort(reverse=True)
    return [s for _, s in scored[:6]]


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_RANGE = re.compile(
    r"((?:[A-Za-z]{3,9}\.?\s*|\d{1,2}[/\-.])?(?:19|20)\d{2})\s*(?:to|till|until|[-–—])\s*"
    r"((?:[A-Za-z]{3,9}\.?\s*|\d{1,2}[/\-.])?(?:(?:19|20)\d{2})|present|current|till date|now|ongoing)", re.I)


def _ym(token: str, end: bool = False):
    token = token.strip().lower()
    if token in ("present", "current", "till date", "now", "ongoing"):
        t = date.today()
        return t.year * 12 + t.month
    y = re.search(r"(19|20)\d{2}", token)
    if not y:
        return None
    year = int(y.group(0))
    mon = None
    mm = re.search(r"[a-z]{3}", token)
    if mm and mm.group(0) in _MONTHS:
        mon = _MONTHS[mm.group(0)]
    else:
        nm = re.match(r"(\d{1,2})[/\-.]", token)
        if nm and 1 <= int(nm.group(1)) <= 12:
            mon = int(nm.group(1))
    return year * 12 + (mon if mon else (12 if end else 1))


def _experience_years(sections: Dict[str, List[str]], text: str) -> str:
    stated = [float(x) for x in re.findall(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\b", text, re.I) if float(x) <= 45]
    near = re.findall(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\b[^.]{0,40}experience|experience[^.]{0,30}?(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)", text, re.I)
    for a, b in near:
        v = float(a or b)
        if v <= 45:
            return ("%g" % v)
    exp_text = "\n".join(sections.get("experience", [])) or text
    spans = []
    for a, b in _RANGE.findall(exp_text):
        s, e = _ym(a), _ym(b, end=True)
        if s and e and e >= s and (e - s) < 12 * 45:
            spans.append((s, e))
    if spans:
        spans.sort()
        merged = [list(spans[0])]
        for s, e in spans[1:]:
            if s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        months = sum(e - s for s, e in merged)
        if months >= 12:
            return "%g" % (round(months / 12 * 2) / 2)
        if months > 0:
            return f"{months} month"
    if len(stated) == 1:                         # a single "N years" figure on the resume
        return "%g" % stated[0]
    return ""


def _bulleted(lines: List[str], limit=8) -> str:
    items = []
    for ln in lines:
        t = _clean_line(ln)
        if len(t) < 3:
            continue
        items.append(t)
    return "\n".join(items[:limit])


_JOB_WORDS = re.compile(
    r"\b(manager|analyst|associate|auditor|accountant|executive|officer|consultant|engineer|developer|director|partner|"
    r"trainee|intern|article|articled|head|lead|specialist|assistant|senior|junior|principal|supervisor|coordinator|"
    r"administrator|advisor|adviser|controller|architect|designer|scientist|secretary|clerk|cma|ca|cfo|ceo|vp)\b", re.I)


def _capitalised(words: List[str]) -> bool:
    letters = [w for w in words if w[0].isalpha()]
    return bool(letters) and sum(1 for w in letters if w[0].isupper()) >= 0.6 * len(letters)


def _designation(lines: List[str]) -> Dict[str, str]:
    """The job title: one of the first lines, short, capitalised and containing a job word
    ("Senior Associate - Audit & Assurance", "CMA Article", "Chartered Accountant | email | city")."""
    for ln in lines[:30]:
        t = _clean_line(ln)
        if not t or _heading_key(ln, allow_generic=False):
            continue
        segs = [x.strip() for x in re.split(r"\s[–—\-|•·]\s|\s[–—|•·]\s*|\||•", t) if x.strip()]
        segs = [x for x in segs if not _CONTACT_LINE.search(x) and not re.search(r"\d", x)]
        if not segs or len(t.split()) > 14:
            continue
        first = segs[0]
        words = first.split()
        if 1 <= len(words) <= 6 and _JOB_WORDS.search(first) and _capitalised(words) and not re.search(r"[.;:!?]", first):
            out = {"designation": first[:60]}
            if len(segs) > 1:
                dep = segs[1]
                if 1 <= len(dep.split()) <= 5 and _capitalised(dep.split()) and not re.search(r"[.;:!?]", dep):
                    out["department"] = dep[:60]
            return out
    return {}


_CONTACT_LINE = re.compile(r"@|https?://|www\.|linkedin|\+?\d[\d\s\-().]{8,}\d")


def _intro_paragraph(lines: List[str]) -> str:
    """A resume without a 'Summary' heading usually still opens with a paragraph under the name."""
    stop = len(lines)
    for n, ln in enumerate(lines):
        if n > 2 and _heading_key(ln) in ("skills", "education", "experience", "certifications", "achievements"):
            stop = n
            break
    for n in range(1, min(stop, 40)):
        ln = lines[n]
        if (_BULLET.match(ln) and len(ln) < 90) or _heading_key(ln) or _CONTACT_LINE.search(ln):
            continue
        if len(ln) < 70 or len(ln.split()) < 10:
            continue
        parts, total = [_clean_line(ln)], len(ln)
        for nxt in lines[n + 1:n + 6]:
            if _heading_key(nxt) or _BULLET.match(nxt) or len(nxt) < 35 or _CONTACT_LINE.search(nxt) or total > 600:
                break
            parts.append(_clean_line(nxt))
            total += len(nxt)
        text = " ".join(parts)
        return text[:700].rsplit(" ", 1)[0] if len(text) > 700 else text
    return ""


def _lines_matching(lines: List[str], pattern: str, limit: int = 6) -> str:
    rx = re.compile(pattern, re.I)
    out = []
    for ln in lines:
        t = _clean_line(ln)
        if 6 <= len(t) <= 160 and rx.search(t) and not _heading_key(ln) and t not in out:
            out.append(t)
    return "\n".join(out[:limit])


# ── public API ────────────────────────────────────────────────────────────────
def parse_resume(text: str, masters: Dict[str, List[str]]) -> dict:
    """Return {"fields": {...suggested form values...}, "extra_skills": [...]}."""
    lines = prepare_lines(text)
    text = "\n".join(lines)
    sections = _sections(lines)
    fields: Dict[str, object] = {}
    fields.update(_contact(text, sections.get("header", [])))
    fields.update(_designation(lines))

    summary = " ".join(_clean_line(l) for l in sections.get("summary", []))
    if not summary:
        summary = _intro_paragraph(lines)                       # no Summary heading: take the opening paragraph
    if summary:
        fields["summary"] = summary[:700].rsplit(" ", 1)[0] if len(summary) > 700 else summary

    quals, qdet = _education(sections, lines, masters.get("qualifications", []))
    if quals:
        fields["qualification"] = quals
        fields["qualification_details"] = {k: v for k, v in qdet.items() if v.get("institute") or v.get("year")}

    non_edu = "\n".join(l for k, ls in sections.items() if k != "education" for l in ls)
    skills, extra = _skills(sections, text, masters.get("skills_expertise", []))
    if skills:
        fields["skills_expertise"] = skills
    mems, mem_no = _memberships(text, masters.get("memberships", []))
    if mems:
        fields["membership"] = mems
        if mem_no:
            fields["membership_id"] = mem_no
    secs = _sectors(non_edu, masters.get("sector_experience", []))
    if secs:
        fields["sector_experience"] = secs
    cert = _bulleted(sections.get("certifications", [])) or _lines_matching(
        lines, r"\bcertif(?:ied|icate|ication)|\bdiploma\b|\bcourse\b")
    if cert:
        fields["certifications"] = cert
    ach = _bulleted(sections.get("achievements", [])) or _lines_matching(
        lines, r"\b(?:award(?:ed)?|rank(?:ed)?|winner|won|topper|scholarship|gold medal|recogni[sz]ed|appreciation)\b")
    if ach:
        fields["achievements"] = ach
    yrs = _experience_years(sections, text)
    if yrs:
        fields["total_experience"] = yrs
    wanted = {"summary": "summary", "qualification": "qualifications", "skills_expertise": "skills",
              "sector_experience": "sectors", "certifications": "certifications",
              "achievements": "achievements", "total_experience": "total experience"}
    missing = [label for key, label in wanted.items() if key not in fields]
    return {"fields": fields, "extra_skills": extra, "missing": missing}


def parse_resume_texts(texts: List[str], masters: Dict[str, List[str]]) -> dict:
    """Parse each reading of the file; keep the one that found the most, and fill any field it
    missed from the others."""
    texts = [t for t in texts if t and t.strip()]
    results = [parse_resume(t, masters) for t in texts]
    if not results:
        return {"fields": {}, "extra_skills": [], "missing": []}
    if len(results) > 1:
        # texts[0] = plain reading, texts[1] = column-by-column reading (only for two-column PDFs)
        best = 0 if is_label_layout(texts[0]) else 1
        if not results[best]["fields"]:
            best = 1 - best
    else:
        best = 0
    primary = results[best]
    for k, r in enumerate(results):
        if k == best:
            continue
        for key, val in r["fields"].items():
            primary["fields"].setdefault(key, val)
    wanted = {"summary": "summary", "qualification": "qualifications", "skills_expertise": "skills",
              "sector_experience": "sectors", "certifications": "certifications",
              "achievements": "achievements", "total_experience": "total experience"}
    primary["missing"] = [label for key, label in wanted.items() if key not in primary["fields"]]
    return primary
