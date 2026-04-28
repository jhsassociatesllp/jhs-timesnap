// static/appraisal/script.js

const API_URL   = "";
const empId     = localStorage.getItem("loggedInEmployeeId") || "";
const token     = localStorage.getItem("access_token") || "";

// ── Auth guard ────────────────────────────────────────────────────────────────
if (!token) window.location.href = "/static/login.html";

// ── State ─────────────────────────────────────────────────────────────────────
let _questions       = null;   // { common: [], role: [], category: "" }
let _currentStatus   = null;   // "not_started" | "draft" | "submitted"
let _draftAnswers    = {};     // answers loaded from existing draft
let _currentPeriod   = "";
let _isReadOnly      = false;  // true when submitted
let _empDetails      = {};     // from /employees

// ── Helpers ───────────────────────────────────────────────────────────────────
const getHeaders = () => ({
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
});

function showLoading(msg = "Loading…") {
    const b = document.getElementById("loadingBar");
    if (b) { b.textContent = msg; b.style.display = "block"; }
}
function hideLoading() {
    const b = document.getElementById("loadingBar");
    if (b) b.style.display = "none";
}

function showPopup(msg, isError = false) {
    const p = document.getElementById("popup");
    const m = document.getElementById("popupMsg");
    if (!p || !m) return;
    m.textContent = msg;
    p.classList.remove("error", "show");
    if (isError) p.classList.add("error");
    p.classList.add("show"); p.style.display = "block";
    p.style.opacity = "1"; p.style.visibility = "visible";
    setTimeout(() => {
        p.classList.remove("show");
        p.style.opacity = "0"; p.style.visibility = "hidden";
        setTimeout(() => p.style.display = "none", 400);
    }, 3500);
}
function closePopup() {
    const p = document.getElementById("popup");
    if (p) { p.classList.remove("show"); p.style.display = "none"; }
}

function toggleNav() {
    document.getElementById("navMenu")?.classList.toggle("active");
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function showTab(tab) {
    ["form", "history", "status"].forEach(t => {
        document.getElementById(t + "Tab").style.display    = t === tab ? "block" : "none";
        document.getElementById(t + "Tab").classList.toggle("active", t === tab);
        const link = document.getElementById("tab" + t.charAt(0).toUpperCase() + t.slice(1));
        if (link) link.classList.toggle("active", t === tab);
    });

    if (tab === "history") loadHistory();
    if (tab === "status")  loadStatus();

    document.getElementById("navMenu")?.classList.remove("active");
}

// ── Initialise ────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
    showLoading("Checking eligibility…");
    try {
        // Verify session
        const sv = await fetch(`${API_URL}/verify_session`, {
            method: "POST", headers: getHeaders(),
        });
        if (!sv.ok) throw new Error("Session invalid");

        // Get period
        const pp = await fetch(`${API_URL}/appraisal/period`, { headers: getHeaders() });
        const pd = await pp.json();
        _currentPeriod = pd.period || "";
        document.getElementById("headerSub").textContent =
            `Annual Performance Review — ${_currentPeriod}`;

        // Check eligibility
        const er = await fetch(`${API_URL}/appraisal/eligibility/${empId}`, { headers: getHeaders() });
        const ed = await er.json();

        if (!ed.eligible) {
            document.getElementById("notEligibleBlock").style.display = "flex";
            document.getElementById("notEligibleMsg").textContent     = ed.reason;
            hideLoading();
            return;
        }

        // Load employee details for display
        const emps = await fetch(`${API_URL}/employees`, { headers: getHeaders() });
        const empsData = await emps.json();
        _empDetails = empsData.find(e => String(e.EmpID) === String(empId)) || {};

        // Populate info bar
        _fillEmpBar();
        document.getElementById("empInfoBar").style.display = "grid";

        // Check current status (draft or submitted)
        const sr = await fetch(`${API_URL}/appraisal/status/${empId}`, { headers: getHeaders() });
        const sd = await sr.json();
        _currentStatus  = sd.status;
        _draftAnswers   = sd.answers || {};

        if (_currentStatus === "submitted") {
            _isReadOnly = true;
            document.getElementById("submittedBanner").style.display = "flex";
            document.getElementById("submittedPeriod").textContent   = _currentPeriod;
            document.getElementById("formActions").style.display     = "none";
        }

        // Load questions
        const qr = await fetch(`${API_URL}/appraisal/questions/${empId}`, { headers: getHeaders() });
        _questions = await qr.json();

        // Build form
        buildForm(_questions, _draftAnswers, _isReadOnly);
        document.getElementById("formBody").style.display = "block";

    } catch (err) {
        console.error("Init error:", err);
        showPopup("Failed to initialise KRA. Please refresh.", true);
    } finally {
        hideLoading();
    }
});

