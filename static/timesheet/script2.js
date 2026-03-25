// static/timesheet/script.js
// ─────────────────────────────────────────────────────────────────────────────
// Path changes from old script.js:
//   /save_timesheets                    → still works (legacy alias in main.py)
//   /timesheets/:id                     → still works (legacy alias)
//   /employees                          → still works (legacy alias)
//   /clients                            → still works (legacy alias)
//   /get_employee_projects/:id          → still works (legacy alias)
//   /check_reporting_manager/:id        → still works (legacy alias)
//   /get_timesheet/:id                  → still works (legacy alias)
//   /get_pending_employees/:id          → still works (legacy alias)
//   /get_approved_employees/:id         → still works (legacy alias)
//   /get_rejected_employees/:id         → still works (legacy alias)
//   /approve_timesheet                  → still works (legacy alias)
//   /reject_timesheet                   → still works (legacy alias)
//   /approve_all_timesheets             → still works (legacy alias)
//   /get-par-current-status             → still works (in main.py)
//
// All URLs are intentionally kept identical to the old script so the legacy
// aliases in main.py route them correctly — zero JS changes needed.
// ─────────────────────────────────────────────────────────────────────────────

console.log("✅ static/timesheet/script.js loaded");

let sectionCount = 0;
let employeeData = [];
let clientData = [];
let weekOptions = [];
let loggedInEmployeeId = localStorage.getItem("loggedInEmployeeId") || "";
const API_URL = "";

let copiedData = null;
let currentRow = null;
let isEditingHistory = false;
let currentEntryId = null;
let historyEntries = [];
let pollingInterval = null;
let weekOptionsInitialized = false;

let employeeProjects = { clients: [], projects: [], project_codes: [] };

let weekOptionsReady = false;
window.weekOptions = [];

// ── Auth guard ────────────────────────────────────────────────────────────────
if (!localStorage.getItem("access_token")) {
    window.location.href = "/static/login.html";
}

// ── Debounce ──────────────────────────────────────────────────────────────────
function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => { clearTimeout(timeout); func(...args); }, wait);
    };
}
const debouncedRefreshWeeks = debounce(refreshPayrollWeeks, 1000);

// ── Token helpers ─────────────────────────────────────────────────────────────
window.addEventListener("load", () => {
    const local = localStorage.getItem("access_token") || localStorage.getItem("token");
    const session = sessionStorage.getItem("token");
    if (!local && session) {
        localStorage.setItem("token", session);
        localStorage.setItem("access_token", session);
    }
});

const getHeaders = (requireAuth = true) => {
    const token = localStorage.getItem("access_token") || localStorage.getItem("token") || sessionStorage.getItem("token");
    if (requireAuth && !token) {
        localStorage.clear(); sessionStorage.clear();
        window.location.href = "/static/login.html";
        return { "Content-Type": "application/json" };
    }
    const base = { "Content-Type": "application/json" };
    return token ? { ...base, Authorization: `Bearer ${token}` } : base;
};

async function safeFetchJson(endpoint, opts = {}) {
    try {
        const res = await fetch(`${API_URL}${endpoint}`, { headers: getHeaders(opts.requireAuth !== false), ...(opts || {}) });
        if (res.status === 401) { localStorage.clear(); sessionStorage.clear(); window.location.href = "/static/login.html"; return []; }
        if (!res.ok) throw new Error(`Fetch ${endpoint} failed: ${res.status}`);
        return await res.json();
    } catch (err) { console.error(`Error fetching ${endpoint}:`, err); return []; }
}

// ── Polling ───────────────────────────────────────────────────────────────────
function startPayrollPolling() {
    if (pollingInterval) clearInterval(pollingInterval);
    pollingInterval = setInterval(() => { if (document.visibilityState === "visible") refreshPayrollWeeks(); }, 300000);
}
window.addEventListener("beforeunload", () => { if (pollingInterval) clearInterval(pollingInterval); });

// ── Week helpers ──────────────────────────────────────────────────────────────
function getPayrollWindow() {
    const today = new Date();
    let start, end;
    if (today.getDate() >= 21) {
        start = new Date(today.getFullYear(), today.getMonth(), 21);
        end   = new Date(today.getFullYear(), today.getMonth() + 1, 20);
    } else {
        start = new Date(today.getFullYear(), today.getMonth() - 1, 21);
        end   = new Date(today.getFullYear(), today.getMonth(), 20);
    }
    return { start, end };
}

function generateWeekOptions(start, end) {
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const weeks = [];
    let weekNum = 1;
    let current = new Date(start);

    const firstWeekEnd = new Date(current);
    const daysToSunday = 7 - firstWeekEnd.getDay();
    firstWeekEnd.setDate(firstWeekEnd.getDate() + (daysToSunday === 7 ? 0 : daysToSunday));
    weeks.push(makeWeekObject(current, firstWeekEnd, weekNum++, months));

    current = new Date(firstWeekEnd);
    current.setDate(current.getDate() + 1);

    while (current < end) {
        const ws = new Date(current);
        const we = new Date(ws);
        we.setDate(ws.getDate() + 6);
        if (we > end) we.setTime(end.getTime());
        weeks.push(makeWeekObject(ws, we, weekNum++, months));
        current = new Date(we);
        current.setDate(current.getDate() + 1);
    }
    return weeks;
}

function makeWeekObject(start, end, weekNum, months) {
    const wsDay = start.getDate().toString().padStart(2, "0");
    const wsMonth = months[start.getMonth()];
    const weDay = end.getDate().toString().padStart(2, "0");
    const weMonth = months[end.getMonth()];
    const value = `${wsDay}/${start.getMonth()+1}/${start.getFullYear()} to ${weDay}/${end.getMonth()+1}/${end.getFullYear()}`;
    const text  = `Week ${weekNum} (${wsDay} ${wsMonth} - ${weDay} ${weMonth})`;
    return { value, text, start, end };
}

window._currentPayrollWindow = null;

async function initWeekOptions() {
    if (weekOptionsInitialized) return;
    try {
        const res  = await fetch("/get-par-current-status", { headers: getHeaders() });
        const data = await res.json();
        let start, end;
        if (data && data.start && data.end) {
            start = new Date(data.start); end = new Date(data.end);
        } else {
            ({ start, end } = getPayrollWindow());
        }
        window._currentPayrollWindow = { start: start.toISOString(), end: end.toISOString() };
        window.weekOptions = generateWeekOptions(start, end);
        weekOptionsInitialized = true;
        weekOptionsReady = true;
        startPayrollPolling();
        console.log(`✅ Payroll: ${start.toDateString()} → ${end.toDateString()}`);
    } catch (err) {
        console.error("❌ initWeekOptions:", err);
        const { start, end } = getPayrollWindow();
        window._currentPayrollWindow = { start: start.toISOString(), end: end.toISOString() };
        window.weekOptions = generateWeekOptions(start, end);
        weekOptionsInitialized = true;
    }
}

