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
// Only fetch the period to update the header subtitle.
// All form/eligibility logic is disabled since the form is closed.

document.addEventListener("DOMContentLoaded", async () => {
    showLoading("Loading…");
    try {
        // Verify session
        const sv = await fetch(`${API_URL}/verify_session`, {
            method: "POST", headers: getHeaders(),
        });
        if (!sv.ok) throw new Error("Session invalid");

        // Get period for header display only
        const pp = await fetch(`${API_URL}/appraisal/period`, { headers: getHeaders() });
        const pd = await pp.json();
        _currentPeriod = pd.period || "";
        document.getElementById("headerSub").textContent =
            `Annual Performance Review — ${_currentPeriod}`;

    } catch (err) {
        console.error("Init error:", err);
    } finally {
        hideLoading();
    }
});

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

        // If questions aren't loaded yet, load them now for history display
        if (!_questions) {
            try {
                const qr = await fetch(`${API_URL}/appraisal/questions/${empId}`, { headers: getHeaders() });
                _questions = await qr.json();
            } catch {
                container.textContent = "Questions not loaded.";
                return;
            }
        }

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