function _fillEmpBar() {
    const name  = _empDetails["Name"] || _empDetails["Emp Name"] || "—";
    const desig = _empDetails["Designation Name"] || _empDetails["Designation"] || "—";
    const part  = _empDetails["Partner"] || "—";
    const mgr   = _empDetails["ReportingEmpName"] || "—";

    const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
    set("empId",     empId);
    set("empName",   name);
    set("empDesig",  desig);
    set("empPart",   part);
    set("empMgr",    mgr);
    set("empPeriod", _currentPeriod);
}

// ── Build Form ────────────────────────────────────────────────────────────────
function buildForm(questions, savedAnswers, readOnly) {
    const container = document.getElementById("formSections");
    container.innerHTML = "";

    // Group common questions by section
    const commonGroups = _groupBySection(questions.common);
    // Group role questions by section
    const roleGroups   = _groupBySection(questions.role);

    // Render common sections
    Object.entries(commonGroups).forEach(([section, qs]) => {
        container.appendChild(_buildSection(section, qs, savedAnswers, readOnly, false));
    });

    // Separator
    if (questions.role && questions.role.length > 0) {
        const sep = document.createElement("div");
        sep.style.cssText = "margin:2rem 0 1.5rem;padding:.8rem 1.2rem;background:linear-gradient(135deg,#11998e,#38ef7d);border-radius:10px;color:white;font-weight:700;font-size:.95rem;display:flex;align-items:center;gap:.6rem;";
        sep.innerHTML = `<i class="fas fa-user-tag"></i> Role-Specific Questions`;
        container.appendChild(sep);

        Object.entries(roleGroups).forEach(([section, qs]) => {
            container.appendChild(_buildSection(section, qs, savedAnswers, readOnly, true));
        });
    }
}

function _groupBySection(questions) {
    const groups = {};
    questions.forEach(q => {
        const s = q.section || "General";
        if (!groups[s]) groups[s] = [];
        groups[s].push(q);
    });
    return groups;
}

function _buildSection(sectionName, questions, savedAnswers, readOnly, isRole) {
    const div = document.createElement("div");
    div.className = "q-section" + (isRole ? " role-section" : "");

    const titleIcon = isRole ? "fas fa-user-tag" : "fas fa-clipboard-list";
    const title = document.createElement("div");
    title.className   = "q-section-title";
    title.innerHTML   = `<i class="${titleIcon}"></i> ${sectionName}`;
    div.appendChild(title);

    questions.forEach(q => {
        div.appendChild(_buildQuestion(q, savedAnswers[q.id], readOnly));
    });

    return div;
}

// All yes/no variant types from the KRA sheet
const YES_NO_TYPES = new Set([
    "yes_no", "yes_no_example", "yes_no_reason", "yes_no_description",
    "yes_no_details", "yes_no_justification", "yes_no_notes",
    "yes_no_explanation", "yes_no_comments", "yes_no_number",
]);

// hint label per yes/no sub-type
const YES_NO_HINTS = {
    "yes_no_example":       "Please provide an example if Yes.",
    "yes_no_reason":        "If No, please state the reason.",
    "yes_no_description":   "If Yes, please describe briefly.",
    "yes_no_details":       "If Yes, please provide details.",
    "yes_no_justification": "Please provide a brief justification.",
    "yes_no_notes":         "Add notes if there are any gaps.",
    "yes_no_explanation":   "Please explain briefly.",
    "yes_no_comments":      "Please add any comments.",
};