async function refreshPayrollWeeks() {
    try {
        const res = await fetch("/get-par-current-status", { headers: getHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        let startISO = data && data.start ? new Date(data.start).toISOString() : null;
        let endISO   = data && data.end   ? new Date(data.end).toISOString()   : null;
        if (!startISO || !endISO) { const l = getPayrollWindow(); startISO = l.start.toISOString(); endISO = l.end.toISOString(); }
        const hash = startISO + "|" + endISO;
        const old  = window._currentPayrollWindow ? window._currentPayrollWindow.start + "|" + window._currentPayrollWindow.end : null;
        if (old === hash) return;
        window._currentPayrollWindow = { start: startISO, end: endISO };
        window.weekOptions = generateWeekOptions(new Date(startISO), new Date(endISO));
        document.querySelectorAll('select[id^="weekPeriod_"]').forEach(sel => {
            const prev = sel.value; sel.innerHTML = "";
            window.weekOptions.forEach(w => { const o = document.createElement("option"); o.value = w.value; o.textContent = w.text; sel.appendChild(o); });
            if (prev && Array.from(sel.options).find(o => o.value === prev)) sel.value = prev;
        });
        showPopup("Payroll weeks updated by admin");
    } catch (err) { console.error("❌ refreshPayrollWeeks:", err); }
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
    const token = localStorage.getItem("access_token");
    if (!token) { window.location.href = "/static/login.html"; return; }

    try {
        const res = await fetch(`${API_URL}/verify_session`, { method: "POST", headers: getHeaders() });
        if (!res.ok) throw new Error("Session invalid");
    } catch {
        localStorage.removeItem("access_token");
        localStorage.removeItem("loggedInEmployeeId");
        window.location.href = "/static/login.html";
        return;
    }

    showLoading("Fetching initial data...");
    try {
        employeeData = await safeFetchJson("/employees");
        clientData   = await safeFetchJson("/clients");
        await loadEmployeeProjects();
        await initWeekOptions();
        populateEmployeeInfo();
        addWeekSection();
        await checkUserRole();
        showSection("timesheet");
    } catch (err) {
        console.error("Init error:", err);
        showPopup("Failed to initialize. See console.", true);
    } finally {
        hideLoading();
    }
});

// ── Employee projects ─────────────────────────────────────────────────────────
async function loadEmployeeProjects() {
    if (!loggedInEmployeeId) return;
    try {
        const res = await fetch(`${API_URL}/get_employee_projects/${loggedInEmployeeId}`, { headers: getHeaders() });
        if (res.ok) { employeeProjects = await res.json(); }
    } catch (err) { console.error("loadEmployeeProjects:", err); }
}

// ── PAR status ────────────────────────────────────────────────────────────────
async function checkPARStatus() {
    try {
        const res = await fetch(`${API_URL}/get-par-current-status`, { headers: getHeaders() });
        if (!res.ok) return false;
        const data = await res.json();
        return data.par_status === "enable";
    } catch { return false; }
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function showLoading(text = "Loading...") { const b = document.getElementById("loadingBar"); if (b) { b.style.display = "block"; b.textContent = text; } }
function hideLoading() { const b = document.getElementById("loadingBar"); if (b) b.style.display = "none"; }
function showError(msg) { const d = document.getElementById("errorMessage"); if (!d) { showPopup(msg, true); return; } d.textContent = msg; d.style.display = "block"; }

function showPopup(message, isError = false) {
    const popup = document.getElementById("successPopup");
    const msg   = document.getElementById("popupMessage");
    msg.innerHTML = isError ? `<i class='fas fa-times-circle'></i> ${message}` : `<i class='fas fa-check-circle'></i> ${message}`;
    popup.classList.remove("error", "show");
    if (isError) popup.classList.add("error");
    popup.style.visibility = "visible";
    popup.style.opacity    = "1";
    popup.classList.add("show");
    setTimeout(() => { popup.classList.remove("show"); popup.style.opacity = "0"; popup.style.visibility = "hidden"; }, 3000);
}
function closePopup() { const p = document.getElementById("successPopup"); if (p) p.classList.remove("show"); }

// ── Employee info ─────────────────────────────────────────────────────────────
function populateEmployeeInfo() {
    if (!loggedInEmployeeId) return;
    const emp = employeeData.find(e => String(e.EmpID) === String(loggedInEmployeeId));
    if (!emp) {
        console.warn("Employee not found in employeeData for ID:", loggedInEmployeeId);
        return;
    }
    console.log("Employee record from DB:", emp); // helpful for spotting field name mismatches

    // Support multiple possible field name variants from the DB
    const name = emp["Name"] || emp["Emp Name"] || emp["EmployeeName"] || emp["employee_name"] || "";
    const designation = emp["Designation Name"] || emp["Designation"] || emp["designation"] || "";
    const partner = emp["Partner"] || emp["partner"] || "";
    const reportingManager = emp["ReportingEmpName"] || emp["Reporting Manager"] || emp["reportingManager"] || "";
    const genderRaw = emp["Gender"] || emp["gender"] || "";
    const gender = genderRaw === "F" ? "Female" : genderRaw === "M" ? "Male" : genderRaw;

    const map = {
        employeeId:      emp["EmpID"] || "",
        employeeName:    name,
        designation:     designation,
        partner:         partner,
        reportingManager: reportingManager,
        gender:          gender,
    };

    Object.entries(map).forEach(([id, val]) => {
        const el = document.getElementById(id);
        if (el) el.value = val;
    });
}

// ── Smart dropdowns ───────────────────────────────────────────────────────────
function createSmartDropdown(type, container, currentValue = "", currentClient = "") {
    let options = [];
    if (type === "client") options = employeeProjects.clients || [];
    else if (type === "project") {
        if (currentClient && employeeProjects.projects_by_client?.[currentClient])
            options = employeeProjects.projects_by_client[currentClient].map(p => p.project_name);
    }

    const select = document.createElement("select");
    select.className = `${type}-field form-input smart-dropdown`;
    select.style.width = "100%";

    const def = document.createElement("option"); def.value = ""; def.textContent = `Select ${type.replace("_"," ")}`; select.appendChild(def);
    options.forEach(opt => { const o = document.createElement("option"); o.value = opt; o.textContent = opt; if (opt === currentValue) o.selected = true; select.appendChild(o); });

    if (type !== "project_code") {
        const custom = document.createElement("option"); custom.value = "__TYPE_HERE__"; custom.textContent = "✏️ Type here (custom entry)"; custom.style.fontStyle = "italic"; select.appendChild(custom);
    }

    select.addEventListener("change", function () {
        const row = this.closest("tr");
        if (this.value === "__TYPE_HERE__") {
            const input = document.createElement("input"); input.type = "text"; input.className = `${type}-field form-input`; input.placeholder = `Enter ${type.replace("_"," ")}`; input.value = currentValue; input.style.width = "calc(100% - 35px)";
            const backBtn = document.createElement("button"); backBtn.className = "back-to-dropdown-btn"; backBtn.innerHTML = '<i class="fas fa-list"></i>'; backBtn.title = "Back to dropdown"; backBtn.type = "button"; backBtn.style.cssText = "margin-left:5px;padding:6px 10px;cursor:pointer;";
            backBtn.onclick = () => {
                const isModal = container.closest("#modalOverlay") !== null;
                let cv = "";
                if (type === "project") cv = isModal ? (document.querySelector("#modalClientContainer select")?.value || "") : (row ? getFieldValue(row, ".col-client") : "");
                const nd = createSmartDropdown(type, container, input.value || "", cv);
                container.innerHTML = ""; container.appendChild(nd);
                if (input.value && !Array.from(nd.options).some(o => o.value === input.value && o.value !== "" && o.value !== "__TYPE_HERE__")) { nd.value = "__TYPE_HERE__"; nd.dispatchEvent(new Event("change")); }
                _resetProjectCode(container, nd.value, cv, isModal);
            };
            container.innerHTML = "";
            const w = document.createElement("div"); w.style.cssText = "display:flex;align-items:center;gap:5px;"; w.appendChild(input); w.appendChild(backBtn); container.appendChild(w);
            input.focus(); input.addEventListener("input", updateSummary);
            if (type === "project") { const isModal = container.closest("#modalOverlay") !== null; _makeProjectCodeEditable(isModal, row); }
        } else if (type === "client" && row) {
            const pc = row.querySelector(".col-project"); const pcc = row.querySelector(".col-project-code");
            if (pc) { const pi = pc.querySelector("input"); pc.innerHTML = ""; pc.appendChild(pi ? (() => { const i = document.createElement("input"); i.type = "text"; i.className = "project form-input"; i.placeholder = "Enter project"; return i; })() : createSmartDropdown("project", pc, "", this.value)); }
            if (pcc) { pcc.innerHTML = ""; pcc.appendChild(createReadonlyProjectCode("", "Auto-filled")); }
        } else if (type === "project" && row) {
            const pcc = row.querySelector(".col-project-code"); if (!pcc) return; pcc.innerHTML = "";
            const cv = getFieldValue(row, ".col-client");
            if (cv && employeeProjects.projects_by_client?.[cv]) { const pd = employeeProjects.projects_by_client[cv].find(p => p.project_name === this.value); if (pd) pcc.appendChild(createReadonlyProjectCode(pd.project_code || "")); else pcc.appendChild(createReadonlyProjectCode("", "Auto-filled")); }
        }
    });
    select.addEventListener("change", updateSummary);
    return select;
}

function _makeProjectCodeEditable(isModal, row) {
    let pcc = isModal ? document.getElementById("modalProjectCodeContainer") : row?.querySelector(".col-project-code");
    if (!pcc) return;
    pcc.innerHTML = "";
    const ci = document.createElement("input"); ci.type = "text"; ci.className = "project-code form-input"; ci.placeholder = "Enter Project Code"; ci.readOnly = false;
    if (isModal) ci.id = "modalProjectCodeInput";
    pcc.appendChild(ci);
}

function _resetProjectCode(container, projectVal, clientVal, isModal) {
    let pcc = isModal ? document.getElementById("modalProjectCodeContainer") : container.closest("tr")?.querySelector(".col-project-code");
    if (!pcc) return;
    pcc.innerHTML = "";
    if (!projectVal || projectVal === "__TYPE_HERE__") { pcc.appendChild(createReadonlyProjectCode("", projectVal === "__TYPE_HERE__" ? "Enter Project Code" : "Auto-filled")); return; }
    if (clientVal && employeeProjects.projects_by_client?.[clientVal]) { const m = employeeProjects.projects_by_client[clientVal].find(p => p.project_name === projectVal); if (m) { pcc.appendChild(createReadonlyProjectCode(m.project_code || "")); return; } }
    pcc.appendChild(createReadonlyProjectCode("", "Auto-filled"));
}

function createReadonlyProjectCode(value = "", placeholder = "Auto-filled") {
    const w = document.createElement("div"); w.style.cssText = "position:relative;width:100%;";
    const i = document.createElement("input"); i.type = "text"; i.className = "project-code form-input";
    i.value = value || ""; i.placeholder = placeholder; i.readOnly = true; i.disabled = true;
    i.setAttribute("readonly","readonly"); i.style.cssText = "background-color:#f0f0f0;color:"+(value?"#444":"#999")+";border:1px solid #ccc;cursor:not-allowed;";
    ["keydown","keypress","input","paste"].forEach(ev => i.addEventListener(ev, e => { e.preventDefault(); e.stopPropagation(); }));
    w.appendChild(i); return w;
}

function setupSmartDropdowns(row) {
    const cc = row.querySelector(".col-client"); const pc = row.querySelector(".col-project"); const pcc = row.querySelector(".col-project-code");
    if (cc) { cc.innerHTML = ""; cc.appendChild(createSmartDropdown("client", cc)); }
    if (pc) { pc.innerHTML = ""; pc.appendChild(createSmartDropdown("project", pc, "", "")); }
    if (pcc) { pcc.innerHTML = ""; pcc.appendChild(createReadonlyProjectCode("", "Auto-filled")); }
}

function getFieldValue(row, className) {
    const cell = row.querySelector(className); if (!cell) return "";
    const sel = cell.querySelector("select"); const inp = cell.querySelector("input");
    if (sel && sel.value !== "__TYPE_HERE__") return sel.value;
    if (inp) return inp.value;
    return "";
}

function setFieldValue(row, className, value) {
    const cell = row.querySelector(className); if (!cell) return;
    const sel = cell.querySelector("select"); const inp = cell.querySelector("input");
    if (sel) {
        if (Array.from(sel.options).some(o => o.value === value)) { sel.value = value; sel.dispatchEvent(new Event("change", { bubbles: true })); }
        else if (value) { sel.value = "__TYPE_HERE__"; sel.dispatchEvent(new Event("change", { bubbles: true })); setTimeout(() => { const ni = cell.querySelector("input"); if (ni) ni.value = value; }, 0); }
    } else if (inp) inp.value = value;
}

// ── Week sections ─────────────────────────────────────────────────────────────
function addWeekSection() {
    if (typeof sectionCount === "undefined") window.sectionCount = 0;
    sectionCount++;
    const sectionsDiv = document.getElementById("timesheetSections");
    if (!sectionsDiv) { console.error("timesheetSections not found"); return; }

    const sectionId = `section_${sectionCount}`;
    const section = document.createElement("div");
    section.className = "timesheet-section"; section.id = sectionId;

    const weekDiv = document.createElement("div"); weekDiv.className = "week-period form-group"; weekDiv.innerHTML = `<label>Week Period ${sectionCount}</label>`;
    const select = document.createElement("select"); select.id = `weekPeriod_${sectionCount}`; select.className = "form-control";
    select.style.cssText = "font-weight:500;font-size:18px;padding:15px;color:#2c3e50;";
    select.onchange = () => { updateSummary(); updateExistingRowDates(sectionId); };

    if (window.weekOptions && window.weekOptions.length > 0) {
        window.weekOptions.forEach(w => { const o = document.createElement("option"); o.value = w.value; o.textContent = w.text; o.style.fontWeight = "500"; select.appendChild(o); });
    } else { const o = document.createElement("option"); o.value = ""; o.textContent = "No week periods found"; select.appendChild(o); }

    weekDiv.appendChild(select);
    const delBtn = document.createElement("button"); delBtn.className = "delete-week-btn"; delBtn.textContent = "Delete Week"; delBtn.onclick = () => deleteWeekSection(sectionId); weekDiv.appendChild(delBtn);
    section.appendChild(weekDiv);

    const tw = document.createElement("div"); tw.className = "table-responsive";
    tw.innerHTML = `<table class="timesheet-table"><thead><tr>
        <th>S.No</th><th>Add</th><th>Action</th><th>Date</th><th>Location</th>
        <th>Project Start</th><th>Project End</th><th>Client</th><th>Project</th>
        <th>Project Code</th><th>Reporting Manager</th><th>Activity</th>
        <th>Project Hours</th><th>Billable</th><th>Remarks</th><th>Delete</th>
    </tr></thead><tbody id="timesheetBody_${sectionCount}"></tbody></table>`;
    section.appendChild(tw);

    const bd = document.createElement("div"); bd.className = "button-container";
    bd.innerHTML = `<button class="add-row-btn" onclick="addRow('${sectionId}')">+ Add New Entry</button>`;
    section.appendChild(bd);

    sectionsDiv.appendChild(section);
    addRow(sectionId);
    updateExistingRowDates(sectionId);
}

function updateExistingRowDates(sectionId) {
    const secNum = sectionId.split("_")[1];
    const tbody  = document.getElementById(`timesheetBody_${secNum}`);
    const weekSel = document.getElementById(`weekPeriod_${secNum}`);
    if (!tbody || !weekSel || !weekSel.value) return;
    const sel = window.weekOptions.find(w => w.value === weekSel.value);
    if (!sel) return;
    const startISO = new Date(sel.start).toISOString().split("T")[0];
    const endISO   = new Date(sel.end).toISOString().split("T")[0];
    tbody.querySelectorAll(".date-field").forEach(inp => {
        inp.min = startISO; inp.max = endISO;
        if (!inp.value || inp.value < startISO || inp.value > endISO) inp.value = startISO;
        validateDate(inp);
    });
}

function addRow(sectionId, specificDate = null) {
    const sectionNum = sectionId.split("_")[1];
    const tbody = document.getElementById(`timesheetBody_${sectionNum}`);
    if (!tbody) { console.error("Table body not found", sectionId); return; }
    const weekSelect = document.getElementById(`weekPeriod_${sectionNum}`);
    if (!weekSelect || !weekSelect.value) { showPopup("Please select a week period first!", true); return; }
    const selectedWeek = window.weekOptions.find(w => w.value === weekSelect.value);
    if (!selectedWeek) { showPopup("Invalid week selected", true); return; }

    const weekStart = new Date(selectedWeek.start);
    const weekEnd   = new Date(selectedWeek.end);
    const dateInputs = tbody.querySelectorAll(".date-field");
    let nextDate;
    if (dateInputs.length === 0) nextDate = new Date(weekStart);
    else { const ld = new Date(dateInputs[dateInputs.length - 1].value || weekStart); nextDate = new Date(ld); nextDate.setDate(ld.getDate() + 1); }
    if (nextDate > weekEnd) nextDate = new Date(weekEnd);
    const defaultDate = nextDate.toISOString().split("T")[0];

    const rowIndex = tbody.querySelectorAll("tr").length + 1;
    const tr = document.createElement("tr");
    tr.innerHTML = `
        <td class="col-sno">${rowIndex}</td>
        <td class="col-add"><button class="eye-btn" onclick="openModal(this)"><i class="fas fa-eye"></i></button></td>
        <td class="col-action">
            <button class="copy-btn" onclick="copyRow(this)">Copy</button>
            <button class="paste-btn" onclick="pasteRow(this)">Paste</button>
        </td>
        <td class="col-date form-input"><input type="date" class="date-field form-input" value="${defaultDate}" onchange="validateDate(this); updateSummary()"></td>
        <td class="col-location"><select class="location-select form-input" onchange="updateSummary()">
            <option value="Office">Office</option><option value="Client Site">Client Site</option>
            <option value="Work From Home">Work From Home</option><option value="Field Work">Field Work</option>
        </select></td>
        <td class="col-project-start"><input type="time" class="project-start form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
        <td class="col-project-end"><input type="time" class="project-end form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
        <td class="col-client"></td>
        <td class="col-project"></td>
        <td class="col-project-code"></td>
        <td class="col-reporting-manager"><input type="text" class="reporting-manager-field form-input" placeholder="Enter Reporting Manager"></td>
        <td class="col-activity" style="min-width:200px;"><input type="text" class="activity-field form-input" placeholder="Enter Activity" oninput="updateSummary()"></td>
        <td class="col-project-hours"><input type="number" class="project-hours-field form-input" readonly></td>
        <td class="col-billable"><select class="billable-select form-input" onchange="updateSummary()">
            <option value="Yes">Billable</option><option value="No">Non-Billable</option>
        </select></td>
        <td class="col-remarks"><input type="text" class="remarks-field form-input" placeholder="Additional notes"></td>
        <td class="col-delete"><button class="delete-btn" onclick="deleteRow(this)">Delete</button></td>
    `;
    tbody.appendChild(tr);
    setupSmartDropdowns(tr);
    setTimeout(() => tr.querySelector("input, select")?.focus(), 100);
    updateRowNumbers(tbody.id);
    updateSummary();
}

function updateRowNumbers(tbodyId) {
    const tbody = document.getElementById(tbodyId); if (!tbody) return;
    tbody.querySelectorAll("tr").forEach((r, i) => { const s = r.querySelector(".col-sno"); if (s) s.textContent = i + 1; });
}
function deleteRow(btn) { const row = btn.closest("tr"); if (!row) return; const tbody = row.closest("tbody"); row.remove(); updateRowNumbers(tbody.id); updateSummary(); }
function deleteWeekSection(sectionId) { if (!confirm("Delete this week section?")) return; document.getElementById(sectionId)?.remove(); updateSummary(); }

// ── Hours calculation ─────────────────────────────────────────────────────────
function calculateHours(row) {
    if (!row) return;
    const start = row.querySelector(".project-start")?.value;
    const end   = row.querySelector(".project-end")?.value;
    const hf    = row.querySelector(".project-hours-field");
    if (!start || !end) { if (hf) hf.value = ""; updateSummary(); return; }
    const [sh,sm] = start.split(":").map(Number);
    const [eh,em] = end.split(":").map(Number);
    let s = sh*60+sm, e = eh*60+em;
    if (e < s) e += 24*60;
    if (hf) hf.value = ((e - s) / 60).toFixed(2);
    updateSummary();
}

function validateTimes(rowOrModal, isModal = false) {
    try {
        if (!rowOrModal && !isModal) return true;
        if (isModal) {
            const ps = document.getElementById("modalInput3"); const pe = document.getElementById("modalInput4");
            if (ps && pe && ps.value && pe.value) {
                const [sh,sm] = ps.value.split(":").map(Number); const [eh,em] = pe.value.split(":").map(Number);
                if (eh*60+em <= sh*60+sm) { pe.classList.add("validation-error"); showPopup("Project End must be later than Start", true); return false; } else pe.classList.remove("validation-error");
            }
        } else {
            const ps = rowOrModal.querySelector(".project-start"); const pe = rowOrModal.querySelector(".project-end");
            if (ps && pe && ps.value && pe.value) {
                const [sh,sm] = ps.value.split(":").map(Number); const [eh,em] = pe.value.split(":").map(Number);
                if (eh*60+em <= sh*60+sm) { pe.classList.add("validation-error"); showPopup("Project End must be later than Start", true); return false; } else pe.classList.remove("validation-error");
            }
        }
        return true;
    } catch { return true; }
}

function validateDate(input) {
    if (!input || !input.value) { input?.classList.remove("validation-error"); return; }
    if (!window.weekOptions || window.weekOptions.length === 0) { input.classList.remove("validation-error"); return; }
    const section = input.closest(".timesheet-section"); if (!section) return;
    const ws = section.querySelector('select[id^="weekPeriod_"]'); if (!ws || !ws.value) { input.classList.remove("validation-error"); return; }
    const sel = window.weekOptions.find(w => w.value === ws.value); if (!sel) { input.classList.remove("validation-error"); return; }
    const id = new Date(input.value); const sd = new Date(sel.start); const ed = new Date(sel.end);
    [id,sd,ed].forEach(d => d.setHours(0,0,0,0));
    if (id < sd || id > ed) {
        input.classList.add("validation-error");
        showPopup(`Invalid Date! Only dates from ${sd.toLocaleDateString("en-GB")} to ${ed.toLocaleDateString("en-GB")} are allowed.`, true);
    } else input.classList.remove("validation-error");
}

function updateSummary() {
    let total = 0, billable = 0, nonBillable = 0;
    document.querySelectorAll(".timesheet-section tbody tr").forEach(tr => {
        const h = parseFloat(tr.querySelector(".project-hours-field")?.value) || 0;
        total += h;
        const b = tr.querySelector(".billable-select")?.value;
        if (b === "Yes") billable += h; else if (b === "No") nonBillable += h;
    });
    const te = document.querySelector(".summary-section .total-hours .value");
    const be = document.querySelector(".summary-section .billable-hours .value");
    const nb = document.querySelector(".summary-section .non-billable-hours .value");
    if (te) te.textContent = total.toFixed(2);
    if (be) be.textContent = billable.toFixed(2);
    if (nb) nb.textContent = nonBillable.toFixed(2);
}

// ── Copy / Paste ──────────────────────────────────────────────────────────────
function copyRow(button) {
    const row = button.closest("tr"); if (!row) return;
    copiedData = { date: row.querySelector(".date-field")?.value||"", location: row.querySelector(".location-select")?.value||"", projectStart: row.querySelector(".project-start")?.value||"", projectEnd: row.querySelector(".project-end")?.value||"", client: getFieldValue(row,".col-client"), project: getFieldValue(row,".col-project"), projectCode: getFieldValue(row,".col-project-code"), reportingManager: row.querySelector(".reporting-manager-field")?.value||"", activity: row.querySelector(".activity-field")?.value||"", billable: row.querySelector(".billable-select")?.value||"", remarks: row.querySelector(".remarks-field")?.value||"" };
    showPopup("Row copied!");
}
function pasteRow(button) {
    if (!copiedData) { showPopup("No copied row found", true); return; }
    const row = button.closest("tr"); if (!row) return;
    const df = row.querySelector(".date-field"); if (df) df.value = copiedData.date;
    const lf = row.querySelector(".location-select"); if (lf) lf.value = copiedData.location;
    const ps = row.querySelector(".project-start"); if (ps) ps.value = copiedData.projectStart;
    const pe = row.querySelector(".project-end"); if (pe) pe.value = copiedData.projectEnd;
    setFieldValue(row,".col-client",copiedData.client); setFieldValue(row,".col-project",copiedData.project); setFieldValue(row,".col-project-code",copiedData.projectCode);
    const rm = row.querySelector(".reporting-manager-field"); if (rm) rm.value = copiedData.reportingManager;
    const af = row.querySelector(".activity-field"); if (af) af.value = copiedData.activity;
    const bf = row.querySelector(".billable-select"); if (bf) bf.value = copiedData.billable;
    const rf = row.querySelector(".remarks-field"); if (rf) rf.value = copiedData.remarks;
    calculateHours(row); updateSummary(); showPopup("Row pasted!");
}

// ── Modal ─────────────────────────────────────────────────────────────────────
function openModal(button) {
    isEditingHistory = false; currentRow = button.closest("tr"); currentEntryId = currentRow.getAttribute("data-entry-id");
    const modal = document.getElementById("modalOverlay"); if (!modal) return;
    modal.style.display = "flex";

    document.getElementById("modalInput1").value = currentRow.querySelector(".date-field")?.value||"";
    document.getElementById("modalInput2").value = currentRow.querySelector(".location-select")?.value||"";
    document.getElementById("modalInput3").value = currentRow.querySelector(".project-start")?.value||"";
    document.getElementById("modalInput4").value = currentRow.querySelector(".project-end")?.value||"";

    const cv = getFieldValue(currentRow,".col-client"); const pv = getFieldValue(currentRow,".col-project"); const pcv = getFieldValue(currentRow,".col-project-code");
    const cc = document.getElementById("modalClientContainer"); cc.innerHTML = ""; const cd = createSmartDropdown("client",cc,cv); cc.appendChild(cd);
    cd.addEventListener("change", function() { updateModalProjectDropdown(this.value,""); });
    const pc = document.getElementById("modalProjectContainer"); pc.innerHTML = ""; const pd = createSmartDropdown("project",pc,pv,cv); pc.appendChild(pd);
    pd.addEventListener("change", function() { updateModalProjectCode(cc.querySelector("select")?.value, this.value); });
    const pcc = document.getElementById("modalProjectCodeContainer"); pcc.innerHTML = ""; const pci = document.createElement("input"); pci.type="text"; pci.id="modalProjectCodeInput"; pci.className="form-input"; pci.value=pcv; pci.readOnly=true; pci.style.backgroundColor="#f0f0f0"; pcc.appendChild(pci);

    document.getElementById("modalInput8").value = currentRow.querySelector(".reporting-manager-field")?.value||"";
    document.getElementById("modalInput9").value = currentRow.querySelector(".activity-field")?.value||"";
    document.getElementById("modalInput10").value = currentRow.querySelector(".project-hours-field")?.value||"";
    document.getElementById("modalInput11").value = currentRow.querySelector(".billable-select")?.value||"";
    document.getElementById("modalInput12").value = currentRow.querySelector(".remarks-field")?.value||"";
    updateModalHours();

    const ab = document.getElementById("modalAddBtn"); ab.innerHTML = '<i class="fas fa-check"></i> Save'; ab.onclick = saveModalEntry;
    const cb = document.getElementById("modalCancelBtn"); cb.innerHTML = '<i class="fas fa-times"></i> Cancel'; cb.onclick = closeModal;
}

function updateModalProjectDropdown(client, proj = "") {
    const pc = document.getElementById("modalProjectContainer"); if (!pc) return;
    pc.innerHTML = ""; const pd = createSmartDropdown("project",pc,proj,client); pc.appendChild(pd);
    pd.addEventListener("change", function() { updateModalProjectCode(client, this.value); });
    const pcc = document.getElementById("modalProjectCodeContainer"); if (pcc) { pcc.innerHTML = ""; const i = document.createElement("input"); i.type="text"; i.id="modalProjectCodeInput"; i.className="form-input"; i.value=""; i.readOnly=true; i.placeholder="Auto-filled"; i.style.backgroundColor="#f0f0f0"; pcc.appendChild(i); }
}

function updateModalProjectCode(clientValue, projectValue) {
    const pci = document.getElementById("modalProjectCodeInput"); if (!pci) return;
    if (projectValue === "__TYPE_HERE__") { pci.value=""; pci.readOnly=false; pci.placeholder="Enter Project Code"; pci.style.backgroundColor=""; return; }
    if (clientValue && employeeProjects.projects_by_client?.[clientValue]) {
        const pd = employeeProjects.projects_by_client[clientValue].find(p => p.project_name === projectValue);
        if (pd) { pci.value=pd.project_code; pci.readOnly=true; pci.style.backgroundColor="#f0f0f0"; }
    }
}

function saveModalEntry() {
    if (!currentRow) return;
    const df = currentRow.querySelector(".date-field"); if (df) df.value = document.getElementById("modalInput1").value;
    const lf = currentRow.querySelector(".location-select"); if (lf) lf.value = document.getElementById("modalInput2").value;
    const ps = currentRow.querySelector(".project-start"); if (ps) ps.value = document.getElementById("modalInput3").value;
    const pe = currentRow.querySelector(".project-end"); if (pe) pe.value = document.getElementById("modalInput4").value;
    const cc = document.getElementById("modalClientContainer"); const cv = cc?.querySelector("select")?.value || cc?.querySelector("input")?.value || "";
    const pc = document.getElementById("modalProjectContainer"); const pv = pc?.querySelector("select")?.value || pc?.querySelector("input")?.value || "";
    const pcv = document.getElementById("modalProjectCodeInput")?.value || "";
    setFieldValue(currentRow,".col-client",cv); setFieldValue(currentRow,".col-project",pv); setFieldValue(currentRow,".col-project-code",pcv);
    const rm = currentRow.querySelector(".reporting-manager-field"); if (rm) rm.value = document.getElementById("modalInput8").value;
    const af = currentRow.querySelector(".activity-field"); if (af) af.value = document.getElementById("modalInput9").value;
    const hf = currentRow.querySelector(".project-hours-field"); if (hf) hf.value = document.getElementById("modalInput10").value;
    const bf = currentRow.querySelector(".billable-select"); if (bf) bf.value = document.getElementById("modalInput11").value;
    const rf = currentRow.querySelector(".remarks-field"); if (rf) rf.value = document.getElementById("modalInput12").value;
    calculateHours(currentRow); validateDate(currentRow.querySelector(".date-field")); closeModal(); updateSummary();
}

function closeModal() { const m = document.getElementById("modalOverlay"); if (m) m.style.display = "none"; currentRow = null; isEditingHistory = false; currentEntryId = null; }

function updateModalHours() {
    const ps = document.getElementById("modalInput3")?.value; const pe = document.getElementById("modalInput4")?.value; const hf = document.getElementById("modalInput10");
    if (ps && pe && hf) { const [sh,sm] = ps.split(":").map(Number); const [eh,em] = pe.split(":").map(Number); let s=sh*60+sm, e=eh*60+em; if (e<s) e+=24*60; hf.value = ((e-s)/60).toFixed(2); }
}

function validateModalDate(dateInput) {
    if (!dateInput || !currentRow) return;
    const section = currentRow.closest(".timesheet-section"); if (!section) return;
    const ws = section.querySelector(".week-period select"); const sel = weekOptions.find(o => o.value === ws.value); if (!sel) return;
    const str = (d) => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
    const startStr = str(sel.start); const endStr = str(sel.end);
    if (dateInput.value < startStr || dateInput.value > endStr) { dateInput.classList.add("validation-error"); showPopup("Please select a date within the specified week.", true); }
    else dateInput.classList.remove("validation-error");
}

// ── Save to Mongo ─────────────────────────────────────────────────────────────
async function saveDataToMongo() {
    showLoading("Saving data...");
    const employeeId = document.getElementById("employeeId").value.trim();
    if (!employeeId) { hideLoading(); showPopup("Please enter Employee ID", true); return; }

    const timesheetData = [];
    let hasError = false; const errorMessages = [];
    document.querySelectorAll(".timesheet-section").forEach((section, si) => {
        const weekPeriod = section.querySelector(".week-period select")?.value || "";
        if (!weekPeriod) { hasError = true; errorMessages.push(`Week ${si+1}: Please select a week period.`); }
        section.querySelectorAll("tbody tr").forEach((row, ri) => {
            const date = row.querySelector(".date-field")?.value;
            const client = getFieldValue(row,".col-client"); const project = getFieldValue(row,".col-project"); const projectCode = getFieldValue(row,".col-project-code");
            const reportingManager = row.querySelector(".reporting-manager-field")?.value;
            const activity = row.querySelector(".activity-field")?.value;
            const mandatory = { date, client, project, projectCode, reportingManager, activity,
                projectStart: row.querySelector(".project-start")?.value, projectEnd: row.querySelector(".project-end")?.value };
            for (const [f, v] of Object.entries(mandatory)) { if (!v || v.trim() === "") { hasError = true; errorMessages.push(`Row ${ri+1} (Week ${si+1}): ${f} is required.`); } }
            if (!date) return;
            timesheetData.push({
                employeeId, employeeName: document.getElementById("employeeName")?.value||"", designation: document.getElementById("designation")?.value||"",
                gender: document.getElementById("gender")?.value||"", partner: document.getElementById("partner")?.value||"",
                reportingManager: document.getElementById("reportingManager")?.value||"",
                weekPeriod, date, location: row.querySelector(".location-select")?.value,
                projectStartTime: row.querySelector(".project-start")?.value, projectEndTime: row.querySelector(".project-end")?.value,
                client, project, projectCode, reportingManagerEntry: reportingManager, activity,
                projectHours: row.querySelector(".project-hours-field")?.value||"0",
                billable: row.querySelector(".billable-select")?.value, remarks: row.querySelector(".remarks-field")?.value,
                hits: document.getElementById("hits")?.value||"", misses: document.getElementById("misses")?.value||"",
                feedback_hr: document.getElementById("feedback_hr")?.value||"", feedback_it: document.getElementById("feedback_it")?.value||"",
                feedback_crm: document.getElementById("feedback_crm")?.value||"", feedback_others: document.getElementById("feedback_others")?.value||"",
            });
        });
    });

    if (hasError) { hideLoading(); showPopup(errorMessages.join("\n"), true); return; }
    if (timesheetData.length === 0) { hideLoading(); showPopup("No valid entries to save.", true); return; }

    try {
        const token = localStorage.getItem("access_token");
        const res = await fetch(`${API_URL}/save_timesheets`, { method: "POST", headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` }, body: JSON.stringify(timesheetData) });
        const result = await res.json(); hideLoading();
        if (res.ok && result.success) { showPopup("Timesheet submitted successfully."); setTimeout(() => clearTimesheet(true), 1500); }
        else showPopup("Save failed: " + (result.message || "Unknown error"), true);
    } catch (err) { hideLoading(); console.error("Save error:", err); showPopup("Network error. Check console.", true); }
}

// ── History ───────────────────────────────────────────────────────────────────
async function loadHistory() {
    try {
        showLoading("Fetching History...");
        const res = await fetch(`${API_URL}/timesheets/${loggedInEmployeeId}`, { headers: getHeaders() });
        if (!res.ok) throw new Error("Failed to fetch history");
        const data = await res.json();
        historyEntries = Array.isArray(data.Data) ? data.Data : [];

        const hc = document.getElementById("historyContent"); hc.innerHTML = "";
        const te = document.querySelector(".history-summary .total-hours .value");
        const be = document.querySelector(".history-summary .billable-hours .value");
        const nb = document.querySelector(".history-summary .non-billable-hours .value");
        if (te) te.textContent = (data.totalHours||0).toFixed(2);
        if (be) be.textContent = (data.totalBillableHours||0).toFixed(2);
        if (nb) nb.textContent = (data.totalNonBillableHours||0).toFixed(2);

        if (!data.Data || data.Data.length === 0) { hc.innerHTML = "<p>No timesheet entries found.</p>"; hideLoading(); return; }

        const grouped = {};
        data.Data.forEach(e => { const w = e.weekPeriod||"No Week"; (grouped[w] = grouped[w]||[]).push(e); });

        Object.keys(grouped).forEach(week => {
            const wd = document.createElement("div"); wd.className = "history-week"; wd.innerHTML = `<h3>Week Period: ${week}</h3>`;
            const tw = document.createElement("div"); tw.className = "table-responsive";
            const t = document.createElement("table"); t.className = "timesheet-table history-table";
            t.innerHTML = `<thead><tr><th>S.No</th><th>Action</th><th>Date</th><th>Location</th><th>Project Start</th><th>Project End</th><th>Client</th><th>Project</th><th>Project Code</th><th>Reporting Manager</th><th>Activity</th><th>Project Hours</th><th>Billable</th><th>Remarks</th></tr></thead><tbody></tbody>`;
            const tb = t.querySelector("tbody");
            grouped[week].forEach((e, i) => {
                const tr = document.createElement("tr");
                tr.innerHTML = `<td>${i+1}</td><td style="min-width:120px;"><button class="action-btn edit-btn" onclick="editHistoryRow(this,'${e.id}')"><i class="fas fa-edit"></i> Edit</button><button class="action-btn delete-btn" onclick="deleteHistoryRow(this,'${e.id}')"><i class="fas fa-trash"></i> Delete</button></td>
                <td>${e.date||""}</td><td>${e.location||""}</td><td>${e.projectStartTime||""}</td><td>${e.projectEndTime||""}</td>
                <td>${e.client||""}</td><td>${e.project||""}</td><td>${e.projectCode||""}</td>
                <td>${e.reportingManagerEntry||""}</td><td>${e.activity||""}</td><td>${e.projectHours||""}</td><td>${e.billable||""}</td><td>${e.remarks||""}</td>`;
                tb.appendChild(tr);
            });
            tw.appendChild(t); wd.appendChild(tw); hc.appendChild(wd);

            const fd = document.createElement("div"); fd.className = "history-feedback";
            const f = grouped[week][0];
            fd.innerHTML = `<h4>Feedback for Week: ${week}</h4>
            <div class="feedback-item"><strong>3 HITS:</strong> ${f.hits||""}</div>
            <div class="feedback-item"><strong>3 MISSES:</strong> ${f.misses||""}</div>
            <div class="feedback-item"><strong>HR:</strong> ${f.feedback_hr||""}</div>
            <div class="feedback-item"><strong>IT:</strong> ${f.feedback_it||""}</div>
            <div class="feedback-item"><strong>CRM:</strong> ${f.feedback_crm||""}</div>
            <div class="feedback-item"><strong>Others:</strong> ${f.feedback_others||""}</div>`;
            hc.appendChild(fd);
        });
        hideLoading();
    } catch (err) { console.error("loadHistory:", err); hideLoading(); }
}

function editHistoryRow(button, entryId) {
    const modal = document.getElementById("modalOverlay"); const row = button.closest("tr"); if (!row || !modal) return;
    const cells = row.querySelectorAll("td");
    document.getElementById("modalInput1").value = cells[2].textContent.trim();
    document.getElementById("modalInput2").value = cells[3].textContent.trim();
    document.getElementById("modalInput3").value = cells[4].textContent.trim();
    document.getElementById("modalInput4").value = cells[5].textContent.trim();
    const cv = cells[6].textContent.trim(); const pv = cells[7].textContent.trim(); const pcv = cells[8].textContent.trim();
    const cc = document.getElementById("modalClientContainer"); cc.innerHTML = ""; const cd = createSmartDropdown("client",cc,cv); cc.appendChild(cd); cd.addEventListener("change", function() { updateModalProjectDropdown(this.value,""); });
    const pc = document.getElementById("modalProjectContainer"); pc.innerHTML = ""; const pd = createSmartDropdown("project",pc,pv,cv); pc.appendChild(pd); pd.addEventListener("change", function() { updateModalProjectCode(cc?.querySelector("select")?.value, this.value); });
    const pcc = document.getElementById("modalProjectCodeContainer"); pcc.innerHTML = ""; const pci = document.createElement("input"); pci.type="text"; pci.id="modalProjectCodeInput"; pci.className="form-input"; pci.value=pcv; pci.readOnly=true; pci.style.backgroundColor="#f0f0f0"; pcc.appendChild(pci);
    document.getElementById("modalInput8").value = cells[9].textContent.trim();
    document.getElementById("modalInput9").value = cells[10].textContent.trim();
    document.getElementById("modalInput10").value = cells[11].textContent.trim();
    document.getElementById("modalInput11").value = cells[12].textContent.trim();
    document.getElementById("modalInput12").value = cells[13].textContent.trim();
    isEditingHistory = true; currentEntryId = entryId; currentRow = row; modal.style.display = "flex";
    const ab = document.getElementById("modalAddBtn"); ab.textContent = "Update"; ab.onclick = updateHistoryEntry;
}

function updateHistoryEntry() {
    if (!currentEntryId || !currentRow) { showPopup("No entry selected", true); return; }
    const cc = document.getElementById("modalClientContainer"); const cv = cc?.querySelector("select")?.value || cc?.querySelector("input")?.value||"";
    const pc = document.getElementById("modalProjectContainer"); const pv = pc?.querySelector("select")?.value || pc?.querySelector("input")?.value||"";
    const pcv = document.getElementById("modalProjectCodeInput")?.value||"";
    const payload = {
        date: document.getElementById("modalInput1").value, location: document.getElementById("modalInput2").value,
        projectStartTime: document.getElementById("modalInput3").value, projectEndTime: document.getElementById("modalInput4").value,
        client: cv, project: pv, projectCode: pcv,
        reportingManagerEntry: document.getElementById("modalInput8").value,
        activity: document.getElementById("modalInput9").value, projectHours: document.getElementById("modalInput10").value,
        billable: document.getElementById("modalInput11").value, remarks: document.getElementById("modalInput12").value,
    };
    showLoading("Updating entry...");
    fetch(`${API_URL}/update_timesheet/${loggedInEmployeeId}/${currentEntryId}`, { method: "PUT", headers: getHeaders(), body: JSON.stringify(payload) })
        .then(r => r.json()).then(res => { hideLoading(); if (res?.success) { showPopup("Entry updated"); closeModal(); loadHistory(); } else showPopup("Failed to update", true); })
        .catch(err => { hideLoading(); console.error(err); showPopup("Error updating", true); });
}

function deleteHistoryRow(button, entryId) {
    if (!confirm("Delete this entry?")) return;
    showLoading("Deleting...");
    fetch(`${API_URL}/delete_timesheet/${loggedInEmployeeId}/${entryId}`, { method: "DELETE", headers: getHeaders() })
        .then(r => r.json()).then(res => { hideLoading(); if (res?.success) { showPopup("Entry deleted"); loadHistory(); } else showPopup("Failed to delete", true); })
        .catch(err => { hideLoading(); console.error(err); showPopup("Error deleting", true); });
}

// ── Role check ────────────────────────────────────────────────────────────────
async function checkUserRole() {
    try {
        const resMgr = await fetch(`${API_URL}/check_reporting_manager/${loggedInEmployeeId}`, { headers: getHeaders() });
        let isManager = false;
        if (resMgr.ok) { const js = await resMgr.json(); isManager = !!js.isManager; }
        let parDisabled = false;
        try {
            const parRes = await fetch(`${API_URL}/get-par-current-status`, { headers: getHeaders() });
            if (parRes.ok) { const pj = await parRes.json(); parDisabled = (pj.par_status || "disable") === "disable"; }
        } catch {}
        document.querySelectorAll(".manager-only").forEach(btn => { btn.style.display = (isManager && !parDisabled) ? "inline-block" : "none"; });
    } catch (err) { console.error("checkUserRole:", err); document.querySelectorAll(".manager-only").forEach(btn => btn.style.display="none"); }
}

// ── Manager lists ─────────────────────────────────────────────────────────────
function _parseList(result) { return Array.isArray(result.employees) ? result.employees : result.data || result.Data || []; }

async function loadPendingList() {
    try {
        const res = await fetch(`${API_URL}/get_pending_employees/${loggedInEmployeeId}`, { headers: getHeaders() });
        const data = _parseList(await res.json()); const tbody = document.getElementById("pendingTableBody"); if (!tbody) return;
        tbody.innerHTML = data.length ? "" : "<tr><td colspan='3'>No pending approvals</td></tr>";
        data.forEach(item => {
            const emp = item.timesheetData||{}; const id = item.employeeId||emp.employeeId||"N/A"; const name = emp.employeeName||"N/A";
            const tr = document.createElement("tr");
            tr.innerHTML = `<td>${id}</td><td><a href="#" class="employee-link" onclick="openEmployeeDetails('${id}')">${name}</a></td><td><button type="button" class="action-btn approve-btn"><i class="fas fa-check"></i> Approve</button><button type="button" class="action-btn reject-btn"><i class="fas fa-times"></i> Reject</button></td>`;
            tbody.appendChild(tr);
            tr.querySelector(".approve-btn").addEventListener("click", e => { e.preventDefault(); approveEmployee(id); });
            tr.querySelector(".reject-btn").addEventListener("click", e => { e.preventDefault(); rejectEmployee(id); });
        });
    } catch (err) { console.error("loadPendingList:", err); }
    updateApproveAllButtons();
}

async function loadApprovedList() {
    try {
        const res = await fetch(`${API_URL}/get_approved_employees/${loggedInEmployeeId}`, { headers: getHeaders() });
        const data = _parseList(await res.json()); const tbody = document.getElementById("approveTableBody"); if (!tbody) return;
        tbody.innerHTML = data.length ? "" : "<tr><td colspan='3'>No approved employees</td></tr>";
        data.forEach(item => {
            const emp = item.timesheetData||{}; const id = item.employeeId||emp.employeeId||"N/A"; const name = emp.employeeName||"N/A";
            const tr = document.createElement("tr");
            tr.innerHTML = `<td>${id}</td><td><a href="#" class="employee-link" onclick="openEmployeeDetails('${id}')">${name}</a></td><td><button class="action-btn reject-btn" onclick="rejectEmployee('${id}')"><i class="fas fa-times"></i> Reject</button></td>`;
            tbody.appendChild(tr);
        });
    } catch (err) { console.error("loadApprovedList:", err); }
}

async function loadRejectedList() {
    try {
        const res = await fetch(`${API_URL}/get_rejected_employees/${loggedInEmployeeId}`, { headers: getHeaders() });
        const data = _parseList(await res.json()); const tbody = document.getElementById("rejectedTableBody"); if (!tbody) return;
        tbody.innerHTML = data.length ? "" : "<tr><td colspan='3'>No rejected employees</td></tr>";
        data.forEach(item => {
            const emp = item.timesheetData||{}; const id = item.employeeId||emp.employeeId||"N/A"; const name = emp.employeeName||"N/A";
            const tr = document.createElement("tr");
            tr.innerHTML = `<td>${id}</td><td><a href="#" class="employee-link" onclick="openEmployeeDetails('${id}')">${name}</a></td><td><button class="action-btn approve-btn" onclick="approveEmployee('${id}')"><i class="fas fa-check"></i> Approve</button></td>`;
            tbody.appendChild(tr);
        });
    } catch (err) { console.error("loadRejectedList:", err); }
    updateApproveAllButtons();
}

async function approveEmployee(employeeId) {
    try {
        const token = localStorage.getItem("access_token"); if (!token) { showPopup("Session expired", true); return; }
        const res = await fetch(`${API_URL}/approve_timesheet`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ reporting_emp_code: loggedInEmployeeId, employee_code: employeeId }) });
        const result = await res.json().catch(() => ({}));
        if (res.status === 401) { localStorage.clear(); window.location.href = "/static/login.html"; return; }
        if (!res.ok || !result.success) { showPopup("Approve failed", true); return; }
        showPopup(`Employee ${employeeId} approved`);
        await loadPendingList(); await loadApprovedList(); await loadRejectedList();
    } catch (err) { console.error("approveEmployee:", err); showPopup("Approve failed", true); }
}

async function rejectEmployee(employeeId) {
    try {
        const token = localStorage.getItem("access_token"); if (!token) { showPopup("Session expired", true); return; }
        const res = await fetch(`${API_URL}/reject_timesheet`, { method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ reporting_emp_code: loggedInEmployeeId, employee_code: employeeId }) });
        const result = await res.json().catch(() => ({}));
        if (!res.ok || !result.success) { showPopup("Reject failed", true); return; }
        showPopup(`Employee ${employeeId} rejected`);
        await loadPendingList(); await loadApprovedList(); await loadRejectedList();
    } catch (err) { console.error("rejectEmployee:", err); showPopup("Reject failed", true); }
}

async function approveAll(source) {
    if (!confirm(`Approve ALL ${source.toUpperCase()} timesheets?`)) return;
    showLoading(`Approving all ${source.toLowerCase()}...`);
    try {
        const res = await fetch(`${API_URL}/approve_all_timesheets`, { method: "POST", headers: getHeaders(), body: JSON.stringify({ reporting_emp_code: loggedInEmployeeId, source }) });
        const result = await res.json(); hideLoading();
        if (!res.ok || !result.success) { showPopup(result.message||"Approve All failed", true); return; }
        showPopup(result.message); await loadPendingList(); await loadApprovedList(); await loadRejectedList(); updateApproveAllButtons();
    } catch (err) { hideLoading(); console.error("approveAll:", err); showPopup("Approve All failed", true); }
}

function updateApproveAllButtons() {
    const pr = document.querySelectorAll("#pendingTableBody tr").length;
    const rr = document.querySelectorAll("#rejectedTableBody tr").length;
    document.getElementById("approveAllPendingContainer").style.display  = pr > 0 ? "block" : "none";
    document.getElementById("approveAllRejectedContainer").style.display = rr > 0 ? "block" : "none";
}

// ── Employee details modal ────────────────────────────────────────────────────
async function openEmployeeDetails(employeeId) {
    const modal = document.getElementById("modalOverlay"); const mc = modal?.querySelector(".modal-content"); if (!modal || !mc) return;
    if (!window._originalModalHTML) window._originalModalHTML = mc.innerHTML;
    modal.style.display = "flex";
    mc.innerHTML = `<h3 style="text-align:center">Loading...</h3>`;
    try {
        const res = await fetch(`${API_URL}/get_timesheet/${employeeId}`, { headers: getHeaders() });
        if (!res.ok) throw new Error("Failed");
        const data = await res.json();
        if (!data.entries || data.entries.length === 0) { mc.innerHTML = `<h3 style="text-align:center">No Timesheet Data</h3><div style="text-align:center"><button class="modal-cancel-btn" onclick="closeModalAndRestore()">Close</button></div>`; return; }
        mc.innerHTML = `<div class="manager-view-wrapper">
            <h2 style="text-align:center;margin-bottom:1rem">Employee Timesheet</h2>
            <div style="background:#f8f9fa;border-radius:12px;padding:1rem 1.5rem;margin-bottom:1rem;border-left:5px solid #3498db;">
                <p><strong>ID:</strong> ${data.employee_id||"-"}</p><p><strong>Name:</strong> ${data.employee_name||"-"}</p>
                <p><strong>Designation:</strong> ${data.designation||"-"}</p><p><strong>Partner:</strong> ${data.partner||"-"}</p>
            </div>
            <div style="max-height:55vh;overflow-y:auto;">
            <table class="timesheet-table" style="width:100%;font-size:14px"><thead><tr>
                <th>Date</th><th>Week Period</th><th>Client</th><th>Project</th><th>Activity</th>
                <th>Location</th><th>Start</th><th>End</th><th>Hours</th><th>Billable</th><th>Remarks</th>
            </tr></thead><tbody>${data.entries.map(e=>`<tr><td>${e.date||"-"}</td><td>${e.weekPeriod||"-"}</td><td>${e.client||"-"}</td><td>${e.project||"-"}</td><td>${e.activity||"-"}</td><td>${e.location||"-"}</td><td>${e.start_time||"-"}</td><td>${e.end_time||"-"}</td><td>${e.hours||"-"}</td><td>${e.billable||"-"}</td><td>${e.remarks||"-"}</td></tr>`).join("")}
            </tbody></table></div>
        </div><div style="text-align:center;margin-top:20px"><button class="modal-cancel-btn" onclick="closeModalAndRestore()">Close</button></div>`;
    } catch (err) { mc.innerHTML = `<p style="color:red;text-align:center">Failed to load.</p><div style="text-align:center"><button class="modal-cancel-btn" onclick="closeModalAndRestore()">Close</button></div>`; }
}

function closeModalAndRestore() {
    const modal = document.getElementById("modalOverlay"); const mc = modal?.querySelector(".modal-content");
    if (modal && window._originalModalHTML) { mc.innerHTML = window._originalModalHTML; modal.style.display = "none"; }
    else closeModal();
}

// ── Section navigation ────────────────────────────────────────────────────────
async function showSection(section) {
    await checkUserRole();
    ["timesheet","history","approve","pending","rejected"].forEach(s => {
        const el = document.getElementById(`${s}Section`); if (el) el.style.display = s === section ? "block" : "none";
    });
    document.querySelectorAll(".nav-menu a").forEach(a => a.classList.remove("active"));
    const link = Array.from(document.querySelectorAll(".nav-menu a")).find(a => a.getAttribute("onclick")?.includes(`'${section}'`));
    if (link) link.classList.add("active");
    if (section === "history") loadHistory();
    if (section === "approve") loadApprovedList();
    if (section === "pending") loadPendingList();
    if (section === "rejected") loadRejectedList();
}

// ── Misc ──────────────────────────────────────────────────────────────────────
function toggleNavMenu() { document.getElementById("navMenu")?.classList.toggle("active"); }

function clearTimesheet(auto = false) {
    if (!auto && !confirm("Clear all timesheet data?")) return;
    document.querySelectorAll(".timesheet-section").forEach(s => s.remove());
    sectionCount = 0; addWeekSection();
    document.querySelectorAll("textarea").forEach(t => t.value = "");
    updateSummary(); if (!auto) showPopup("Timesheet cleared");
}

let isExiting = false;
window.addEventListener("beforeunload", e => { if (!isExiting) { e.preventDefault(); e.returnValue = ""; return ""; } });

function showExitConfirmation() { const p = document.getElementById("exitConfirmation"); if (p) p.style.display = "block"; }
function cancelExit() { const p = document.getElementById("exitConfirmation"); if (p) p.style.display = "none"; }
function confirmExit() {
    const p = document.getElementById("exitConfirmation"); if (p) p.style.display = "none";
    window.onbeforeunload = null; localStorage.clear(); sessionStorage.clear();
    setTimeout(() => window.location.href = "/static/login.html", 300);
}

function formatDate(date) { if (!date || !(date instanceof Date) || isNaN(date)) return ""; return date.toISOString().split("T")[0]; }

// ── Excel export ──────────────────────────────────────────────────────────────
function exportTimesheetToExcel() {
    const empId = document.getElementById("employeeId").value;
    const columns = ["employeeId","employeeName","designation","gender","partner","reportingManager","weekPeriod","date","location","projectStartTime","projectEndTime","client","project","projectCode","reportingManagerEntry","activity","projectHours","billable","remarks","hits","misses","feedback_hr","feedback_it","feedback_crm","feedback_others"];
    const headers = ["Employee ID","Employee Name","Designation","Gender","Partner","Reporting Manager","Week Period","Date","Location of Work","Project Start Time","Project End Time","Client","Project","Project Code","Reporting Manager Entry","Activity","Project Hours","Billable","Remarks","3 HITS","3 MISSES","Feedback for HR","Feedback for IT","Feedback for CRM","Feedback for Others"];
    const rows = [];
    document.querySelectorAll(".timesheet-section").forEach(sec => {
        const wp = sec.querySelector(".week-period select")?.value||"";
        sec.querySelectorAll("tbody tr").forEach(row => {
            const date = row.querySelector(".date-field")?.value?.trim()||"";
            const client = getFieldValue(row,".col-client"); const project = getFieldValue(row,".col-project");
            if (!date && !project && !client) return;
            rows.push({ employeeId:empId, employeeName:document.getElementById("employeeName").value, designation:document.getElementById("designation").value, gender:document.getElementById("gender").value, partner:document.getElementById("partner").value, reportingManager:document.getElementById("reportingManager").value, weekPeriod:wp, date, location:row.querySelector(".location-select")?.value||"", projectStartTime:row.querySelector(".project-start")?.value||"", projectEndTime:row.querySelector(".project-end")?.value||"", client, project, projectCode:getFieldValue(row,".col-project-code"), reportingManagerEntry:row.querySelector(".reporting-manager-field")?.value||"", activity:row.querySelector(".activity-field")?.value||"", projectHours:row.querySelector(".project-hours-field")?.value||"", billable:row.querySelector(".billable-select")?.value||"", remarks:row.querySelector(".remarks-field")?.value||"", hits:document.getElementById("hits").value||"", misses:document.getElementById("misses").value||"", feedback_hr:document.getElementById("feedback_hr").value||"", feedback_it:document.getElementById("feedback_it").value||"", feedback_crm:document.getElementById("feedback_crm").value||"", feedback_others:document.getElementById("feedback_others").value||"" });
        });
    });
    if (rows.length === 0) { showPopup("No valid data to export!", true); return; }
    const ws = XLSX.utils.json_to_sheet(rows, { header: columns }); XLSX.utils.sheet_add_aoa(ws, [headers], { origin: "A1" });
    const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, ws, "Timesheet"); XLSX.writeFile(wb, `Timesheet_${empId}_${new Date().toISOString().split("T")[0]}.xlsx`);
    showPopup("Timesheet exported!");
}

function exportHistoryToExcel() {
    if (!historyEntries || historyEntries.length === 0) { showPopup("No history available!"); return; }
    const columns = ["employeeId","employeeName","designation","gender","partner","reportingManager","weekPeriod","date","location","projectStartTime","projectEndTime","client","project","projectCode","reportingManagerEntry","activity","projectHours","billable","remarks","hits","misses","feedback_hr","feedback_it","feedback_crm","feedback_others","totalHours","totalBillableHours","totalNonBillableHours"];
    const headers = ["Employee ID","Employee Name","Designation","Gender","Partner","Reporting Manager","Week Period","Date","Location of Work","Project Start Time","Project End Time","Client","Project","Project Code","Reporting Manager Entry","Activity","Project Hours","Billable","Remarks","3 HITS","3 MISSES","Feedback for HR","Feedback for IT","Feedback for CRM","Feedback for Others","Total Hours","Total Billable Hours","Total Non Billable Hours"];
    const rows = historyEntries.map(r => ({ employeeId:r.employeeId||"", employeeName:r.employeeName||"", designation:r.designation||"", gender:r.gender||"", partner:r.partner||"", reportingManager:r.reportingManager||"", weekPeriod:r.weekPeriod||"", date:r.date||"", location:r.location||"", projectStartTime:r.projectStartTime||"", projectEndTime:r.projectEndTime||"", client:r.client||"", project:r.project||"", projectCode:r.projectCode||"", reportingManagerEntry:r.reportingManagerEntry||"", activity:r.activity||"", projectHours:r.projectHours||"", billable:r.billable||"", remarks:r.remarks||"", hits:r.hits||"", misses:r.misses||"", feedback_hr:r.feedback_hr||"", feedback_it:r.feedback_it||"", feedback_crm:r.feedback_crm||"", feedback_others:r.feedback_others||"", totalHours:r.totalHours||"", totalBillableHours:r.totalBillableHours||"", totalNonBillableHours:r.totalNonBillableHours||"" }));
    const ws = XLSX.utils.json_to_sheet(rows, { header: columns }); XLSX.utils.sheet_add_aoa(ws, [headers], { origin: "A1" });
    const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, ws, "History"); XLSX.writeFile(wb, `History_${loggedInEmployeeId}_${new Date().toISOString().split("T")[0]}.xlsx`);
    showPopup("History exported!");
}

async function handleExcelUpload(event) {
    const file = event.target.files[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = async function(e) {
        try {
            const data = new Uint8Array(e.target.result);
            const wb = XLSX.read(data, { type:"array", cellDates:true });
            const sheet = wb.Sheets[wb.SheetNames[0]];
            const jsonData = XLSX.utils.sheet_to_json(sheet, { defval:"", raw:false });
            if (!jsonData || jsonData.length === 0) { showPopup("Excel file is empty.", true); return; }
            const required = ["Employee ID","Employee Name","Designation","Gender","Partner","Reporting Manager","Week Period","Date","Location of Work","Project Start Time","Project End Time","Client","Project","Project Code","Reporting Manager Entry","Activity","Project Hours","Billable","Remarks"];
            const missing = required.filter(c => !Object.keys(jsonData[0]).includes(c));
            if (missing.length > 0) { showPopup(`Missing columns: ${missing.join(", ")}`, true); return; }
            showLoading("Uploading Excel data...");
            const toStr = v => v instanceof Date ? v.toISOString().split("T")[0] : v !== null && v !== undefined ? String(v) : "";
            function excelTimeToMinutes(v) { if (v===''||v===null||v===undefined) return null; if (typeof v==="string"&&v.includes(":")) { const [h,m]=v.split(":").map(Number); return isNaN(h)||isNaN(m)?null:h*60+m; } if (!isNaN(v)) return Math.round(Number(v)*24*60); return null; }
            function excelTimeToHHMM(v) { const m=excelTimeToMinutes(v); if (m===null) return ""; return `${String(Math.floor(m/60)).padStart(2,"0")}:${String(m%60).padStart(2,"0")}`; }
            function calcHrs(row) { const s=excelTimeToMinutes(row["Project Start Time"]); const e=excelTimeToMinutes(row["Project End Time"]); return (s!==null&&e!==null&&e>s) ? +((e-s)/60).toFixed(2) : 0; }
            const timesheetData = jsonData.map(row => ({ employeeId:toStr(row["Employee ID"]), employeeName:toStr(row["Employee Name"]), designation:toStr(row["Designation"]), gender:toStr(row["Gender"]), partner:toStr(row["Partner"]), reportingManager:toStr(row["Reporting Manager"]), weekPeriod:toStr(row["Week Period"]), date:toStr(row["Date"]), location:toStr(row["Location of Work"]), projectStartTime:excelTimeToHHMM(row["Project Start Time"]), projectEndTime:excelTimeToHHMM(row["Project End Time"]), client:toStr(row["Client"]), project:toStr(row["Project"]), projectCode:toStr(row["Project Code"]), reportingManagerEntry:toStr(row["Reporting Manager Entry"]), activity:toStr(row["Activity"]), projectHours:calcHrs(row).toString(), billable:toStr(row["Billable"]), remarks:toStr(row["Remarks"]), hits:toStr(row["3 Hits"])||"", misses:toStr(row["3 Misses"])||"", feedback_hr:toStr(row["Feedback for HR"])||"", feedback_it:toStr(row["Feedback for IT"])||"", feedback_crm:toStr(row["Feedback for CRM"])||"", feedback_others:toStr(row["Feedback for Others"])||"" }));
            const res = await fetch(`${API_URL}/save_timesheets`, { method:"POST", headers:getHeaders(), body:JSON.stringify(timesheetData) });
            hideLoading();
            if (!res.ok) { const err = await res.json(); throw new Error(Array.isArray(err.detail) ? err.detail.map(e=>`${e.loc.join(".")} → ${e.msg}`).join("\n") : err.detail); }
            showPopup("Excel uploaded and saved successfully!");
        } catch (err) { hideLoading(); showPopup(`Upload failed: ${err.message}`, true); }
    };
    reader.readAsArrayBuffer(file);
}
window.handleExcelUpload = handleExcelUpload;