function _buildQuestion(q, savedValue, readOnly) {
    const block = document.createElement("div");
    block.className = "question-block";

    const label = document.createElement("label");
    label.className = "q-label";
    label.setAttribute("for", "q_" + q.id);
    label.innerHTML = q.question + (q.required ? ' <span class="required-star">*</span>' : "");
    if (q.response_hint) {
        label.innerHTML += ` <span class="q-hint">(${q.response_hint})</span>`;
    }
    block.appendChild(label);

    // ── textarea ──
    if (q.type === "textarea" || q.type === "text") {
        const ta = document.createElement("textarea");
        ta.className   = "q-textarea";
        ta.id          = "q_" + q.id;
        ta.name        = q.id;
        ta.rows        = q.type === "text" ? 1 : 4;
        ta.placeholder = readOnly ? "—" : "Write your answer here…";
        ta.value       = savedValue || "";
        ta.disabled    = readOnly;
        block.appendChild(ta);
    }

    // ── rating (0–5 scale) ──
    else if (q.type === "rating") {
        const outer = document.createElement("div");
        outer.style.cssText = "display:flex;flex-direction:column;gap:.5rem;";

        // Scale label
        const scaleLabel = document.createElement("p");
        scaleLabel.className = "rating-scale-label";
        scaleLabel.innerHTML = `<span class="scale-low">0 — Lowest</span><span class="scale-high">5 — Highest</span>`;
        outer.appendChild(scaleLabel);

        const wrapper = document.createElement("div");
        wrapper.className = "star-rating" + (readOnly ? " disabled" : "");
        wrapper.setAttribute("data-qid", q.id);

        // 5 → 0 (RTL CSS trick renders right-to-left visually as 0–5)
        for (let i = 5; i >= 0; i--) {
            const radio = document.createElement("input");
            radio.type     = "radio";
            radio.name     = "q_" + q.id;
            radio.id       = `q_${q.id}_${i}`;
            radio.value    = i;
            radio.disabled = readOnly;
            if (String(savedValue) === String(i)) radio.checked = true;

            const lbl = document.createElement("label");
            lbl.setAttribute("for", `q_${q.id}_${i}`);
            lbl.innerHTML = i === 0 ? "☆" : "★";
            lbl.title     = i === 0 ? "0 — Lowest" : `${i} out of 5`;
            wrapper.appendChild(radio);
            wrapper.appendChild(lbl);
        }

        const val = document.createElement("span");
        val.className   = "rating-value";
        val.id          = "rval_" + q.id;
        val.textContent = savedValue !== undefined && savedValue !== "" ? `${savedValue}/5` : "";
        wrapper.appendChild(val);

        wrapper.addEventListener("change", e => {
            if (e.target.type === "radio")
                document.getElementById("rval_" + q.id).textContent = `${e.target.value}/5`;
        });

        outer.appendChild(wrapper);
        block.appendChild(outer);
    }

    // ── yes_no_number (Yes/No + conditional count input) ──
    else if (q.type === "yes_no_number") {
        const radioWrapper = document.createElement("div");
        radioWrapper.className = "yes-no-wrapper";

        // Keep direct references — don't use querySelector before appending
        let yesRadio = null;
        let noRadio  = null;

        ["Yes", "No"].forEach(choice => {
            const rb = document.createElement("input");
            rb.type     = "radio";
            rb.name     = `q_${q.id}_yn`;
            rb.id       = `q_${q.id}_${choice}`;
            rb.value    = choice;
            rb.disabled = readOnly;

            const savedStr = String(savedValue || "").toLowerCase();
            if (savedStr.startsWith(choice.toLowerCase())) rb.checked = true;

            if (choice === "Yes") yesRadio = rb;
            else                  noRadio  = rb;

            const lbl = document.createElement("label");
            lbl.setAttribute("for", `q_${q.id}_${choice}`);
            lbl.textContent = choice;
            lbl.className   = "yn-label";

            radioWrapper.appendChild(rb);
            radioWrapper.appendChild(lbl);
        });

        block.appendChild(radioWrapper);

        // Count wrapper — hidden by default, shown when Yes is selected
        const countWrapper = document.createElement("div");
        countWrapper.className = "yn-count-wrapper";
        countWrapper.id        = `q_${q.id}_count_wrapper`;

        const countLabel = document.createElement("label");
        countLabel.textContent = "If Yes, enter the number:";
        countLabel.className   = "yn-hint";
        countLabel.setAttribute("for", `q_${q.id}_count`);

        const countInput = document.createElement("input");
        countInput.type        = "number";
        countInput.className   = "q-input yn-count-input";
        countInput.id          = `q_${q.id}_count`;
        countInput.name        = `q_${q.id}_count`;
        countInput.min         = 0;
        countInput.placeholder = "Enter count";
        countInput.disabled    = readOnly;

        // Restore saved count (format: "Yes — 3")
        const savedCount = String(savedValue || "").match(/\d+/);
        if (savedCount) countInput.value = savedCount[0];

        countWrapper.appendChild(countLabel);
        countWrapper.appendChild(countInput);
        block.appendChild(countWrapper);

        // Set initial visibility using direct references
        const savedYes = String(savedValue || "").toLowerCase().startsWith("yes");
        countWrapper.style.display = (savedYes && !readOnly) || (savedYes && readOnly) ? "flex" : "none";

        // Listen for change — use direct references, not querySelector
        yesRadio.addEventListener("change", () => {
            countWrapper.style.display = "flex";
            countInput.focus();
        });
        noRadio.addEventListener("change", () => {
            countWrapper.style.display = "none";
            countInput.value = "";
        });
    }

    // ── number (plain numeric input) ──
    else if (q.type === "number") {
        const inp = document.createElement("input");
        inp.type        = "number";
        inp.className   = "q-input";
        inp.id          = "q_" + q.id;
        inp.name        = q.id;
        inp.min         = 0;
        inp.placeholder = "Enter a number";
        inp.value       = savedValue ?? "";
        inp.disabled    = readOnly;
        block.appendChild(inp);
    }

    // ── number_dropdown (select from list) ──
    else if (q.type === "number_dropdown") {
        const sel = document.createElement("select");
        sel.className = "q-select";
        sel.id        = "q_" + q.id;
        sel.name      = q.id;
        sel.disabled  = readOnly;

        const def = document.createElement("option");
        def.value       = "";
        def.textContent = "— Select —";
        sel.appendChild(def);

        (q.options || []).forEach(opt => {
            const o = document.createElement("option");
            o.value       = opt;
            o.textContent = opt;
            if (String(savedValue) === String(opt)) o.selected = true;
            sel.appendChild(o);
        });

        block.appendChild(sel);
    }

    // ── dropdown (generic options list) ──
    else if (q.type === "dropdown") {
        const sel = document.createElement("select");
        sel.className = "q-select";
        sel.id        = "q_" + q.id;
        sel.name      = q.id;
        sel.disabled  = readOnly;

        const def = document.createElement("option");
        def.value       = "";
        def.textContent = "— Select —";
        sel.appendChild(def);

        (q.options || []).forEach(opt => {
            const o = document.createElement("option");
            o.value       = opt;
            o.textContent = opt;
            if (savedValue === opt) o.selected = true;
            sel.appendChild(o);
        });

        block.appendChild(sel);
    }

    // ── yes_no and all its variants ──
    else if (YES_NO_TYPES.has(q.type)) {
        // Radio Yes / No
        const radioWrapper = document.createElement("div");
        radioWrapper.className = "yes-no-wrapper";

        ["Yes", "No"].forEach(choice => {
            const rb = document.createElement("input");
            rb.type     = "radio";
            rb.name     = `q_${q.id}_yn`;
            rb.id       = `q_${q.id}_${choice}`;
            rb.value    = choice;
            rb.disabled = readOnly;

            const savedStr = String(savedValue || "").toLowerCase();
            if (savedStr.startsWith(choice.toLowerCase())) rb.checked = true;

            const lbl = document.createElement("label");
            lbl.setAttribute("for", `q_${q.id}_${choice}`);
            lbl.textContent = choice;
            lbl.className   = "yn-label";

            radioWrapper.appendChild(rb);
            radioWrapper.appendChild(lbl);
        });

        block.appendChild(radioWrapper);

        // For types that need an explanation, add a textarea
        if (q.type !== "yes_no") {
            const hint = YES_NO_HINTS[q.type] || "Please elaborate if needed.";
            const hintEl = document.createElement("p");
            hintEl.className   = "yn-hint";
            hintEl.textContent = hint;
            block.appendChild(hintEl);

            const ta = document.createElement("textarea");
            ta.className   = "q-textarea yn-textarea";
            ta.id          = `q_${q.id}_reason`;
            ta.name        = `q_${q.id}_reason`;
            ta.rows        = 2;
            ta.placeholder = readOnly ? "—" : hint;
            ta.disabled    = readOnly;

            // Restore saved reason part (format: "Yes — explanation")
            const savedReason = String(savedValue || "").replace(/^(yes|no)\s*[—-]?\s*/i, "");
            ta.value = savedReason;

            block.appendChild(ta);
        }
    }

    return block;
}

// ── Collect answers from DOM ──────────────────────────────────────────────────
function collectAnswers() {
    const answers = {};
    if (!_questions) return answers;

    const allQs = [..._questions.common, ...(_questions.role || [])];

    allQs.forEach(q => {
        const qtype = q.type;

        if (qtype === "rating") {
            const checked = document.querySelector(`input[name="q_${q.id}"]:checked`);
            if (checked) answers[q.id] = Number(checked.value);

        } else if (qtype === "textarea" || qtype === "text") {
            const el = document.getElementById("q_" + q.id);
            if (el) answers[q.id] = el.value.trim();

        } else if (qtype === "number") {
            const el = document.getElementById("q_" + q.id);
            if (el && el.value !== "") answers[q.id] = Number(el.value);

        } else if (qtype === "number_dropdown" || qtype === "dropdown") {
            const el = document.getElementById("q_" + q.id);
            if (el && el.value !== "") answers[q.id] = el.value;

        } else if (YES_NO_TYPES.has(qtype)) {
            const checked = document.querySelector(`input[name="q_${q.id}_yn"]:checked`);
            if (checked) {
                let val = checked.value;
                if (qtype === "yes_no_number") {
                    const countEl = document.getElementById(`q_${q.id}_count`);
                    const countVal = countEl?.value?.trim();
                    if (val === "Yes" && countVal) val = `Yes — ${countVal}`;
                } else if (qtype !== "yes_no") {
                    const reason = document.getElementById(`q_${q.id}_reason`);
                    const reasonText = reason?.value?.trim();
                    if (reasonText) val = `${val} — ${reasonText}`;
                }
                answers[q.id] = val;
            }
        }
    });

    return answers;
}

// ── Validate required questions ───────────────────────────────────────────────
function validateAnswers(answers) {
    if (!_questions) return [];
    const allQs  = [..._questions.common, ...(_questions.role || [])];
    const missing = [];

    allQs.filter(q => q.required).forEach(q => {
        const ans = answers[q.id];
        const isEmpty = ans === undefined || ans === null || ans === ""
            || (typeof ans === "string" && !ans.trim());

        if (isEmpty) {
            missing.push(q.question.substring(0, 55) + "…");

            // Highlight field
            const qtype = q.type;
            if (qtype === "rating") {
                const wrapper = document.querySelector(`.star-rating[data-qid="${q.id}"]`);
                if (wrapper) wrapper.style.outline = "2px solid #e74c3c";
            } else if (qtype === "textarea" || qtype === "text") {
                document.getElementById("q_" + q.id)?.classList.add("error");
            } else if (qtype === "number" || qtype === "number_dropdown" || qtype === "dropdown") {
                const el = document.getElementById("q_" + q.id);
                if (el) el.style.outline = "2px solid #e74c3c";
            } else if (YES_NO_TYPES.has(qtype)) {
                const yesEl = document.getElementById(`q_${q.id}_Yes`);
                const noEl  = document.getElementById(`q_${q.id}_No`);
                [yesEl, noEl].forEach(el => { if (el) el.style.outline = "2px solid #e74c3c"; });
            }
        } else {
            // Clear errors
            const qtype = q.type;
            if (qtype === "rating") {
                const wrapper = document.querySelector(`.star-rating[data-qid="${q.id}"]`);
                if (wrapper) wrapper.style.outline = "none";
            } else if (qtype === "textarea" || qtype === "text") {
                document.getElementById("q_" + q.id)?.classList.remove("error");
            } else if (qtype === "number" || qtype === "number_dropdown" || qtype === "dropdown") {
                const el = document.getElementById("q_" + q.id);
                if (el) el.style.outline = "none";
            } else if (YES_NO_TYPES.has(qtype)) {
                const yesEl = document.getElementById(`q_${q.id}_Yes`);
                const noEl  = document.getElementById(`q_${q.id}_No`);
                [yesEl, noEl].forEach(el => { if (el) el.style.outline = "none"; });
            }
        }
    });

    return missing;
}

// ── Save (draft or submit) ────────────────────────────────────────────────────
async function saveAppraisal(status) {
    if (_isReadOnly) { showPopup("KRA already submitted.", true); return; }

    const answers = collectAnswers();

    if (status === "submitted") {
        const missing = validateAnswers(answers);
        if (missing.length > 0) {
            showPopup(`Please answer all required questions before submitting.\nMissing: ${missing.slice(0,3).join("; ")}${missing.length > 3 ? "…" : ""}`, true);
            return;
        }
    }

    showLoading(status === "submitted" ? "Submitting…" : "Saving draft…");

    try {
        const res = await fetch(`${API_URL}/appraisal/save`, {
            method:  "POST",
            headers: getHeaders(),
            body:    JSON.stringify({
                employeeId: empId,
                period:     _currentPeriod,
                answers:    answers,
                status:     status,
            }),
        });

        const data = await res.json();
        hideLoading();

        if (!res.ok || !data.success) {
            showPopup(data.detail || data.message || "Save failed.", true);
            return;
        }

        showPopup(data.message);
        _draftAnswers  = answers;
        _currentStatus = status;

        if (status === "submitted") {
            _isReadOnly = true;
            document.getElementById("submittedBanner").style.display = "flex";
            document.getElementById("submittedPeriod").textContent   = _currentPeriod;
            document.getElementById("formActions").style.display     = "none";
            // Re-render form as read-only
            buildForm(_questions, answers, true);
        }

    } catch (err) {
        hideLoading();
        console.error("saveAppraisal:", err);
        showPopup("Network error. Please try again.", true);
    }
}

function confirmSubmit() {
    if (_isReadOnly) return;
    // Quick check for any answers first
    const answers = collectAnswers();
    const missing = validateAnswers(answers);
    if (missing.length > 0) {
        showPopup(`Please answer all required questions.\nMissing: ${missing.slice(0,3).join("; ")}${missing.length > 3 ? "…" : ""}`, true);
        return;
    }
    document.getElementById("submitConfirm").style.display = "block";
}
function closeSubmitConfirm() {
    document.getElementById("submitConfirm").style.display = "none";
}
function doSubmit() {
    closeSubmitConfirm();
    saveAppraisal("submitted");
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
    const container = document.getElementById("historyContent");
    container.innerHTML = `<p class="empty-msg">Loading…</p>`;

    try {
        const res  = await fetch(`${API_URL}/appraisal/my/${empId}`, { headers: getHeaders() });
        const data = await res.json();

        if (!data.success || !data.data || data.data.length === 0) {
            container.innerHTML = `<p class="empty-msg">No KRA records found.</p>`;
            return;
        }

        container.innerHTML = "";

        // Sort newest first
        const records = [...data.data].sort((a, b) =>
            (b.updatedAt || "").localeCompare(a.updatedAt || "")
        );

        records.forEach(record => {
            container.appendChild(_buildHistoryCard(record));
        });

    } catch (err) {
        console.error("loadHistory:", err);
        container.innerHTML = `<p class="empty-msg">Failed to load history.</p>`;
    }
}

function _buildHistoryCard(record) {
    const card = document.createElement("div");
    card.className = `history-card ${record.status}`;

    const isSubmitted = record.status === "submitted";
    const updatedStr  = record.updatedAt
        ? new Date(record.updatedAt).toLocaleDateString("en-IN", { day:"2-digit", month:"short", year:"numeric" })
        : "—";

    let actionsHTML = "";
    if (record.status === "draft") {
        actionsHTML = `<button class="edit-draft-btn" onclick="loadDraftIntoForm('${record.id}')">
            <i class="fas fa-edit"></i> Continue Editing
        </button>`;
    }

    card.innerHTML = `
        <div class="history-card-header">
            <span class="history-period"><i class="fas fa-calendar-alt"></i> ${record.period || "—"}</span>
            <span class="history-badge ${isSubmitted ? "badge-submitted" : "badge-draft"}">
                ${isSubmitted ? "Submitted" : "Draft"}
            </span>
        </div>
        <div class="history-meta">
            Designation: <strong>${record.designation || "—"}</strong> &nbsp;|&nbsp;
            Last updated: <strong>${updatedStr}</strong>
        </div>
        ${actionsHTML}
        <div class="history-answers" id="ha_${record.id}">
            <button onclick="toggleAnswers('${record.id}')" style="background:none;border:1px solid var(--border-color);padding:.4rem 1rem;border-radius:8px;cursor:pointer;font-size:.85rem;color:var(--text-light);margin-top:.5rem;">
                <i class="fas fa-chevron-down"></i> View Answers
            </button>
            <div id="ha_body_${record.id}" style="display:none;margin-top:1rem;"></div>
        </div>
    `;

    return card;
}

function toggleAnswers(recordId) {
    const body = document.getElementById("ha_body_" + recordId);
    if (!body) return;

    if (body.style.display === "none") {
        body.style.display = "block";
        // Need to populate it — find the record from existing DOM data
        // Simpler: re-fetch from API for this specific record
        _populateAnswerView(recordId, body);
    } else {
        body.style.display = "none";
    }
}

async function _populateAnswerView(recordId, container) {
    if (container.innerHTML.trim() !== "") return; // already populated

    try {
        const res  = await fetch(`${API_URL}/appraisal/my/${empId}`, { headers: getHeaders() });
        const data = await res.json();
        const record = data.data?.find(r => r.id === recordId);
        if (!record || !record.answers) { container.textContent = "No answers found."; return; }

        if (!_questions) { container.textContent = "Questions not loaded."; return; }

        const allQs = [..._questions.common, ...(_questions.role || [])];
        const groups = {};
        allQs.forEach(q => {
            const s = q.section || "General";
            if (!groups[s]) groups[s] = [];
            groups[s].push(q);
        });

        Object.entries(groups).forEach(([section, qs]) => {
            const secDiv = document.createElement("div");
            secDiv.className = "ha-section";
            secDiv.innerHTML = `<div class="ha-section-title">${section}</div>`;

            qs.forEach(q => {
                const ans = record.answers[q.id];
                if (ans === undefined || ans === null || ans === "") return;
                const row = document.createElement("div");
                row.className = "ha-row";
        const displayAns = q.type === "rating" ? `${ans}/5 ★` : String(ans);
                row.innerHTML = `<div class="ha-q">${q.question}</div><div class="ha-a">${displayAns}</div>`;
                secDiv.appendChild(row);
            });

            container.appendChild(secDiv);
        });

    } catch (err) {
        container.textContent = "Failed to load answers.";
    }
}

async function loadDraftIntoForm(recordId) {
    // Switch to form tab
    showTab("form");

    try {
        const res  = await fetch(`${API_URL}/appraisal/my/${empId}`, { headers: getHeaders() });
        const data = await res.json();
        const record = data.data?.find(r => r.id === recordId);
        if (!record) { showPopup("Draft not found.", true); return; }

        _draftAnswers = record.answers || {};
        buildForm(_questions, _draftAnswers, false);
        document.getElementById("formBody").style.display = "block";
        showPopup("Draft loaded. You can continue editing.");
    } catch (err) {
        showPopup("Failed to load draft.", true);
    }
}

// ── Status tab ────────────────────────────────────────────────────────────────
async function loadStatus() {
    const container = document.getElementById("statusContent");
    container.innerHTML = `<p class="empty-msg">Loading…</p>`;

    try {
        const [eligRes, statusRes] = await Promise.all([
            fetch(`${API_URL}/appraisal/eligibility/${empId}`, { headers: getHeaders() }),
            fetch(`${API_URL}/appraisal/status/${empId}`,      { headers: getHeaders() }),
        ]);

        const eligData   = await eligRes.json();
        const statusData = await statusRes.json();

        container.innerHTML = "";

        // Eligibility card
        const eligCard = document.createElement("div");
        eligCard.className = "status-card";
        eligCard.innerHTML = `
            <h3><i class="fas fa-user-check"></i> Eligibility</h3>
            <div class="status-row">
                <span class="status-key">Status</span>
                <span class="status-val">
                    <span class="pill ${eligData.eligible ? "pill-submitted" : "pill-pending"}">
                        ${eligData.eligible ? "Eligible" : "Not Eligible"}
                    </span>
                </span>
            </div>
            <div class="status-row">
                <span class="status-key">Date of Joining</span>
                <span class="status-val">${eligData.doj || "—"}</span>
            </div>
            <div class="status-row">
                <span class="status-key">1-Year Completion</span>
                <span class="status-val">${eligData.one_year_date || "—"}</span>
            </div>
            <div class="status-row">
                <span class="status-key">Reason</span>
                <span class="status-val" style="font-weight:400;color:var(--text-light)">${eligData.reason}</span>
            </div>
        `;
        container.appendChild(eligCard);

        // Submission card
        const subCard = document.createElement("div");
        subCard.className = "status-card";
        const pillClass = {
            "submitted":   "pill-submitted",
            "draft":       "pill-draft",
            "not_started": "pill-pending",
        }[statusData.status] || "pill-pending";

        const statusLabel = {
            "submitted":   "Submitted",
            "draft":       "Draft Saved",
            "not_started": "Not Started",
        }[statusData.status] || statusData.status;

        const updatedAt = statusData.updatedAt
            ? new Date(statusData.updatedAt).toLocaleString("en-IN")
            : "—";

        subCard.innerHTML = `
            <h3><i class="fas fa-paper-plane"></i> KRA Submission — ${_currentPeriod}</h3>
            <div class="status-row">
                <span class="status-key">Current Status</span>
                <span class="status-val"><span class="pill ${pillClass}">${statusLabel}</span></span>
            </div>
            <div class="status-row">
                <span class="status-key">Period</span>
                <span class="status-val">${statusData.period || "—"}</span>
            </div>
            <div class="status-row">
                <span class="status-key">Last Updated</span>
                <span class="status-val">${updatedAt}</span>
            </div>
            <div class="status-row">
                <span class="status-key">Next Steps</span>
                <span class="status-val" style="font-weight:400;color:var(--text-light)">
                    ${statusData.status === "submitted"
                        ? "Your KRA is under review by your reporting manager and partner."
                        : statusData.status === "draft"
                        ? "You have a saved draft. Go to the Form tab to complete and submit."
                        : "You haven't started your KRA yet. Go to the Form tab to begin."}
                </span>
            </div>
        `;
        container.appendChild(subCard);

    } catch (err) {
        console.error("loadStatus:", err);
        container.innerHTML = `<p class="empty-msg">Failed to load status.</p>`;
    }
}

// ── Logout ────────────────────────────────────────────────────────────────────
function confirmLogout() {
    document.getElementById("logoutConfirm").style.display = "block";
}
function doLogout() {
    localStorage.clear(); sessionStorage.clear();
    window.location.href = "/static/login.html";
}