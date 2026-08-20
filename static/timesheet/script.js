
console.log("✅ script.js loaded successfully");

let sectionCount = 0;
let employeeData = [];
let clientData = [];
let loggedInEmployeeId = localStorage.getItem("loggedInEmployeeId") || "";
// const API_URL = "http://localhost:8000";
const API_URL = "";

let copiedData = null; // for copy/paste row
let currentRow = null; // used by modal if present
let isEditingHistory = false;
let currentEntryId = null;
let historyEntries = [];
// Replace your polling interval with this - only poll every 5 MINUTES instead of 30 seconds
let pollingInterval = null;
// Debounced version of refreshPayrollWeeks
const debouncedRefreshWeeks = debounce(refreshPayrollWeeks, 1000);

// 1. ADD THIS GLOBAL VARIABLE (after line with historyEntries)
let employeeProjects = {
  clients: [],
  projects: [],
  project_codes: []
};

// Employees under this partner have no fixed client/project list to pick
// from, so Client / Project / Project Code are plain typed fields instead
// of dropdowns, everywhere (table rows, the entry modal, and the downloaded
// template). Everything else about them works exactly like any other user.
const FREE_TEXT_PARTNER_CODE = "JHS01";
window._freeTextClientProject = false;

// Shared-services (JHS01) employees pick Project Code from this fixed list
// instead of typing it freely — Client/Project stay plain typed fields for
// them, only Project Code becomes a dropdown. "Type Here" swaps the dropdown
// for a free-text input for anything not on the list.
const SHARED_SERVICES_PROJECT_CODES = [
  "SS-HR Team",
  "SS-Payroll Team",
  "SS-Accounts & Finance Team",
  "SS-IT Team",
  "SS-Automation Team",
  "SS-CRM Team",
  "SS-Knowledge Team"
];
const SHARED_SERVICES_TYPE_HERE = "Type Here";

// Locations that mean "not a working day" — project/time/client fields are
// optional (but still accepted if filled in) for rows marked with these.
const DAY_OFF_LOCATIONS = ["Leave", "PHY", "Week Off"];
const isDayOffLocation = (loc) => DAY_OFF_LOCATIONS.includes((loc || "").trim());
const NO_TRAVEL_TIME_LOCATIONS = [...DAY_OFF_LOCATIONS, "Work From Home", "Office"];

function applyLocationTimeRules(row) {
  if (!row) return;
  const location = row.querySelector('.location-select')?.value || '';
  const lunchTime = row.querySelector('.lunch-time-select');
  const travelTime = row.querySelector('.travel-time-select');
  const billable = row.querySelector('.billable-select');
  const isDayOff = isDayOffLocation(location);
  const hasNoTravel = NO_TRAVEL_TIME_LOCATIONS.includes(location.trim());

  if (lunchTime) {
    if (isDayOff) lunchTime.value = '';
    lunchTime.disabled = isDayOff;
  }
  if (travelTime) {
    if (hasNoTravel) travelTime.value = '';
    travelTime.disabled = hasNoTravel;
  }
  if (billable) {
    if (isDayOff) billable.value = 'No';
    billable.disabled = isDayOff;
  }
}

function onLocationChange(select) {
  applyLocationTimeRules(select?.closest('tr'));
  updateSummary();
}

function applyModalLocationTimeRules() {
  const location = document.getElementById('modalInput2')?.value || '';
  const lunchTime = document.getElementById('modalInput13');
  const travelTime = document.getElementById('modalInput14');
  const billable = document.getElementById('modalInput11');
  const isDayOff = isDayOffLocation(location);
  const hasNoTravel = NO_TRAVEL_TIME_LOCATIONS.includes(location.trim());

  if (lunchTime) {
    if (isDayOff) lunchTime.value = '';
    lunchTime.disabled = isDayOff;
  }
  if (travelTime) {
    if (hasNoTravel) travelTime.value = '';
    travelTime.disabled = hasNoTravel;
  }
  if (billable) {
    if (isDayOff) billable.value = 'No';
    billable.disabled = isDayOff;
  }
}

function startPayrollPolling() {
  // Clear any existing interval first
  if (pollingInterval) {
    clearInterval(pollingInterval);
  }
  
  // Poll every 5 minutes (300000ms) instead of 30 seconds
  pollingInterval = setInterval(() => {
    if (document.visibilityState === "visible") {
      refreshPayrollWeeks();
    }
  }, 300000); // 5 minutes
}


// Stop polling when leaving the page
window.addEventListener('beforeunload', () => {
  if (pollingInterval) {
    clearInterval(pollingInterval);
  }
});

// At the top of script.js, add a debounce helper
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

async function loadEmployeeProjects() {
  if (!loggedInEmployeeId) return;

  try {
    const res = await fetch(`${API_URL}/get_employee_projects/${loggedInEmployeeId}`, {
      headers: getHeaders()
    });

    if (res.ok) {
      employeeProjects = await res.json();
      window._freeTextClientProject =
        (employeeProjects.partner_emp_code || "").trim().toUpperCase() === FREE_TEXT_PARTNER_CODE;
      console.log("✅ Employee projects loaded:", employeeProjects);
       console.log("📊 Clients:", employeeProjects.clients);
  console.log("📊 Projects by client:", employeeProjects.projects_by_client);
    } else {
      console.warn("Failed to load employee projects");
    }
  } catch (err) {
    console.error("Error loading employee projects:", err);
  }

  // Needed before any row renders (checkUserRole() runs later, after draft
  // rows are already restored) so the project-plan status feature — TL-only,
  // exempting the free-text/JHS01 partner — is ready from the very first row.
  try {
    const resMgr = await fetch(`${API_URL}/check_reporting_manager/${loggedInEmployeeId}`, {
      headers: getHeaders()
    });
    window._isTL = resMgr.ok ? !!(await resMgr.json()).isManager : false;
  } catch (err) {
    console.error("Error checking TL status:", err);
    window._isTL = false;
  }
}

// TLs must have a valid project plan for their entries before submitting;
// JHS01 is shared services and is exempt (no fixed projects to plan against).
const showsProjectPlanStatus = () => !!window._isTL && !window._freeTextClientProject;

// Restore token from sessionStorage if localStorage got cleared
window.addEventListener("load", () => {
  const localToken =
    localStorage.getItem("access_token") || localStorage.getItem("token");
  const sessionToken = sessionStorage.getItem("token");
  if (!localToken && sessionToken) {
    localStorage.setItem("token", sessionToken);
    localStorage.setItem("access_token", sessionToken);
    console.log("🔁 Restored token from sessionStorage");
  }
});

const getHeaders = (requireAuth = true) => {
  const token =
    localStorage.getItem("access_token") ||
    localStorage.getItem("token") ||
    sessionStorage.getItem("token");

  // If auth required and no token -> force login (fail fast)
  if (requireAuth && !token) {
    console.warn("⚠️ No auth token found — redirecting to login.");
    localStorage.clear();
    sessionStorage.clear();
    window.location.href = "/static/login.html";
    return { "Content-Type": "application/json" }; // won't be used because of redirect
  }

  const base = { "Content-Type": "application/json" };
  return token ? { ...base, Authorization: `Bearer ${token}` } : base;
};


async function checkPARStatus() {
  try {
    // const res = await fetch(`${API_URL}/get-par-current-status`);
    const res = await fetch(`${API_URL}/get-par-current-status`, {
  headers: getHeaders(),
});
    if (!res.ok) {
      console.warn("PAR status fetch failed", res.status);
      return false;
    }
    const data = await res.json();
    return data.par_status === "enable";
  } catch (err) {
    console.error("Failed to fetch PAR status:", err);
    return false;
  }
}

function showLoading(text = "Loading...") {
  const bar = document.getElementById("loadingBar");
  if (!bar) return;
  bar.style.display = "block";
  bar.textContent = text;
}
function hideLoading() {
  const bar = document.getElementById("loadingBar");
  if (!bar) return;
  bar.style.display = "none";
}

function showError(message) {
  const dv = document.getElementById("errorMessage");
  if (!dv) {
    showPopup(message, true);
    return;
  }
  dv.textContent = message;
  dv.style.display = "block";
  // setTimeout(() => {
  //   dv.style.display = "none";
  // }, 5000);
}

// ── Global payroll cycle state ────────────────────────────────────────────────
let _availableCycles = [];       // all cycles user can fill
let _selectedCycle   = null;     // currently selected cycle object
let _submittedCycles = {};       // { cycle_id: true/false }

document.addEventListener("DOMContentLoaded", async () => {
  const token = localStorage.getItem("access_token");
  if (!token) {
    window.location.href = "/static/login.html";
    return;
  }

  // Step 1: Verify session
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

    // Load available payroll cycles
    await loadAvailableCycles();

    // Populate employee info
    populateEmployeeInfo();

    // Build the flat timesheet table for the selected cycle
    renderTimesheetTable();
    if (_selectedCycle) {
      populateAllCycleDateRows();
      // Overlay any saved draft entries on top of the auto-generated rows
      await loadDraftForCycle(_selectedCycle.id);
    }

    await checkUserRole();
    showSection("timesheet");
  } catch (err) {
    console.error("Init error:", err);
    showPopup("Failed to initialize data. See console.", true);
  } finally {
    hideLoading();
  }
});


// ── Load available payroll cycles and populate the dropdown ──────────────────
async function loadAvailableCycles() {
  try {
    const res = await fetch(`${API_URL}/available-payroll-cycles`, { headers: getHeaders() });
    if (!res.ok) throw new Error("Failed to fetch cycles");
    const data = await res.json();
    _availableCycles = data.cycles || [];
  } catch(e) {
    console.error("Error loading cycles:", e);
    _availableCycles = [];
  }

  // Also load submission status
  try {
    const res2 = await fetch(`${API_URL}/timesheet/submission-status/${loggedInEmployeeId}`, { headers: getHeaders() });
    if (res2.ok) {
      const d = await res2.json();
      _submittedCycles = d.status || {};
    }
  } catch(e) {}

  const wrap   = document.getElementById("payrollCycleSelectorWrap");
  const noBanner = document.getElementById("noCyclesBanner");
  const sel    = document.getElementById("payrollCycleSelect");

  if (!_availableCycles.length) {
    if (wrap) wrap.style.display = "none";
    if (noBanner) noBanner.style.display = "block";
    window._payrollLocked = true;
    return;
  }

  if (noBanner) noBanner.style.display = "none";
  if (wrap) wrap.style.display = "block";

  // Populate dropdown
  sel.innerHTML = '<option value="">-- Select a payroll cycle --</option>';
  _availableCycles.forEach(c => {
    const opt = document.createElement("option");
    opt.value = c.id;
    const submitted = _submittedCycles[c.id]?.submitted ? " ✅ Submitted" : "";
    const locked    = c.locked ? " 🔒 Deadline passed" : "";
    opt.textContent = `${c.cycle_label}${submitted}${locked}`;
    opt.disabled    = c.locked;
    sel.appendChild(opt);
  });

  // Auto-select first non-locked cycle (allow multiple submissions)
  const autoSelect = _availableCycles.find(c => !c.locked);
  if (autoSelect) {
    sel.value = autoSelect.id;
    _selectedCycle = autoSelect;
    _updateCycleUI(autoSelect);
    _setCycleWindow(autoSelect);
    // Draft will be loaded after renderTimesheetTable in the init flow
    window._pendingDraftCycleId = autoSelect.id;
  } else if (_availableCycles.length === 1) {
    sel.value = _availableCycles[0].id;
    _selectedCycle = _availableCycles[0];
    _updateCycleUI(_availableCycles[0]);
    _setCycleWindow(_availableCycles[0]);
    window._pendingDraftCycleId = _availableCycles[0].id;
  }
}

function onCycleChange() {
  const sel = document.getElementById("payrollCycleSelect");
  const id  = sel.value;
  if (!id) { _selectedCycle = null; return; }
  const cycle = _availableCycles.find(c => c.id === id);
  if (!cycle) return;
  _selectedCycle = cycle;
  _updateCycleUI(cycle);
  _setCycleWindow(cycle);
  renderTimesheetTable();
  populateAllCycleDateRows();
  // Load saved draft for this cycle (overlays/merges on top of the auto rows)
  loadDraftForCycle(cycle.id);
}

function _updateCycleUI(cycle) {
  const info   = document.getElementById("cycleDeadlineInfo");
  const banner = document.getElementById("cycleLockBanner");
  if (info) info.textContent = `Deadline: ${cycle.deadline_date} at ${cycle.deadline_time} IST`;
  if (banner) banner.style.display = cycle.locked ? "block" : "none";
  window._payrollLocked = cycle.locked;

  // Store the lunch/travel visibility flag globally
  window._showLunchTravel = cycle.show_lunch_travel !== false; // default true

  // Toggle modal fields
  _applyLunchTravelVisibility();

  // Disable submit only if locked (allow multiple submissions)
  const submitBtn = document.getElementById("submitBtn");
  if (submitBtn) {
    submitBtn.disabled = cycle.locked;
    submitBtn.title    = cycle.locked ? "Deadline passed" : "";
  }
}

function _applyLunchTravelVisibility() {
  const show = window._showLunchTravel !== false;

  // Modal fields (modalLabel13/14 and their inputs)
  ['13','14'].forEach(n => {
    const label = document.getElementById(`modalLabel${n}`);
    const input = document.getElementById(`modalInput${n}`);
    if (label) label.closest('div').style.display = show ? '' : 'none';
    else if (input) input.closest('div').style.display = show ? '' : 'none';
  });

  // Table columns — header and cells in all existing sections
  _toggleTableLunchTravel(show);
}

function _toggleTableLunchTravel(show) {
  const display = show ? '' : 'none';
  // All table headers named Lunch Time / Travel Time
  document.querySelectorAll('.timesheet-table thead th').forEach(th => {
    const txt = th.textContent.trim();
    if (txt === 'Lunch Time' || txt === 'Travel Time') th.style.display = display;
  });
  // All cells with those classes
  document.querySelectorAll('.col-lunch-time, .col-travel-time').forEach(td => {
    td.style.display = display;
  });
}

function _setCycleWindow(cycle) {
  const start = new Date(cycle.start_date);
  const end   = new Date(cycle.end_date);
  window._currentPayrollWindow = { start: start.toISOString(), end: end.toISOString() };
  window._activeCycle = cycle;
  window._payrollLocked = cycle.locked;
}

// ── Load saved draft and restore rows ────────────────────────────────────────
async function loadDraftForCycle(cycleId) {
  if (!cycleId || !loggedInEmployeeId) return;
  try {
    const res = await fetch(
      `${API_URL}/timesheet/draft/${loggedInEmployeeId}?cycle_id=${cycleId}`,
      { headers: getHeaders() }
    );
    if (!res.ok) return;
    const data = await res.json();

    const entries = (data.draft && data.draft.entries) || [];

    const tbody = document.getElementById('timesheetBody_1');
    if (tbody && entries.length) {
      // Rebuild from the saved draft — flat, one row per saved entry
      tbody.innerHTML = '';
      for (const entry of entries) {
        _restoreDraftRow(TIMESHEET_SECTION_ID, entry, true);
      }
      updateRowNumbers('timesheetBody_1');
    }

    // Fill in any cycle dates the saved draft didn't cover
    populateAllCycleDateRows();

    if (!data.draft) { updateSummary(); return; }

    // Restore feedback/metadata
    const meta = data.draft.metadata || {};
    ['hits','misses','feedback_hr','feedback_it','feedback_crm','feedback_others'].forEach(f => {
      const el = document.getElementById(f);
      if (el && meta[f]) el.value = meta[f];
    });

    // Restore idle time status, hours, and reason
    const statusEl = document.getElementById('idle_time_status');
    if (statusEl) statusEl.value = meta.idle_time_status || 'No';
    const hoursEl = document.getElementById('idle_time_hours');
    if (hoursEl) hoursEl.value = meta.idle_time_hours || '';
    const reasonEl = document.getElementById('idle_time_reason');
    if (reasonEl) reasonEl.value = meta.idle_time_reason || '';
    if (typeof toggleIdleTimeFields === 'function') toggleIdleTimeFields();

    updateSummary();
    // Silently restore — no popup needed, green rows are the visual indicator
  } catch(e) {
    console.error('loadDraftForCycle error:', e);
  }
}

function _restoreDraftRow(sectionId, entry, isSaved = false) {
  const sectionNum = sectionId.split('_')[1];
  const tbody = document.getElementById(`timesheetBody_${sectionNum}`);
  if (!tbody) return;

  const win = window._currentPayrollWindow;
  const minDate = win ? new Date(win.start).toISOString().split('T')[0] : (entry.date || '');
  const maxDate = win ? new Date(win.end).toISOString().split('T')[0]   : (entry.date || '');

  const rowIndex = tbody.querySelectorAll('tr').length + 1;
  const tr = document.createElement('tr');
  if (isSaved) {
    tr.style.background = 'linear-gradient(90deg,#f0fdf4,#dcfce7)';
    tr.dataset.saved = '1';
    tr.dataset.entryId = entry.id || '';
  }

  tr.innerHTML = `
    <td class="col-sno">${rowIndex}</td>
    <td class="col-add"><button class="eye-btn" onclick="openModal(this)"><i class="fas fa-eye"></i></button></td>
    <td class="col-action">
      <button class="add-entry-btn" onclick="addEntryForRow(this)" title="Add another entry for this date"><i class="fas fa-plus"></i></button>
      <button class="copy-btn" onclick="copyRow(this)">Copy</button>
      <button class="paste-btn" onclick="pasteRow(this)">Paste</button>
    </td>
    <td class="col-date form-input">
      <input type="date" class="date-field form-input" value="${entry.date || minDate}"
        min="${minDate}" max="${maxDate}"
        onchange="validateDate(this); updateSummary()">
    </td>
    <td class="col-location">
      <select class="location-select form-input" onchange="onLocationChange(this)">
        <option value="Office"${entry.location==='Office'?' selected':''}>Office</option>
        <option value="Client Site"${entry.location==='Client Site'?' selected':''}>Client Site</option>
        <option value="Work From Home"${entry.location==='Work From Home'?' selected':''}>Work From Home</option>
        <option value="Field Work"${entry.location==='Field Work'?' selected':''}>Field Work</option>
        <option value="Leave"${entry.location==='Leave'?' selected':''}>Leave</option>
        <option value="PHY"${entry.location==='PHY'?' selected':''}>PHY</option>
        <option value="Week Off"${entry.location==='Week Off'?' selected':''}>Week Off</option>
      </select>
    </td>
    <td class="col-project-start"><input type="time" class="project-start form-input" value="${entry.projectStartTime||''}" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
    <td class="col-project-end"><input type="time" class="project-end form-input" value="${entry.projectEndTime||''}" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
    <td class="col-client"></td>
    <td class="col-project"></td>
    <td class="col-project-code"></td>
    <td class="col-reporting-manager"><input type="text" class="reporting-manager-field form-input" value="${entry.reportingManagerEntry||''}" placeholder="Enter Reporting Manager"></td>
    <td class="col-activity" style="min-width:200px;"><input type="text" class="activity-field form-input" value="${entry.activity||''}" placeholder="Enter Activity" oninput="updateSummary()"></td>
    <td class="col-project-hours"><input type="number" class="project-hours-field form-input" value="${entry.projectHours||''}" readonly></td>
    <td class="col-billable">
      <select class="billable-select form-input" onchange="updateSummary()">
        <option value="Yes"${entry.billable==='Yes'?' selected':''}>Billable</option>
        <option value="No"${entry.billable==='No'?' selected':''}>Non-Billable</option>
      </select>
    </td>
    <td class="col-lunch-time" style="display:${window._showLunchTravel!==false?'':'none'}">
      <select class="lunch-time-select form-input">
        <option value="">None</option>
        <option value="15 min"${entry.lunchTime==='15 min'?' selected':''}>15 min</option>
        <option value="30 min"${(entry.lunchTime || '30 min')==='30 min'?' selected':''}>30 min</option>
        <option value="45 min"${entry.lunchTime==='45 min'?' selected':''}>45 min</option>
        <option value="1 hr"${entry.lunchTime==='1 hr'?' selected':''}>1 hr</option>
        <option value="1.5 hr"${entry.lunchTime==='1.5 hr'?' selected':''}>1.5 hr</option>
        <option value="2 hr"${entry.lunchTime==='2 hr'?' selected':''}>2 hr</option>
      </select>
    </td>
    <td class="col-travel-time" style="display:${window._showLunchTravel!==false?'':'none'}">
      <select class="travel-time-select form-input">
        <option value="">None</option>
        <option value="15 min"${entry.travelTime==='15 min'?' selected':''}>15 min</option>
        <option value="30 min"${entry.travelTime==='30 min'?' selected':''}>30 min</option>
        <option value="45 min"${entry.travelTime==='45 min'?' selected':''}>45 min</option>
        <option value="1 hr"${entry.travelTime==='1 hr'?' selected':''}>1 hr</option>
        <option value="1.5 hr"${entry.travelTime==='1.5 hr'?' selected':''}>1.5 hr</option>
        <option value="2 hr"${entry.travelTime==='2 hr'?' selected':''}>2 hr</option>
        <option value="2.5 hr"${entry.travelTime==='2.5 hr'?' selected':''}>2.5 hr</option>
        <option value="3 hr"${entry.travelTime==='3 hr'?' selected':''}>3 hr</option>
      </select>
    </td>
    <td class="col-remarks"><input type="text" class="remarks-field form-input" value="${entry.remarks||''}" placeholder="Additional notes"></td>
    <td class="col-delete"><button class="delete-btn" onclick="deleteRow(this)">Delete</button></td>
  `;

  tbody.appendChild(tr);
  setupSmartDropdowns(tr);
  applyLocationTimeRules(tr);

  // Restore client/project/code after smart dropdowns are set up. Client and
  // Project (dropdown mode) are always plain <input> elements now (the
  // searchable combo), so restoring is just setting .value directly —
  // there's no "not a valid option" fallback needed, the combo only
  // validates on blur, not on programmatic assignment.
  const isOtherClient = !window._freeTextClientProject && (entry.client || '').trim() === 'Other';
  if (entry.client) {
    const inp = tr.querySelector('.col-client')?.querySelector('input');
    if (inp) inp.value = entry.client;
  }
  if (isOtherClient) {
    // "Other" client — Project is free text, Project Code is a fixed "Other"
    _applyRowClientCascade(tr, 'Other');
    const projInp = tr.querySelector('.col-project')?.querySelector('input');
    if (projInp) projInp.value = entry.project || '';
  } else {
    if (entry.project) {
      const projCell = tr.querySelector('.col-project');
      if (projCell && !window._freeTextClientProject) {
        // Rebuild filtered by the restored client so the combo's suggestion
        // list matches that client (the cell's combo was created empty by
        // setupSmartDropdowns, before the client was known).
        projCell.innerHTML = '';
        const projField = createSmartDropdown('project', projCell, entry.project, entry.client);
        projCell.appendChild(projField);
      } else {
        const inp = projCell?.querySelector('input');
        if (inp) inp.value = entry.project;
      }
    }
    if (entry.projectCode) {
      const codeCell = tr.querySelector('.col-project-code');
      if (window._freeTextClientProject) {
        // Rebuild so a preset value shows in the dropdown and a custom value
        // shows in the "Type Here" input, rather than always the last-rendered mode.
        if (codeCell) {
          codeCell.innerHTML = "";
          codeCell.appendChild(createSharedServicesProjectCode(entry.projectCode));
        }
      } else {
        const codeInp = codeCell?.querySelector('input');
        if (codeInp) codeInp.value = entry.projectCode;
      }
    }
  }

  // Covers drafts loaded on page load and rows restored right after an Excel
  // upload alike — both funnel through this one restore function.
  showProjectPlanStatus(entry.projectCode || '', { row: tr });

  updateSummary();
}


// A searchable, single-select combobox: a plain text input backed by a
// floating, filterable suggestion list. Used anywhere Client/Project used to
// be a plain <select> — the option lists can run to 100+ entries (company-
// wide clients, or 30-40 projects for a big client), so a type-ahead is
// needed. The root element returned IS the input itself (no wrapper), so
// every existing `cell.querySelector('input')` fallback (getFieldValue,
// setFieldValue, saveModalEntry, _restoreDraftRow, etc.) keeps working
// unchanged — callers never need to know this isn't a plain input.
function createSearchableCombo(type, options, currentValue = "") {
  const input = document.createElement("input");
  input.type = "text";
  input.className = `${type}-field form-input combo-input`;
  input.placeholder = `Search ${type.replace('_', ' ')}...`;
  input.autocomplete = "off";
  input.value = currentValue || "";

  // Appended to <body> (not the cell) and positioned with `fixed` coords so
  // it's never clipped by the table's horizontal scroll wrapper or the
  // modal's own scroll region — both of which an absolutely-positioned
  // descendant would be subject to.
  const list = document.createElement("div");
  list.className = "combo-suggestions";
  list.style.cssText =
    "display:none;position:fixed;z-index:3000;background:#fff;border:1px solid #ccc;" +
    "border-radius:8px;max-height:240px;overflow-y:auto;box-shadow:0 8px 24px rgba(0,0,0,.15);";
  document.body.appendChild(list);

  let lastValid = currentValue || "";
  let highlighted = -1;
  let scrollHandler = null;

  function positionList() {
    const r = input.getBoundingClientRect();
    list.style.left = r.left + "px";
    list.style.top = (r.bottom + 2) + "px";
    list.style.width = r.width + "px";
  }

  function closeList() {
    list.style.display = "none";
    if (scrollHandler) {
      window.removeEventListener("scroll", scrollHandler, true);
      scrollHandler = null;
    }
  }

  // Scrolling the page/table should keep the list anchored under the input
  // (smooth, follows along) rather than yanking it away — the previous
  // behavior closed the list on ANY scroll, including scrolling inside the
  // suggestion list itself, which made a long list impossible to scroll
  // through. Only close it if the input has scrolled fully out of view.
  function onScroll(e) {
    if (list.contains(e.target)) return; // scrolling the list itself — leave it open
    if (list.style.display === "none") return;
    const r = input.getBoundingClientRect();
    if (r.bottom < 0 || r.top > window.innerHeight) {
      closeList();
    } else {
      positionList();
    }
  }

  function highlightRow(items) {
    items.forEach((it, i) => { it.style.background = i === highlighted ? "#eef2ff" : ""; });
  }

  function renderList() {
    const q = input.value.trim().toLowerCase();
    const matches = (q ? options.filter(o => o.toLowerCase().includes(q)) : options).slice(0, 200);
    list.innerHTML = "";
    highlighted = -1;
    if (!matches.length) { closeList(); return; }
    matches.forEach(opt => {
      const item = document.createElement("div");
      item.className = "combo-option";
      item.textContent = opt;
      item.style.cssText = "padding:7px 12px;cursor:pointer;font-size:.9rem;";
      item.addEventListener("mouseenter", () => {
        highlighted = Array.from(list.children).indexOf(item);
        highlightRow(Array.from(list.children));
      });
      item.addEventListener("mousedown", (e) => {
        e.preventDefault(); // fires before blur — keeps focus so blur-revert doesn't race it
        commit(opt);
      });
      list.appendChild(item);
    });
    positionList();
    list.style.display = "block";
    if (!scrollHandler) {
      scrollHandler = onScroll;
      window.addEventListener("scroll", scrollHandler, true);
    }
  }

  function commit(value) {
    input.value = value;
    lastValid = value;
    closeList();
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  input.addEventListener("focus", renderList);
  input.addEventListener("input", renderList);
  input.addEventListener("keydown", (e) => {
    const items = Array.from(list.children);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (list.style.display === "none") { renderList(); return; }
      highlighted = Math.min(highlighted + 1, items.length - 1);
      highlightRow(items);
      items[highlighted]?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      highlighted = Math.max(highlighted - 1, 0);
      highlightRow(items);
      items[highlighted]?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (highlighted >= 0 && items[highlighted]) {
        commit(items[highlighted].textContent);
      } else if (options.includes(input.value)) {
        commit(input.value);
      }
    } else if (e.key === "Escape") {
      closeList();
      input.blur();
    }
  });
  input.addEventListener("blur", () => {
    // Small delay so a suggestion's mousedown handler runs before we decide
    // whether the typed text is valid.
    setTimeout(() => {
      closeList();
      if (!options.includes(input.value)) {
        input.value = lastValid;
      } else {
        lastValid = input.value;
      }
    }, 150);
  });

  return input;
}

function createSmartDropdown(type, container, currentValue = "", currentClient = "") {
  // type = "client", "project", or "project_code"

  // Free-text partner: skip the dropdown/"Type here" machinery entirely and
  // hand back a plain input, for both table rows and the modal.
  if (window._freeTextClientProject && (type === "client" || type === "project")) {
    const input = document.createElement("input");
    input.type = "text";
    input.className = `${type}-field form-input`;
    input.placeholder = `Enter ${type}`;
    input.value = currentValue || "";
    input.addEventListener("input", updateSummary);
    return input;
  }

  let options = [];

  if (type === "client") {
    options = employeeProjects.clients || [];
  } else if (type === "project") {
    // Filter projects based on selected client
    if (currentClient && employeeProjects.projects_by_client && employeeProjects.projects_by_client[currentClient]) {
      options = employeeProjects.projects_by_client[currentClient].map(p => p.project_name);
    } else {
      options = [];
    }
  } else if (type === "project_code") {
    // Project codes are auto-filled, so we don't need options
    options = [];
  }

  // "Other" — lets a dropdown-mode employee log time against something not
  // in their assigned client list. Selecting it switches Project to free
  // text and Project Code to a fixed "Other" (handled by the change
  // listener in setupSmartDropdowns/_applyRowClientCascade for rows, and by
  // updateModalProjectDropdown for the modal).
  if (type === "client") {
    options = [...options, "Other"];
  }

  const combo = createSearchableCombo(type, options, currentValue);
  combo.classList.add("smart-dropdown");
  combo.addEventListener("change", updateSummary);
  return combo;
}


async function safeFetchJson(endpoint, opts = {}) {
  try {
    const res = await fetch(`${API_URL}${endpoint}`, {
      headers: getHeaders(opts.requireAuth !== false),
      ...(opts || {})
    });

    if (res.status === 401) {
      console.warn(`Unauthorized while fetching ${endpoint} — forcing logout.`);
      localStorage.clear();
      sessionStorage.clear();
      window.location.href = "/static/login.html";
      return [];
    }

    if (!res.ok) {
      console.warn(`Fetch ${endpoint} returned ${res.status}`);
      throw new Error(`Fetch ${endpoint} failed: ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`Error fetching ${endpoint}:`, err);
    return [];
  }
}


function getPayrollWindow() {
  const today = new Date();
  let start, end;

  if (today.getDate() >= 21) {
    start = new Date(today.getFullYear(), today.getMonth(), 21);
    end = new Date(today.getFullYear(), today.getMonth() + 1, 20);
  } else {
    start = new Date(today.getFullYear(), today.getMonth() - 1, 21);
    end = new Date(today.getFullYear(), today.getMonth(), 20);
  }

  return { start, end };
}


// top-level cache for current payroll window
window._currentPayrollWindow = null; // { start: ISO, end: ISO }

// Improved init — fetch from server and build weekOptions
// async function initWeekOptions() {
//   try {
//     // If /get-par-current-status requires auth, use getHeaders() else getHeaders(false)
//     const res = await fetch("/get-par-current-status", { headers: getHeaders() });
//     const data = await res.json();

//     let start, end;
//     if (data && data.start && data.end) {
//       start = new Date(data.start);
//       end = new Date(data.end);
//       window._currentPayrollWindow = { start: start.toISOString(), end: end.toISOString() };
//     } else {
//       const fallback = getPayrollWindow();
//       start = fallback.start;
//       end = fallback.end;
//       window._currentPayrollWindow = { start: start.toISOString(), end: end.toISOString() };
//     }

//     window.weekOptions = generateWeekOptions(start, end);

//     // update all existing selects
//     document.querySelectorAll('select[id^="weekPeriod_"]').forEach(select => {
//       select.innerHTML = "";
//       window.weekOptions.forEach(week => {
//         const o = document.createElement("option");
//         o.value = week.value;
//         o.textContent = week.text;
//         select.appendChild(o);
//       });
//     });

//     console.log(`✅ Payroll Period: ${start.toDateString()} → ${end.toDateString()}`);

//   } catch (err) {
//     console.error("❌ Error fetching payroll window:", err);
//     const { start, end } = getPayrollWindow();
//     window._currentPayrollWindow = { start: start.toISOString(), end: end.toISOString() };
//     window.weekOptions = generateWeekOptions(start, end);
//   }
// }

// initWeekOptions is now defined above in the init block

// Refresh function — update weekOptions only if admin changed payroll window
// async function refreshPayrollWeeks() {
//   try {
//     const res = await fetch("/get-par-current-status", { headers: getHeaders() });
//     if (!res.ok) {
//       console.warn("refreshPayrollWeeks: server returned", res.status);
//       return;
//     }
//     const data = await res.json();

//     let startISO = data && data.start ? (new Date(data.start)).toISOString() : null;
//     let endISO = data && data.end ? (new Date(data.end)).toISOString() : null;

//     if (!startISO || !endISO) {
//       const local = getPayrollWindow();
//       startISO = local.start.toISOString();
//       endISO = local.end.toISOString();
//     }

//     const newWindowHash = startISO + "|" + endISO;
//     const oldWindow = window._currentPayrollWindow ? (window._currentPayrollWindow.start + "|" + window._currentPayrollWindow.end) : null;

//     if (oldWindow !== newWindowHash) {
//       console.log("🔄 Payroll window changed — updating week dropdowns");
//       window._currentPayrollWindow = { start: startISO, end: endISO };
//       const start = new Date(startISO);
//       const end = new Date(endISO);
//       window.weekOptions = generateWeekOptions(start, end);

//       document.querySelectorAll('select[id^="weekPeriod_"]').forEach(select => {
//         const prevVal = select.value;
//         select.innerHTML = "";
//         window.weekOptions.forEach(week => {
//           const o = document.createElement("option");
//           o.value = week.value;
//           o.textContent = week.text;
//           select.appendChild(o);
//         });

//         // try to keep selection if same value exists
//         if (prevVal) {
//           const found = Array.from(select.options).find(opt => opt.value === prevVal);
//           if (found) select.value = prevVal;
//         }
//       });

//       showPopup("Payroll weeks updated by admin — week period dropdown refreshed.");
//     }
//   } catch (err) {
//     console.error("❌ Error refreshing payroll weeks:", err);
//   }
// }

async function refreshPayrollWeeks() {
  try {
    const res = await fetch("/active-payroll-cycle", { headers: getHeaders() });
    if (!res.ok) { console.warn("refreshPayrollWeeks: server returned", res.status); return; }
    const data = await res.json();

    // Check if locked state changed
    if (data.locked && !window._payrollLocked) {
      window._payrollLocked = true;
      window._payrollLockReason = "The submission deadline has passed. Timesheet is now locked.";
      showPopup("⏰ Submission deadline has passed. Timesheet is now locked.", true);
      return;
    }

    if (!data.found || data.locked) return;

    const startISO = new Date(data.start_date).toISOString();
    const endISO   = new Date(data.end_date).toISOString();
    const newWindowHash = startISO + "|" + endISO;
    const oldWindow = window._currentPayrollWindow
      ? (window._currentPayrollWindow.start + "|" + window._currentPayrollWindow.end)
      : null;

    if (oldWindow === newWindowHash) {
      console.log("✅ Payroll window unchanged, skipping update");
      return;
    }

    console.log("🔄 Payroll window changed — refreshing date rows");
    window._currentPayrollWindow = { start: startISO, end: endISO };
    window._activeCycle = data;
    window._payrollLocked = false;

    // Add rows for any newly-included cycle dates (existing rows are left as-is)
    populateAllCycleDateRows();

    showPopup("Payroll cycle dates updated by admin");
  } catch (err) {
    console.error("❌ Error refreshing payroll weeks:", err);
  }
}


// Builds the single flat timesheet table (no week-wise grouping — one row
// per calendar day of the selected payroll cycle, all shown at once). Always
// uses a fixed section/tbody id so the rest of the row-level code (addRow,
// deleteRow, copy/paste, the modal, etc.) keeps working unchanged.
const TIMESHEET_SECTION_ID = "section_1";

function renderTimesheetTable() {
  const sectionsDiv = document.getElementById("timesheetSections");
  if (!sectionsDiv) {
    console.error("❌ timesheetSections container not found");
    return;
  }

  sectionsDiv.innerHTML = "";
  sectionCount = 1;

  const section = document.createElement("div");
  section.className = "timesheet-section";
  section.id = TIMESHEET_SECTION_ID;

  // Table skeleton
  const tableWrapper = document.createElement("div");
  tableWrapper.className = "table-responsive";
  const showLT = window._showLunchTravel !== false;
  tableWrapper.innerHTML = `
    <table class="timesheet-table">
      <thead>
        <tr>
          <th>S.No</th><th>Add</th><th>Action</th><th>Date</th><th>Work</th>
          <th>Project Start</th><th>Project End</th><th>Client</th><th>Project</th>
          <th>Project Code</th><th>Reporting Manager</th><th>Activity</th>
          <th>Project Hours</th><th>Billable</th>
          <th style="display:${showLT?'':'none'}">Lunch Time</th>
          <th style="display:${showLT?'':'none'}">Travel Time</th>
          <th>Remarks</th><th>Delete</th>
        </tr>
      </thead>
      <tbody id="timesheetBody_1"></tbody>
    </table>
  `;
  section.appendChild(tableWrapper);

  // Buttons
  const btnDiv = document.createElement("div");
  btnDiv.className = "button-container";
  btnDiv.innerHTML = `
    <button class="add-row-btn" onclick="addRow('${TIMESHEET_SECTION_ID}')">+ Add New Entry</button>
    <button class="save-week-btn" onclick="saveDraft()" style="background:linear-gradient(135deg,#5d5fef,#7c3aed);color:#fff;border:none;padding:.55rem 1.3rem;border-radius:9px;font-size:.88rem;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:.4rem;margin-left:.5rem;"><i class="fas fa-save"></i> Save Draft</button>
  `;
  section.appendChild(btnDiv);

  sectionsDiv.appendChild(section);
}

function _employeeDateKey(value) {
  // Employee_details currently stores Date of Joining/Exit as DD/MM/YYYY.
  // Return a sortable YYYY-MM-DD key without relying on browser timezone.
  const match = String(value || '').trim().match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (match) return `${match[3]}-${match[2]}-${match[1]}`;
  const isoMatch = String(value || '').trim().match(/^(\d{4}-\d{2}-\d{2})/);
  return isoMatch ? isoMatch[1] : '';
}

function _applicableCycleDateKeys() {
  const win = window._currentPayrollWindow;
  if (!win) return null;

  let start = _employeeDateKey(win.start);
  let end = _employeeDateKey(win.end);
  const employee = employeeData.find(e => String(e.EmpID) === String(loggedInEmployeeId)) || {};
  const joiningDate = _employeeDateKey(employee['Date of Joining']);
  const exitDate = _employeeDateKey(employee['Date of Exit']);

  if (joiningDate && joiningDate > start) start = joiningDate;
  if (exitDate && exitDate < end) end = exitDate;
  return { start, end };
}

// Adds one row for every calendar date applicable to the employee in the
// selected payroll cycle that doesn't already have a row. Dates outside the
// recorded employment window are intentionally not auto-created.
function populateAllCycleDateRows() {
  const applicableWindow = _applicableCycleDateKeys();
  if (!applicableWindow || applicableWindow.start > applicableWindow.end) return;
  const tbody = document.getElementById("timesheetBody_1");
  if (!tbody) return;

  const existingDates = new Set(
    Array.from(tbody.querySelectorAll(".date-field")).map(i => i.value).filter(Boolean)
  );

  const start = new Date(`${applicableWindow.start}T00:00:00Z`);
  const end   = new Date(`${applicableWindow.end}T00:00:00Z`);
  const d = new Date(start);
  while (d <= end) {
    const dateStr = d.toISOString().split("T")[0];
    if (!existingDates.has(dateStr)) {
      addRow(TIMESHEET_SECTION_ID, dateStr);
    }
    d.setDate(d.getDate() + 1);
  }
}


/* populate header employee fields */
function populateEmployeeInfo() {
  if (!loggedInEmployeeId) return;
  const emp = employeeData.find(
    (e) => String(e.EmpID) === String(loggedInEmployeeId)
  );
  if (!emp) return;

  const map = {
    employeeId: emp["EmpID"] || "",
    employeeName: emp["Emp Name"] || "",
    designation: emp["Designation Name"] || "",
    partner: emp["Partner"] || "",
    reportingManager: emp["ReportingEmpName"] || "",
    gender:
      emp["Gender"] === "F" ? "Female" : emp["Gender"] === "M" ? "Male" : "",
  };

  Object.entries(map).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) el.value = val;
  });
}

function addRow(sectionId, specificDate = null, insertAfterRow = null) {
  const sectionNum = sectionId.split("_")[1];
  const tbody = document.getElementById(`timesheetBody_${sectionNum}`);
  if (!tbody) {
    console.error("Table body not found for", sectionId);
    return;
  }

  const win = window._currentPayrollWindow;
  const cycleStart = win ? new Date(win.start) : null;
  const cycleEnd   = win ? new Date(win.end)   : null;

  let nextDate;
  if (specificDate) {
    nextDate = new Date(specificDate);
  } else {
    // Find the last used date in the table and default to the day after it
    const dateInputs = tbody.querySelectorAll(".date-field");
    if (dateInputs.length === 0) {
      nextDate = cycleStart ? new Date(cycleStart) : new Date();
    } else {
      const lastInput = dateInputs[dateInputs.length - 1];
      const lastDate = new Date(lastInput.value || cycleStart || new Date());
      nextDate = new Date(lastDate);
      nextDate.setDate(lastDate.getDate() + 1);
    }
    if (cycleEnd && nextDate > cycleEnd) nextDate = new Date(cycleEnd);
    if (cycleStart && nextDate < cycleStart) nextDate = new Date(cycleStart);
  }

  const defaultDate = nextDate.toISOString().split("T")[0];
  const minDate = cycleStart ? cycleStart.toISOString().split("T")[0] : "";
  const maxDate = cycleEnd ? cycleEnd.toISOString().split("T")[0] : "";

  const rowIndex = tbody.querySelectorAll("tr").length + 1;
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td class="col-sno">${rowIndex}</td>
    <td class="col-add"><button class="eye-btn" onclick="openModal(this)"><i class="fas fa-eye"></i></button></td>
    <td class="col-action">
      <button class="add-entry-btn" onclick="addEntryForRow(this)" title="Add another entry for this date"><i class="fas fa-plus"></i></button>
      <button class="copy-btn" onclick="copyRow(this)">Copy</button>
      <button class="paste-btn" onclick="pasteRow(this)">Paste</button>
    </td>
    <td class="col-date form-input">
      <input type="date" class="date-field form-input" value="${defaultDate}" min="${minDate}" max="${maxDate}" onchange="validateDate(this); updateSummary()">
    </td>
    <td class="col-location">
      <select class="location-select form-input" onchange="onLocationChange(this)">
        <option value="Office">Office</option>
        <option value="Client Site">Client Site</option>
        <option value="Work From Home">Work From Home</option>
        <option value="Field Work">Field Work</option>
        <option value="Leave">Leave</option>
        <option value="PHY">PHY</option>
        <option value="Week Off">Week Off</option>
      </select>
    </td>
    <td class="col-project-start"><input type="time" class="project-start form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
    <td class="col-project-end"><input type="time" class="project-end form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
    <td class="col-client"></td>
    <td class="col-project"></td>
    <td class="col-project-code"></td>
    <td class="col-reporting-manager"><input type="text" class="reporting-manager-field form-input" placeholder="Enter Reporting Manager"></td>
    <td class="col-activity" style="min-width: 200px;"><input type="text" class="activity-field form-input" placeholder="Enter Activity" oninput="updateSummary()"></td>
    <td class="col-project-hours"><input type="number" class="project-hours-field form-input" readonly></td>
    <td class="col-billable">
      <select class="billable-select form-input" onchange="updateSummary()">
        <option value="Yes">Billable</option>
        <option value="No">Non-Billable</option>
      </select>
    </td>
    <td class="col-lunch-time" style="display:${window._showLunchTravel!==false?'':'none'}">
      <select class="lunch-time-select form-input">
        <option value="">None</option>
        <option value="15 min">15 min</option>
        <option value="30 min" selected>30 min</option>
        <option value="45 min">45 min</option>
        <option value="1 hr">1 hr</option>
        <option value="1.5 hr">1.5 hr</option>
        <option value="2 hr">2 hr</option>
      </select>
    </td>
    <td class="col-travel-time" style="display:${window._showLunchTravel!==false?'':'none'}">
      <select class="travel-time-select form-input">
        <option value="">None</option>
        <option value="15 min">15 min</option>
        <option value="30 min">30 min</option>
        <option value="45 min">45 min</option>
        <option value="1 hr">1 hr</option>
        <option value="1.5 hr">1.5 hr</option>
        <option value="2 hr">2 hr</option>
        <option value="2.5 hr">2.5 hr</option>
        <option value="3 hr">3 hr</option>
      </select>
    </td>
    <td class="col-remarks"><input type="text" class="remarks-field form-input" placeholder="Additional notes"></td>
    <td class="col-delete"><button class="delete-btn" onclick="deleteRow(this)">Delete</button></td>
  `;

  if (insertAfterRow && insertAfterRow.parentNode === tbody) {
    insertAfterRow.insertAdjacentElement("afterend", tr);
  } else {
    tbody.appendChild(tr);
  }

  // ✅ Setup smart dropdowns for client, project, project code
  setupSmartDropdowns(tr);
  applyLocationTimeRules(tr);

  // Auto focus first input
  setTimeout(() => tr.querySelector("input, select")?.focus(), 100);

  updateRowNumbers(tbody.id);
  updateSummary();
  return tr;
}

// Inserts a fresh, otherwise-blank row directly after the clicked row,
// pre-filled with that same date — the convenient way to log a second
// (or third...) entry for one day without it landing out of order at the
// bottom of the table.
function addEntryForRow(button) {
  const row = button.closest("tr");
  if (!row) return;
  const date = row.querySelector(".date-field")?.value;
  addRow(TIMESHEET_SECTION_ID, date || null, row);
}

// ── TL project-plan status (Project_Plans collection) ───────────────────────
// TLs must be able to see, right where they pick a project, whether it has an
// approved plan and what dates that plan covers. JHS01 is shared services and
// has no such plans, so this is skipped entirely for them.
function _fmtPlanDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d) ? '' : d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

function _clearProjectPlanRow(row) {
  const next = row.nextElementSibling;
  if (next && next.classList.contains('project-meta-row-tl')) next.remove();
}

function _renderProjectPlanRow(row, data) {
  _clearProjectPlanRow(row);
  const metaRow = document.createElement('tr');
  metaRow.className = 'project-meta-row-tl';
  const colCount = row.children.length || 1;
  metaRow.innerHTML = `<td colspan="${colCount}">${_projectPlanStatusHtml(data)}</td>`;
  row.after(metaRow);
}

function _renderProjectPlanModal(data) {
  const el = document.getElementById('modalProjectMetaTL');
  if (!el) return;
  if (!data) {
    el.style.display = 'none';
    el.innerHTML = '';
    return;
  }
  el.innerHTML = _projectPlanStatusHtml(data);
  el.style.display = 'block';
}

function _projectPlanStatusHtml(data) {
  return data.has_plan
    ? `<i class="fas fa-check-circle" style="color:#16a34a;"></i> Project plan found: ${_fmtPlanDate(data.start_date)} – ${_fmtPlanDate(data.end_date)}`
    : `<i class="fas fa-exclamation-triangle" style="color:#dc2626;"></i> No project plan found for this project code`;
}

// target = { row: <tr> } for a table row, or { modal: true } for the entry modal
async function showProjectPlanStatus(projectCode, target) {
  if (!showsProjectPlanStatus()) return;

  const code = (projectCode || '').trim();
  if (!code) {
    if (target.row) _clearProjectPlanRow(target.row);
    else _renderProjectPlanModal(null);
    return;
  }

  try {
    const res = await fetch(`${API_URL}/get_project_plan_status/${encodeURIComponent(code)}`, {
      headers: getHeaders()
    });
    const data = res.ok ? await res.json() : { has_plan: false };
    if (target.row) _renderProjectPlanRow(target.row, data);
    else _renderProjectPlanModal(data);
  } catch (err) {
    console.error('Error checking project plan status:', err);
  }
}
window.showProjectPlanStatus = showProjectPlanStatus;

function createReadonlyProjectCode(value = "", placeholder = "Auto-filled") {
    const wrapper = document.createElement("div");
    wrapper.style.position = "relative";
    wrapper.style.width = "100%";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "project-code form-input";
    input.value = value || "";                      // ensure no undefined
    input.placeholder = placeholder;
    input.readOnly = true;
    input.disabled = true;
    input.setAttribute("readonly", "readonly");
    input.style.backgroundColor = "#f0f0f0";
    input.style.color = value ? "#444" : "#999";   // lighter when empty
    input.style.border = "1px solid #ccc";
    input.style.cursor = "not-allowed";

    // Block all input attempts
    ['keydown', 'keypress', 'input', 'paste'].forEach(event => {
        input.addEventListener(event, (e) => {
            e.preventDefault();
            e.stopPropagation();
        });
    });

    wrapper.appendChild(input);
    return wrapper;
}

// Builds the shared-services Project Code field: a dropdown of the fixed
// SS-team codes plus a "Type Here" option that swaps the dropdown for a
// free-text input (with a button to switch back). Used for JHS01 employees
// in the table row and both modal population paths (openModal/editHistoryRow).
function createSharedServicesProjectCode(currentValue = "", inputId = null) {
  const wrapper = document.createElement("div");
  wrapper.style.width = "100%";

  const isCustomValue = !!currentValue && !SHARED_SERVICES_PROJECT_CODES.includes(currentValue);

  function renderSelect(selectValue) {
    wrapper.innerHTML = "";
    const select = document.createElement("select");
    select.className = "project-code form-input smart-dropdown";
    select.style.width = "100%";
    if (inputId) select.id = inputId;

    const defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = "Select project code";
    select.appendChild(defaultOpt);

    SHARED_SERVICES_PROJECT_CODES.forEach(code => {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = code;
      if (code === selectValue) opt.selected = true;
      select.appendChild(opt);
    });

    const typeHereOpt = document.createElement("option");
    typeHereOpt.value = SHARED_SERVICES_TYPE_HERE;
    typeHereOpt.textContent = SHARED_SERVICES_TYPE_HERE;
    select.appendChild(typeHereOpt);

    select.addEventListener("change", function () {
      if (this.value === SHARED_SERVICES_TYPE_HERE) {
        renderInput("");
      } else {
        updateSummary();
      }
    });

    wrapper.appendChild(select);
  }

  function renderInput(inputValue) {
    wrapper.innerHTML = "";
    const row = document.createElement("div");
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.gap = "5px";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "project-code form-input";
    if (inputId) input.id = inputId;
    input.placeholder = "Enter Project Code";
    input.value = inputValue || "";
    input.style.width = "calc(100% - 35px)";
    input.addEventListener("input", updateSummary);

    const backBtn = document.createElement("button");
    backBtn.type = "button";
    backBtn.title = "Back to dropdown";
    backBtn.innerHTML = '<i class="fas fa-list"></i>';
    backBtn.style.marginLeft = "5px";
    backBtn.style.padding = "6px 10px";
    backBtn.style.cursor = "pointer";
    backBtn.onclick = () => { renderSelect(""); updateSummary(); };

    row.appendChild(input);
    row.appendChild(backBtn);
    wrapper.appendChild(row);
  }

  if (isCustomValue) {
    renderInput(currentValue);
  } else {
    renderSelect(currentValue);
  }

  return wrapper;
}

// Rebuilds a row's Project + Project Code cells for the given Client value.
// "Other" -> Project becomes free text, Project Code becomes a fixed,
// non-typable "Other". A real client -> normal filtered Project dropdown,
// which itself auto-fills Project Code (readonly) once a project is picked.
function _applyRowClientCascade(row, clientValue) {
  const projectCell = row.querySelector(".col-project");
  const projectCodeCell = row.querySelector(".col-project-code");
  if (!projectCell || !projectCodeCell) return;

  if (clientValue === "Other") {
    projectCell.innerHTML = "";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "project-field form-input";
    input.placeholder = "Enter project";
    input.addEventListener("input", updateSummary);
    projectCell.appendChild(input);

    projectCodeCell.innerHTML = "";
    projectCodeCell.appendChild(createReadonlyProjectCode("Other", "Other"));
    updateSummary();
    return;
  }

  projectCell.innerHTML = "";
  const projectDropdown = createSmartDropdown("project", projectCell, "", clientValue);
  projectCell.appendChild(projectDropdown);
  projectDropdown.addEventListener("change", function() {
    _applyRowProjectCode(row, clientValue, this.value);
    updateSummary();
  });

  projectCodeCell.innerHTML = "";
  projectCodeCell.appendChild(createReadonlyProjectCode("", "Auto-filled"));
  updateSummary();
}

// Auto-fills a row's Project Code (readonly) once a real Project is picked.
function _applyRowProjectCode(row, clientValue, projectValue) {
  const projectCodeCell = row.querySelector(".col-project-code");
  if (!projectCodeCell) return;

  let code = "";
  if (clientValue && employeeProjects.projects_by_client && employeeProjects.projects_by_client[clientValue]) {
    const projectData = employeeProjects.projects_by_client[clientValue].find(p => p.project_name === projectValue);
    if (projectData) code = projectData.project_code;
  }
  projectCodeCell.innerHTML = "";
  projectCodeCell.appendChild(createReadonlyProjectCode(code, "Auto-filled"));
  showProjectPlanStatus(code, { row });
}

function setupSmartDropdowns(row) {
  const clientCell = row.querySelector(".col-client");
  const projectCell = row.querySelector(".col-project");
  const projectCodeCell = row.querySelector(".col-project-code");

  // Setup client dropdown
  if (clientCell) {
    clientCell.innerHTML = "";
    const clientDropdown = createSmartDropdown("client", clientCell);
    clientCell.appendChild(clientDropdown);
    if (!window._freeTextClientProject) {
      clientDropdown.addEventListener("change", function() {
        _applyRowClientCascade(row, this.value);
      });
    }
  }

  // Setup project dropdown (empty initially)
  if (projectCell) {
    projectCell.innerHTML = "";
    const emptyProjectDropdown = createSmartDropdown("project", projectCell, "", "");
    projectCell.appendChild(emptyProjectDropdown);
  }

  // Setup project code field (readonly input)
  if (projectCodeCell) {
    projectCodeCell.innerHTML = "";
    if (window._freeTextClientProject) {
      projectCodeCell.appendChild(createSharedServicesProjectCode());
    } else {
      projectCodeCell.appendChild(createReadonlyProjectCode("", "Auto-filled"));
    }
  }
}

// ✅ Smart dropdown creator
// function createSmartDropdown(type, container, currentValue = "") {
//   const dataKey = type === "client" ? "clients" : 
//                   type === "project" ? "projects" : "project_codes";
//   const options = employeeProjects[dataKey] || [];
  
//   const select = document.createElement("select");
//   select.className = `${type}-field form-input smart-dropdown`;
//   select.style.width = "100%";
  
//   // Add default option
//   const defaultOpt = document.createElement("option");
//   defaultOpt.value = "";
//   defaultOpt.textContent = `Select ${type.replace('_', ' ')}`;
//   select.appendChild(defaultOpt);
  
//   // Add filtered options
//   options.forEach(opt => {
//     const option = document.createElement("option");
//     option.value = opt;
//     option.textContent = opt;
//     if (opt === currentValue) option.selected = true;
//     select.appendChild(option);
//   });
  
//   // Add "Type here" option
//   const typeOption = document.createElement("option");
//   typeOption.value = "__TYPE_HERE__";
//   typeOption.textContent = "✏️ Type here (custom entry)";
//   typeOption.style.fontStyle = "italic";
//   typeOption.style.color = "#666";
//   select.appendChild(typeOption);
  
//   // Handle selection
//   select.addEventListener("change", function() {
//     if (this.value === "__TYPE_HERE__") {
//       // Replace with input field
//       const input = document.createElement("input");
//       input.type = "text";
//       input.className = `${type}-field form-input`;
//       input.placeholder = `Enter ${type.replace('_', ' ')}`;
//       input.value = currentValue;
//       input.style.width = "calc(100% - 35px)";
      
//       // Add button to go back to dropdown
//       const backBtn = document.createElement("button");
//       backBtn.className = "back-to-dropdown-btn";
//       backBtn.innerHTML = '<i class="fas fa-list"></i>';
//       backBtn.title = "Back to dropdown";
//       backBtn.type = "button";
//       backBtn.style.marginLeft = "5px";
//       backBtn.style.padding = "6px 10px";
//       backBtn.style.cursor = "pointer";
//       backBtn.onclick = () => {
//         const newDropdown = createSmartDropdown(type, container, input.value);
//         container.innerHTML = "";
//         container.appendChild(newDropdown);
//       };
      
//       container.innerHTML = "";
//       const wrapper = document.createElement("div");
//       wrapper.style.display = "flex";
//       wrapper.style.alignItems = "center";
//       wrapper.style.gap = "5px";
//       wrapper.appendChild(input);
//       wrapper.appendChild(backBtn);
//       container.appendChild(wrapper);
      
//       input.focus();
      
//       // Trigger summary update on input change
//       input.addEventListener("input", updateSummary);
//     }
//   });
  
//   // Trigger summary update on dropdown change
//   select.addEventListener("change", updateSummary);
  
//   return select;
// }

// ✅ Helper to get field value (works with both select and input)
// function getFieldValue(row, className) {
//   const cell = row.querySelector(className);
//   if (!cell) return "";
  
//   const select = cell.querySelector("select");
//   const input = cell.querySelector("input");
  
//   if (select && select.value !== "__TYPE_HERE__" && select.value !== "") {
//     return select.value;
//   } else if (input) {
//     return input.value;
//   }
//   return "";
// }

// ✅ Helper to set field value (works with both select and input)
// function setFieldValue(row, className, value) {
//   const cell = row.querySelector(className);
//   if (!cell) return;
  
//   const select = cell.querySelector("select");
//   const input = cell.querySelector("input");
  
//   if (select) {
//     // Check if value exists in options
//     const option = Array.from(select.options).find(opt => opt.value === value);
//     if (option && value !== "") {
//       select.value = value;
//     } else if (value && value !== "") {
//       // Trigger "Type here" mode
//       select.value = "__TYPE_HERE__";
//       const changeEvent = new Event("change", { bubbles: true });
//       select.dispatchEvent(changeEvent);
//       setTimeout(() => {
//         const newInput = cell.querySelector("input");
//         if (newInput) newInput.value = value;
//       }, 100);
//     }
//   } else if (input) {
//     input.value = value;
//   }
// }

/* utility to create 7 daily dates from a week start */
function getWeekDates(startDate) {
  const d = new Date(startDate);
  const arr = [];
  for (let i = 0; i < 7; i++) {
    const dd = new Date(d);
    dd.setDate(d.getDate() + i);
    arr.push(
      `${dd.getFullYear()}-${String(dd.getMonth() + 1).padStart(2, "0")}-${String(dd.getDate()).padStart(2, "0")}`
    );
  }
  return arr;
}

/* update row numbers after delete/insert */
function updateRowNumbers(tbodyId) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  const rows = tbody.querySelectorAll("tr");
  rows.forEach((r, i) => {
    const sno = r.querySelector(".col-sno");
    if (sno) sno.textContent = i + 1;
  });
}

/* delete row */
function deleteRow(btn) {
  const row = btn.closest("tr");
  if (!row) return;
  const tbody = row.closest("tbody");
  row.remove();
  updateRowNumbers(tbody.id);
  updateSummary();
}

/* Calculations & validations */
function calculateHours(row) {
  if (!row) return;
  const start = row.querySelector(".project-start")?.value;
  const end = row.querySelector(".project-end")?.value;
  const hoursField = row.querySelector(".project-hours-field");
  if (!start || !end) {
    if (hoursField) hoursField.value = "";
    updateSummary();
    return;
  }
  const [sh, sm] = start.split(":").map(Number);
  const [eh, em] = end.split(":").map(Number);
  let startMin = sh * 60 + sm;
  let endMin = eh * 60 + em;
  if (endMin < startMin) endMin += 24 * 60; // overnight allowed
  const hrs = ((endMin - startMin) / 60).toFixed(2);
  if (hoursField) hoursField.value = hrs;

  updateSummary();
}

function validateTimes(rowOrModal, isModal = false) {
  try {
    if (!rowOrModal) return true;
    let startEl, endEl;

    if (isModal) {
      // For modal, we have both and project times - validate via modal ids
      // modal project start/end ids: modalInput3 & modalInput4
      const mPS = document.getElementById("modalInput3");
      const mPE = document.getElementById("modalInput4");

      // check project start/end
      if (mPS && mPE && mPS.value && mPE.value) {
        const [sh, sm] = mPS.value.split(":").map(Number);
        const [eh, em] = mPE.value.split(":").map(Number);
        let s = sh * 60 + sm, e = eh * 60 + em;
        if (e <= s) {
          mPE.classList.add("validation-error");
          showPopup("Project End Time must be later than Project Start Time", true);
          return false;
        } else mPE.classList.remove("validation-error");
      }

    } else {
      // row validation - validate project times
      const projStart = rowOrModal.querySelector(".project-start");
      const projEnd = rowOrModal.querySelector(".project-end");

      if (projStart && projEnd && projStart.value && projEnd.value) {
        const [sh, sm] = projStart.value.split(":").map(Number);
        const [eh, em] = projEnd.value.split(":").map(Number);
        let s = sh * 60 + sm, e = eh * 60 + em;
        if (e <= s) {
          projEnd.classList.add("validation-error");
          showPopup("Project End Time must be later than Project Start Time", true);
          return false;
        } else projEnd.classList.remove("validation-error");
      }

    }
    return true;
  } catch (err) {
    console.warn("validateTimes error", err);
    return true;
  }
}

function validateDate(input) {
    if (!input || !input.value) {
        input?.classList.remove("validation-error");
        return;
    }

    const win = window._currentPayrollWindow;
    if (!win) {
        input.classList.remove("validation-error");
        return;
    }

    const inputDate = new Date(input.value);
    const cycleStart = new Date(win.start);
    const cycleEnd = new Date(win.end);

    inputDate.setHours(0, 0, 0, 0);
    cycleStart.setHours(0, 0, 0, 0);
    cycleEnd.setHours(0, 0, 0, 0);

    if (inputDate < cycleStart || inputDate > cycleEnd) {
        input.classList.add("validation-error");
        const startStr = cycleStart.toLocaleDateString('en-GB');
        const endStr = cycleEnd.toLocaleDateString('en-GB');
        showPopup(`Invalid Date! Only dates from <strong>${startStr}</strong> to <strong>${endStr}</strong> (the selected payroll cycle) are allowed.`, true);
    } else {
        input.classList.remove("validation-error");
    }
}

/* Summary update */
function updateSummary() {
  let total = 0,
    billable = 0,
    nonBillable = 0;
  document.querySelectorAll(".timesheet-section tbody tr").forEach((tr) => {
    const hours =
      parseFloat(tr.querySelector(".project-hours-field")?.value) || 0;
    total += hours;
    const bill = tr.querySelector(".billable-select")?.value;
    if (bill === "Yes") billable += hours;
    else if (bill === "No") nonBillable += hours;
  });

  const totalEl = document.querySelector(
    ".summary-section .total-hours .value"
  );
  const billEl = document.querySelector(
    ".summary-section .billable-hours .value"
  );
  const nonBillEl = document.querySelector(
    ".summary-section .non-billable-hours .value"
  );
  if (totalEl) totalEl.textContent = total.toFixed(2);
  if (billEl) billEl.textContent = billable.toFixed(2);
  if (nonBillEl) nonBillEl.textContent = nonBillable.toFixed(2);
}

/* Copy / Paste rows */
function copyRow(button) {
  const row = button.closest("tr");
  if (!row) return;
  const inputs = Array.from(row.querySelectorAll("input, select"));
  copiedData = {};
  inputs.forEach((inp) => {
    const cls = inp.classList && inp.classList[0] ? inp.classList[0] : null;
    if (cls) copiedData[cls] = inp.value;
  });
  showPopup("Row copied!");
}

function pasteRow(button) {
  if (!copiedData) {
    showPopup("No copied row found", true);
    return;
  }
  const row = button.closest("tr");
  if (!row) return;
  const inputs = Array.from(row.querySelectorAll("input, select"));
  inputs.forEach((inp) => {
    const cls = inp.classList && inp.classList[0] ? inp.classList[0] : null;
    if (cls && copiedData[cls] !== undefined) {
      inp.value = copiedData[cls];
    }
  });
  calculateHours(row);
  updateSummary();
  showPopup("Row pasted!");
}


function pasteAboveCell(sectionId) {
  const sectionNum = sectionId.split("_")[1];
  const tbody = document.getElementById(`timesheetBody_${sectionNum}`);
  if (!tbody) {
    showPopup("Section not found", true);
    return;
  }
  const rows = tbody.querySelectorAll("tr");
  if (rows.length === 0) {
    showPopup("No rows to duplicate. Adding a new row instead.");
    addRow(sectionId);
    return;
  }
  const lastRow = rows[rows.length - 1];
  const newRow = lastRow.cloneNode(true);
  tbody.appendChild(newRow);
  updateRowNumbers(tbody.id);
  updateSummary();
  showPopup("Row duplicated");
}

function getFieldValue(row, className) {
  const cell = row.querySelector(className);
  if (!cell) return "";
  
  // Check if it's a select or input
  const select = cell.querySelector("select");
  const input = cell.querySelector("input");
  
  if (select) {
    return select.value;
  } else if (input) {
    return input.value;
  }
  return "";
}

// function setFieldValue(row, className, value) {
//   const cell = row.querySelector(className);
//   if (!cell) return;
  
//   const select = cell.querySelector("select");
//   const input = cell.querySelector("input");
  
//   if (select) {
//     // Check if value exists in options
//     const option = Array.from(select.options).find(opt => opt.value === value);
//     if (option) {
//       select.value = value;
//     } else if (value) {
//       // Trigger "Type here" mode
//       select.value = "__TYPE_HERE__";
//       select.dispatchEvent(new Event("change"));
//       setTimeout(() => {
//         const newInput = cell.querySelector("input");
//         if (newInput) newInput.value = value;
//       }, 100);
//     }
//   } else if (input) {
//     input.value = value;
//   }
// }


// function openModal(button) {
//   isEditingHistory = false;
//   currentRow = button.closest("tr");
//   currentEntryId = currentRow.getAttribute("data-entry-id");

//   const modalOverlay = document.getElementById("modalOverlay");
//   if (!modalOverlay) {
//     showPopup("Modal not available in layout. Please add modalOverlay div.", true);
//     return;
//   }

//   modalOverlay.style.display = "flex";

//   // Updated mapping - use helper functions for client/project/code
//   document.getElementById("modalInput1").value = currentRow.querySelector(".date-field")?.value || "";
//   document.getElementById("modalInput2").value = currentRow.querySelector(".location-select")?.value || "";
//   document.getElementById("modalInput3").value = currentRow.querySelector(".project-start")?.value || "";
//   document.getElementById("modalInput4").value = currentRow.querySelector(".project-end")?.value || "";
  
//   // ✅ Use helper function for smart dropdown fields
//   // document.getElementById("modalInput5").value = getFieldValue(currentRow, ".col-client");
//   // document.getElementById("modalInput6").value = getFieldValue(currentRow, ".col-project");
//   // document.getElementById("modalInput7").value = getFieldValue(currentRow, ".col-project-code");
//   // In openModal() function, after setting modalInput7 (client)
//   document.getElementById("modalInput5").value = getFieldValue(currentRow, ".col-client");

//   // Add this event listener for client change in modal
//   document.getElementById("modalInput6").addEventListener("change", function() {
//     const selectedClient = this.value;
//     const projectInput = document.getElementById("modalInput6");
//     const projectCodeInput = document.getElementById("modalInput7");
    
//     // Clear project and code
//     projectInput.value = "";
//     projectCodeInput.value = "";
    
//     // Note: You might want to convert modalInput8 to a dropdown as well
//     // For now, this just clears the values when client changes
//   });

//   // Add event listener for project change in modal
//   document.getElementById("modalInput7").addEventListener("input", function() {
//     const selectedProject = this.value;
//     const selectedClient = document.getElementById("modalInput5").value;
    
//     if (selectedClient && employeeProjects.projects_by_client && employeeProjects.projects_by_client[selectedClient]) {
//       const projectData = employeeProjects.projects_by_client[selectedClient].find(
//         p => p.project_name === selectedProject
//       );
      
//       if (projectData) {
//         document.getElementById("modalInput7").value = projectData.project_code;
//       }
//     }
//   });
  
//   document.getElementById("modalInput8").value = currentRow.querySelector(".reporting-manager-field")?.value || "";
//   document.getElementById("modalInput9").value = currentRow.querySelector(".activity-field")?.value || "";
//   document.getElementById("modalInput10").value = currentRow.querySelector(".project-hours-field")?.value || "";
//   document.getElementById("modalInput11").value = currentRow.querySelector(".billable-select")?.value || "";
//   document.getElementById("modalInput12").value = currentRow.querySelector(".remarks-field")?.value || "";

//   updateModalProjectHours();

//   const addBtn = document.getElementById("modalAddBtn");
//   if (addBtn) {
//     addBtn.innerHTML = '<i class="fas fa-check"></i> Save';
//     addBtn.onclick = saveModalEntry;
//   }

//   const cancelBtn = document.getElementById("modalCancelBtn");
//   if (cancelBtn) {
//     cancelBtn.innerHTML = '<i class="fas fa-times"></i> Cancel';
//     cancelBtn.onclick = closeModal;
//   }
// }

// ==========================================
// UPDATED saveModalEntry FUNCTION
// ==========================================

function setFieldValue(row, className, value) {
  const cell = row.querySelector(className);
  if (!cell) return;

  const select = cell.querySelector("select");
  const input = cell.querySelector("input");

  if (select) {
    const optionExists = Array.from(select.options).some(opt => opt.value === value);

    if (!optionExists && value) {
      // Dropdown-only mode has no "type here" escape hatch, but a row saved
      // before a project list changed (or from a former custom entry) still
      // needs to display its actual value rather than silently going blank
      // and losing it on the next save — surface it as a selectable option.
      const legacyOpt = document.createElement("option");
      legacyOpt.value = value;
      legacyOpt.textContent = value;
      select.appendChild(legacyOpt);
    }

    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  } else if (input) {
    input.value = value;
    // Needed so pasting a Client value still cascades the Project combo
    // (Client/Project are plain inputs now — the searchable combo — not a
    // <select>, but they still listen for "change" the same way).
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function openModal(button) {
  isEditingHistory = false;
  currentRow = button.closest("tr");
  currentEntryId = currentRow.getAttribute("data-entry-id");

  const modalOverlay = document.getElementById("modalOverlay");
  if (!modalOverlay) {
    showPopup("Modal not available in layout. Please add modalOverlay div.", true);
    return;
  }

  modalOverlay.style.display = "flex";

  // Set regular fields
  document.getElementById("modalInput1").value = currentRow.querySelector(".date-field")?.value || "";
  document.getElementById("modalInput2").value = currentRow.querySelector(".location-select")?.value || "";
  document.getElementById("modalInput3").value = currentRow.querySelector(".project-start")?.value || "";
  document.getElementById("modalInput4").value = currentRow.querySelector(".project-end")?.value || "";
  
  // ✅ CREATE SMART DROPDOWNS for Client, Project, Project Code
  const clientValue = getFieldValue(currentRow, ".col-client");
  const projectValue = getFieldValue(currentRow, ".col-project");
  const projectCodeValue = getFieldValue(currentRow, ".col-project-code");
  
  // Clear and create client dropdown
  const clientContainer = document.getElementById("modalClientContainer");
  if (clientContainer) {
    clientContainer.innerHTML = "";
    const clientDropdown = createSmartDropdown("client", clientContainer, clientValue);
    clientContainer.appendChild(clientDropdown);

    // Add change listener to update project dropdown (dropdown mode only —
    // free-text client/project fields are independent of one another)
    if (!window._freeTextClientProject) {
      clientDropdown.addEventListener("change", function() {
        updateModalProjectDropdown(this.value, "");
      });
    }
  }

  if (window._freeTextClientProject) {
    // Free-text partner: Client/Project are independent plain fields.
    const projectContainer = document.getElementById("modalProjectContainer");
    if (projectContainer) {
      projectContainer.innerHTML = "";
      projectContainer.appendChild(createSmartDropdown("project", projectContainer, projectValue, clientValue));
    }
    const projectCodeContainer = document.getElementById("modalProjectCodeContainer");
    if (projectCodeContainer) {
      projectCodeContainer.innerHTML = "";
      projectCodeContainer.appendChild(createSharedServicesProjectCode(projectCodeValue, "modalProjectCodeInput"));
    }
    showProjectPlanStatus(projectCodeValue, { modal: true });
  } else if (clientValue === "Other") {
    _renderModalProjectOther(projectValue);
  } else {
    // Clear and create project dropdown
    const projectContainer = document.getElementById("modalProjectContainer");
    if (projectContainer) {
      projectContainer.innerHTML = "";
      const projectDropdown = createSmartDropdown("project", projectContainer, projectValue, clientValue);
      projectContainer.appendChild(projectDropdown);

      // Add change listener to auto-fill project code
      projectDropdown.addEventListener("change", function() {
        const currentClient = clientContainer?.querySelector("input")?.value;
        updateModalProjectCode(currentClient, this.value);
      });
    }

    // Clear and create project code field
    const projectCodeContainer = document.getElementById("modalProjectCodeContainer");
    if (projectCodeContainer) {
      projectCodeContainer.innerHTML = "";
      const codeInput = document.createElement("input");
      codeInput.type = "text";
      codeInput.id = "modalProjectCodeInput";
      codeInput.className = "form-input";
      codeInput.value = projectCodeValue;
      codeInput.readOnly = true;
      codeInput.style.backgroundColor = "#f0f0f0";
      projectCodeContainer.appendChild(codeInput);
    }
    showProjectPlanStatus(projectCodeValue, { modal: true });
  }

  // Set other fields
  document.getElementById("modalInput8").value = currentRow.querySelector(".reporting-manager-field")?.value || "";
  document.getElementById("modalInput9").value = currentRow.querySelector(".activity-field")?.value || "";
  document.getElementById("modalInput10").value = currentRow.querySelector(".project-hours-field")?.value || "";
  document.getElementById("modalInput11").value = currentRow.querySelector(".billable-select")?.value || "";
  // Lunch & Travel Time
  const lunchSel = document.getElementById("modalInput13");
  if (lunchSel) lunchSel.value = currentRow.querySelector(".lunch-time-select")?.value || "";
  const travelSel = document.getElementById("modalInput14");
  if (travelSel) travelSel.value = currentRow.querySelector(".travel-time-select")?.value || "";
  document.getElementById("modalInput12").value = currentRow.querySelector(".remarks-field")?.value || "";
  applyModalLocationTimeRules();

  updateModalHours();

  const addBtn = document.getElementById("modalAddBtn");
  if (addBtn) {
    addBtn.innerHTML = '<i class="fas fa-check"></i> Save';
    addBtn.onclick = saveModalEntry;
  }

  const cancelBtn = document.getElementById("modalCancelBtn");
  if (cancelBtn) {
    cancelBtn.innerHTML = '<i class="fas fa-times"></i> Cancel';
    cancelBtn.onclick = closeModal;
  }
}

// Renders Project as free text + Project Code as a fixed, non-typable
// "Other" in the modal — used whenever Client is "Other".
function _renderModalProjectOther(projectValue = "") {
  const projectContainer = document.getElementById("modalProjectContainer");
  if (projectContainer) {
    projectContainer.innerHTML = "";
    const input = document.createElement("input");
    input.type = "text";
    input.className = "project-field form-input";
    input.placeholder = "Enter project";
    input.value = projectValue || "";
    projectContainer.appendChild(input);
  }

  const projectCodeContainer = document.getElementById("modalProjectCodeContainer");
  if (projectCodeContainer) {
    projectCodeContainer.innerHTML = "";
    const codeInput = document.createElement("input");
    codeInput.type = "text";
    codeInput.id = "modalProjectCodeInput";
    codeInput.className = "form-input";
    codeInput.value = "Other";
    codeInput.readOnly = true;
    codeInput.disabled = true;
    codeInput.style.backgroundColor = "#f0f0f0";
    codeInput.style.cursor = "not-allowed";
    projectCodeContainer.appendChild(codeInput);
  }
  showProjectPlanStatus("", { modal: true });
}

// Update project dropdown when client changes in modal
function updateModalProjectDropdown(selectedClient, selectedProject = "") {
  if (window._freeTextClientProject) return; // free-text fields are independent, nothing to cascade
  if (selectedClient === "Other") {
    _renderModalProjectOther(selectedProject);
    return;
  }
  const projectContainer = document.getElementById("modalProjectContainer");
  if (!projectContainer) return;

  projectContainer.innerHTML = "";
  const projectDropdown = createSmartDropdown("project", projectContainer, selectedProject, selectedClient);
  projectContainer.appendChild(projectDropdown);

  // Add change listener
  projectDropdown.addEventListener("change", function() {
    updateModalProjectCode(selectedClient, this.value);
  });

  // Reset project code to readonly
  const projectCodeContainer = document.getElementById("modalProjectCodeContainer");
  if (projectCodeContainer) {
    projectCodeContainer.innerHTML = "";
    const codeInput = document.createElement("input");
    codeInput.type = "text";
    codeInput.id = "modalProjectCodeInput";
    codeInput.className = "form-input";
    codeInput.value = "";
    codeInput.readOnly = true;
    codeInput.placeholder = "Auto-filled";
    codeInput.style.backgroundColor = "#f0f0f0";
    projectCodeContainer.appendChild(codeInput);
  }
  showProjectPlanStatus("", { modal: true });
}

// Auto-fill project code in modal
// function updateModalProjectCode(clientValue, projectValue) {
//   if (!clientValue || !projectValue) return;
  
//   if (employeeProjects.projects_by_client && employeeProjects.projects_by_client[clientValue]) {
//     const projectData = employeeProjects.projects_by_client[clientValue].find(
//       p => p.project_name === projectValue
//     );
    
//     if (projectData) {
//       const projectCodeInput = document.getElementById("modalProjectCodeInput");
//       if (projectCodeInput) {
//         projectCodeInput.value = projectData.project_code;
//       }
//     }
//   }
// }

function updateModalProjectCode(clientValue, projectValue) {
  if (window._freeTextClientProject) return; // project code stays freely editable, never auto-locked
  const projectCodeInput = document.getElementById("modalProjectCodeInput");
  if (!projectCodeInput) return;

  // 🟢 Normal project
  if (
    clientValue &&
    employeeProjects.projects_by_client &&
    employeeProjects.projects_by_client[clientValue]
  ) {
    const projectData =
      employeeProjects.projects_by_client[clientValue].find(
        p => p.project_name === projectValue
      );

    if (projectData) {
      projectCodeInput.value = projectData.project_code;
      projectCodeInput.readOnly = true;
      projectCodeInput.style.backgroundColor = "#f0f0f0";
      showProjectPlanStatus(projectData.project_code, { modal: true });
      return;
    }
  }
  showProjectPlanStatus("", { modal: true });
}


// function saveModalEntry() {
//   if (!currentRow) return;

//   // Date
//   const dateField = currentRow.querySelector(".date-field");
//   if (dateField) dateField.value = document.getElementById("modalInput1").value;

//   // Location
//   const locationField = currentRow.querySelector(".location-select");
//   if (locationField) locationField.value = document.getElementById("modalInput2").value;

//   // Times

//   const projectStart = currentRow.querySelector(".project-start");
//   if (projectStart) projectStart.value = document.getElementById("modalInput3").value;

//   const projectEnd = currentRow.querySelector(".project-end");
//   if (projectEnd) projectEnd.value = document.getElementById("modalInput4").value;

//   // ✅ Smart dropdown fields - use helper function
//   setFieldValue(currentRow, ".col-client", document.getElementById("modalInput5").value);
//   setFieldValue(currentRow, ".col-project", document.getElementById("modalInput6").value);
//   setFieldValue(currentRow, ".col-project-code", document.getElementById("modalInput7").value);

//   // Other fields
//   const reportingManager = currentRow.querySelector(".reporting-manager-field");
//   if (reportingManager) reportingManager.value = document.getElementById("modalInput8").value;

//   const activity = currentRow.querySelector(".activity-field");
//   if (activity) activity.value = document.getElementById("modalInput9").value;

//   const projectHours = currentRow.querySelector(".project-hours-field");
//   if (projectHours) projectHours.value = document.getElementById("modalInput10").value;

//   const billable = currentRow.querySelector(".billable-select");
//   if (billable) billable.value = document.getElementById("modalInput11").value;

//   const remarks = currentRow.querySelector(".remarks-field");
//   if (remarks) remarks.value = document.getElementById("modalInput12").value;

//   calculateHours(currentRow);
//   validateDate(currentRow.querySelector(".date-field"));
//   closeModal();
//   updateSummary();
// }


function saveModalEntry() {
  if (!currentRow) return;

  // Date
  const dateField = currentRow.querySelector(".date-field");
  if (dateField) dateField.value = document.getElementById("modalInput1").value;

  // Location
  const locationField = currentRow.querySelector(".location-select");
  if (locationField) locationField.value = document.getElementById("modalInput2").value;

  // Times
  const projectStart = currentRow.querySelector(".project-start");
  if (projectStart) projectStart.value = document.getElementById("modalInput3").value;

  const projectEnd = currentRow.querySelector(".project-end");
  if (projectEnd) projectEnd.value = document.getElementById("modalInput4").value;

  // ── Client (always a plain input now — combo or free text) ──────────────────
  const clientContainer = document.getElementById("modalClientContainer");
  const clientValue = (clientContainer?.querySelector("input")?.value || "").trim();

  const clientCell = currentRow.querySelector(".col-client");
  if (clientCell) {
    const existingInp = clientCell.querySelector("input");
    if (existingInp) {
      existingInp.value = clientValue;
    } else {
      clientCell.innerHTML = `<input type="text" class="client-field form-input" value="${clientValue}">`;
    }
  }

  // ── Project (always a plain input now — combo or free text) ─────────────────
  const projectContainer = document.getElementById("modalProjectContainer");
  const projectValue = (projectContainer?.querySelector("input")?.value || "").trim();

  const projectCell = currentRow.querySelector(".col-project");
  if (projectCell) {
    const existingInp = projectCell.querySelector("input");
    if (existingInp) {
      existingInp.value = projectValue;
    } else {
      projectCell.innerHTML = `<input type="text" class="project-field form-input" value="${projectValue}">`;
    }
  }

  // ── Project Code ─────────────────────────────────────────────────────────────
  const projectCodeInput = document.getElementById("modalProjectCodeInput");
  const projectCodeValue = projectCodeInput?.value || "";
  const codeCell = currentRow.querySelector(".col-project-code");
  if (codeCell) {
    if (window._freeTextClientProject) {
      codeCell.innerHTML = "";
      codeCell.appendChild(createSharedServicesProjectCode(projectCodeValue));
    } else {
      const codeInp = codeCell.querySelector("input");
      if (codeInp) codeInp.value = projectCodeValue;
      else codeCell.innerHTML = `<input type="text" class="project-code form-input" value="${projectCodeValue}" readonly style="background:#f0f0f0;">`;
    }
  }

  // ── Other fields ─────────────────────────────────────────────────────────────
  const reportingManager = currentRow.querySelector(".reporting-manager-field");
  if (reportingManager) reportingManager.value = document.getElementById("modalInput8").value;

  const activity = currentRow.querySelector(".activity-field");
  if (activity) activity.value = document.getElementById("modalInput9").value;

  const projectHours = currentRow.querySelector(".project-hours-field");
  if (projectHours) projectHours.value = document.getElementById("modalInput10").value;

  const billable = currentRow.querySelector(".billable-select");
  if (billable) billable.value = document.getElementById("modalInput11").value;

  // Lunch & Travel Time
  const lunchSel = currentRow.querySelector(".lunch-time-select");
  if (lunchSel) lunchSel.value = document.getElementById("modalInput13")?.value || "";
  const travelSel = currentRow.querySelector(".travel-time-select");
  if (travelSel) travelSel.value = document.getElementById("modalInput14")?.value || "";
  applyLocationTimeRules(currentRow);

  const remarks = currentRow.querySelector(".remarks-field");
  if (remarks) remarks.value = document.getElementById("modalInput12").value;

  calculateHours(currentRow);
  validateDate(currentRow.querySelector(".date-field"));
  closeModal();
  updateSummary();
}

function closeModal() {
  const modal = document.getElementById("modalOverlay");
  if (modal) modal.style.display = "none";
  currentRow = null;
  isEditingHistory = false;
  currentEntryId = null;
}

function updateModalHours() {
  // Project hours from modalInput4/5 -> modalInput10
  const projectStart = document.getElementById("modalInput3")?.value;
  const projectEnd = document.getElementById("modalInput4")?.value;
  const projectHoursInput = document.getElementById("modalInput10");

  if (projectStart && projectEnd && projectHoursInput) {
    const [sh, sm] = projectStart.split(":").map(Number);
    const [eh, em] = projectEnd.split(":").map(Number);
    let s = sh * 60 + sm;
    let e = eh * 60 + em;
    if (e < s) e += 24 * 60;
    projectHoursInput.value = ((e - s) / 60).toFixed(2);
  }
}

/* Manager employee details modal (opens timeline and feedback) */
async function openEmployeeDetails(employeeId, cycleId) {
  console.log("🔹 Opening employee timesheet for:", employeeId, "cycle:", cycleId);

  const modal = document.getElementById("modalOverlay");
  const modalContent = modal?.querySelector(".modal-content");
  if (!modal || !modalContent) {
    console.error("❌ modalOverlay not found");
    showPopup("Modal not found in DOM.", true);
    return;
  }

  if (!window._originalModalHTML) {
    window._originalModalHTML = modalContent.innerHTML;
  }

  modal.style.display = "flex";
  modal.style.flexDirection = "column";
  modalContent.innerHTML = `
    <h3 style="text-align:center;margin-bottom:10px;">Loading Timesheet...</h3>
    <p style="text-align:center;">Please wait while we fetch employee details.</p>
  `;

  try {
    const url = cycleId
      ? `${API_URL}/get_timesheet/${employeeId}?cycle_id=${encodeURIComponent(cycleId)}`
      : `${API_URL}/get_timesheet/${employeeId}`;
    const historyUrl = cycleId
      ? `${API_URL}/timesheet/approval-history/${employeeId}?cycle_id=${encodeURIComponent(cycleId)}`
      : `${API_URL}/timesheet/approval-history/${employeeId}`;
    const [response, historyRes] = await Promise.all([
      fetch(url, { method: "GET", headers: getHeaders() }),
      fetch(historyUrl, { method: "GET", headers: getHeaders() }).catch(() => null),
    ]);

    if (!response.ok) throw new Error("Failed to fetch timesheet data");
    const data = await response.json();

    let approvalHistoryHTML = '';
    if (historyRes && historyRes.ok) {
      try {
        const historyData = await historyRes.json();
        approvalHistoryHTML = _buildApprovalHistoryLog(historyData.events || [], cycleId);
      } catch (e) { console.error('approval history parse error', e); }
    }

    if (!data.entries || data.entries.length === 0) {
      modalContent.innerHTML = `
        <h3 style="text-align:center;">No Timesheet Data Found</h3>
        <p style="text-align:center;">This employee hasn’t submitted any data.</p>
        <div style="text-align:center;margin-top:10px;">
          <button class="modal-cancel-btn" onclick="closeModalAndRestore()">Close</button>
        </div>`;
      return;
    }

    const empDetailsHTML = `
      <div style="
        background:#f8f9fa;
        border-radius:12px;
        padding:1rem 1.5rem;
        margin-bottom:1rem;
        border-left:5px solid #3498db;
        box-shadow:0 2px 6px rgba(0,0,0,0.05);
      ">
        <h3 style="margin-bottom:1rem;text-align:center;color:#2c3e50;">Employee Details</h3>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:0.5rem 1rem;">
          <p><strong>Employee ID:</strong> ${data.employee_id || "-"}</p>
          <p><strong>Employee Name:</strong> ${data.employee_name || "-"}</p>
          <p><strong>Designation:</strong> ${data.designation || "-"}</p>
          <p><strong>Gender:</strong> ${data.gender || "-"}</p>
          <p><strong>Partner:</strong> ${data.partner || "-"}</p>
          <p><strong>Reporting Manager:</strong> ${data.reporting_manager || "-"}</p>
          ${data.cycle_label ? `<p style="grid-column:1/-1;"><strong>Payroll Cycle:</strong> <span style="background:#e0e7ff;color:#3730a3;padding:.2rem .7rem;border-radius:8px;font-weight:700;font-size:.88rem;">${data.cycle_label}</span></p>` : ''}
        </div>
      </div>
    `;

    let tableHTML = `
      <div style="max-height:55vh;overflow-y:auto;">
      <table class="timesheet-table" style="width:100%;font-size:14px;">
        <thead>
          <tr>
            <th>Date</th>
            <th>Client</th>
            <th>Project</th>
            <th>Activity</th>
            <th>Work</th>
            <th>Start</th>
            <th>End</th>
            <th>Hours</th>
            <th>Billable</th>
            <th>Remarks</th>
          </tr>
        </thead>
        <tbody>
          ${data.entries.map(entry => `
            <tr>
              <td>${entry.date || "-"}</td>
              <td>${entry.client || "-"}</td>
              <td>${entry.project || "-"}</td>
              <td>${entry.activity || "-"}</td>
              <td>${entry.location || "-"}</td>
              <td>${entry.start_time || "-"}</td>
              <td>${entry.end_time || "-"}</td>
              <td>${entry.hours || "-"}</td>
              <td>${entry.billable || "-"}</td>
              <td>${entry.remarks || "-"}</td>
            </tr>
          `).join("")}
        </tbody>
      </table></div>
    `;

    const feedbackHTML = `
      <div class="feedback-grid" style="margin-top:1.5rem;">
        <div class="feedback-card" style="border-left:4px solid #2ecc71;"><h3>3 HITS</h3><p>${data.hits || "-"}</p></div>
        <div class="feedback-card" style="border-left:4px solid #e67e22;"><h3>3 MISSES</h3><p>${data.misses || "-"}</p></div>
        <div class="feedback-card" style="border-left:4px solid #3498db;"><h3>FEEDBACK FOR HR</h3><p>${data.feedback_hr || "-"}</p></div>
        <div class="feedback-card" style="border-left:4px solid #9b59b6;"><h3>FEEDBACK FOR IT</h3><p>${data.feedback_it || "-"}</p></div>
        <div class="feedback-card" style="border-left:4px solid #1abc9c;"><h3>FEEDBACK FOR CRM</h3><p>${data.feedback_crm || "-"}</p></div>
        <div class="feedback-card" style="border-left:4px solid #e74c3c;"><h3>FEEDBACK FOR OTHERS</h3><p>${data.feedback_others || "-"}</p></div>
        <div class="feedback-card" style="border-left:4px solid #f1c40f;">
          <h3>IDLE TIME</h3>
          <p>
            <strong>Idle Time?</strong> ${data.idle_time_status || 'No'}<br>
            ${data.idle_time_status === 'Yes' ? `<strong>Time:</strong> ${data.idle_time_hours || '-'}<br><strong>Reason:</strong> ${data.idle_time_reason || '-'}` : ''}
          </p>
        </div>
      </div>
    `;

    modalContent.innerHTML = `
      <div class="manager-view-wrapper">
        <h2 style="text-align:center;margin-bottom:1rem;">Employee Timesheet</h2>
        ${empDetailsHTML}
        ${tableHTML}
        ${feedbackHTML}
        ${approvalHistoryHTML}
      </div>
      <div style="text-align:center;margin-top:20px;">
        <button class="modal-cancel-btn" onclick="closeModalAndRestore()">Close</button>
      </div>
    `;
  } catch (err) {
    console.error("❌ Error loading employee details:", err);
    modalContent.innerHTML = `
      <p style="color:red;text-align:center;">Failed to load timesheet data.</p>
      <div style="text-align:center;margin-top:10px;">
        <button class="modal-cancel-btn" onclick="closeModalAndRestore()">Close</button>
      </div>
    `;
  }
}

// Renders the full submit/resubmit/reject/approve audit trail for a cycle —
// used both in the manager's employee-details popup and the employee's own
// History page, so both sides see the same complete track record. Each
// submit/resubmit/reject/approve event carries a snapshot of the timesheet
// entries as they stood at that moment (see backend's Approval_History
// collection), so past rejected versions stay viewable even after a
// resubmission overwrites the "live" data.
function _buildApprovalHistoryLog(events, cycleId) {
  if (!events || !events.length) return '';

  window._approvalHistoryByCycle = window._approvalHistoryByCycle || {};
  if (cycleId) window._approvalHistoryByCycle[cycleId] = events;

  const fmtDate = iso => {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); }
    catch { return iso; }
  };

  const meta = {
    submitted:   { icon: 'fa-paper-plane',    color: '#6366f1', label: 'Submitted' },
    resubmitted: { icon: 'fa-rotate-right',   color: '#f59e0b', label: 'Resubmitted' },
    rejected:    { icon: 'fa-circle-xmark',   color: '#ef4444', label: 'Rejected' },
    approved:    { icon: 'fa-circle-check',   color: '#10b981', label: 'Approved' },
  };

  const rows = events.map((ev, idx) => {
    const m = meta[ev.action] || { icon: 'fa-circle', color: '#94a3b8', label: ev.action };
    const who = ev.actor_name ? ` by ${ev.actor_name}` : '';
    const reasonLine = ev.reason
      ? `<div style="color:#64748b;margin-top:.15rem;font-size:.8rem;">Reason: ${ev.reason}</div>`
      : '';
    const viewBtn = (ev.entries && ev.entries.length && cycleId)
      ? `<button type="button" onclick="showApprovalSnapshot('${cycleId}', ${idx})" style="margin-top:.35rem;font-size:.72rem;padding:.2rem .6rem;border:1px solid #cbd5e1;border-radius:6px;background:#fff;color:#475569;cursor:pointer;"><i class="fas fa-eye"></i> View Timesheet</button>`
      : '';
    return `
      <div style="display:flex;gap:.75rem;padding:.55rem 0;border-bottom:1px solid #e5e7eb;">
        <div style="width:30px;height:30px;flex:0 0 30px;border-radius:50%;background:${m.color};color:#fff;display:flex;align-items:center;justify-content:center;font-size:.82rem;"><i class="fas ${m.icon}"></i></div>
        <div>
          <div style="font-weight:700;color:${m.color};font-size:.86rem;">${m.label}${who}</div>
          <div style="color:#94a3b8;font-size:.76rem;">${fmtDate(ev.timestamp)}${ev.cycle_label ? ' · ' + ev.cycle_label : ''}</div>
          ${reasonLine}
          ${viewBtn}
        </div>
      </div>`;
  }).join('');

  return `
    <div style="background:#f8fafc;border-radius:12px;padding:1rem 1.5rem;margin-top:1rem;border-left:5px solid #f59e0b;box-shadow:0 2px 6px rgba(0,0,0,0.05);">
      <h3 style="margin-bottom:.75rem;text-align:center;color:#2c3e50;"><i class="fas fa-route"></i> Approval History</h3>
      ${rows}
    </div>
  `;
}

// Opens a read-only popup showing exactly what the timesheet looked like at
// one point in its history (e.g. the version that was rejected), pulled from
// the snapshot cached by _buildApprovalHistoryLog.
function showApprovalSnapshot(cycleId, idx) {
  const events = (window._approvalHistoryByCycle || {})[cycleId] || [];
  const ev = events[idx];
  if (!ev || !ev.entries) return;

  const showLunchTravel = window._showLunchTravel !== false;
  const rows = ev.entries.map((e, i) => `
    <tr>
      <td>${i + 1}</td>
      <td>${e.date || ''}</td>
      <td>${e.location || ''}</td>
      <td>${e.client || ''}</td>
      <td>${e.project || ''}</td>
      <td>${e.projectCode || ''}</td>
      <td>${e.activity || ''}</td>
      <td>${e.projectStartTime || ''}</td>
      <td>${e.projectEndTime || ''}</td>
      <td>${e.projectHours || ''}</td>
      <td>${e.billable || ''}</td>
      ${showLunchTravel ? `<td>${e.lunchTime || ''}</td>` : ''}
      <td>${e.remarks || ''}</td>
    </tr>`).join('');

  let overlay = document.getElementById('snapshotModalOverlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'snapshotModalOverlay';
    overlay.style.cssText = 'display:flex;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;align-items:center;justify-content:center;padding:1.5rem;';
    overlay.innerHTML = `
      <div style="background:#fff;border-radius:14px;max-width:95vw;width:1150px;max-height:85vh;overflow:auto;padding:1.5rem;">
        <div id="snapshotModalTitle" style="font-weight:800;font-size:1.05rem;margin-bottom:1rem;color:#2c3e50;"></div>
        <div id="snapshotModalBody" style="overflow-x:auto;"></div>
        <div style="text-align:center;margin-top:1.2rem;">
          <button class="modal-cancel-btn" onclick="document.getElementById('snapshotModalOverlay').style.display='none';">Close</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
  } else {
    overlay.style.display = 'flex';
  }

  const label = ev.action.charAt(0).toUpperCase() + ev.action.slice(1);
  const when = (() => { try { return new Date(ev.timestamp).toLocaleString('en-IN'); } catch { return ev.timestamp; } })();
  document.getElementById('snapshotModalTitle').textContent =
    `${label} — ${ev.cycle_label || ''} (${when})`;
  document.getElementById('snapshotModalBody').innerHTML = `
    <table class="timesheet-table" style="width:100%;font-size:13px;">
      <thead>
        <tr>
          <th>#</th><th>Date</th><th>Work</th><th>Client</th><th>Project</th><th>Code</th>
          <th>Activity</th><th>Start</th><th>End</th><th>Hours</th><th>Billable</th>
          ${showLunchTravel ? '<th>Lunch</th>' : ''}
          <th>Remarks</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function closeModalAndRestore() {
  const modal = document.getElementById("modalOverlay");
  const modalContent = modal?.querySelector(".modal-content");
  if (modal && window._originalModalHTML) {
    modalContent.innerHTML = window._originalModalHTML;
    modal.style.display = "none";
  } else {
    closeModal();
  }
}

async function loadHistory(){
          try {
            showLoading("Fetching History...");
            // Refresh submission status
            try {
              const sr = await fetch(`${API_URL}/timesheet/submission-status/${loggedInEmployeeId}`, { headers: getHeaders() });
              if (sr.ok) { const sd = await sr.json(); _submittedCycles = sd.status || {}; }
            } catch(e) {}

            // Fetch timesheet history, approval tracker, AND the full approval
            // audit trail (submit/resubmit/reject/approve events) in parallel
            const [response, trackerRes, historyLogRes] = await Promise.all([
              fetch(`${API_URL}/timesheets/${loggedInEmployeeId}`, { headers: getHeaders() }),
              fetch(`${API_URL}/timesheet/approval-tracker/${loggedInEmployeeId}`, { headers: getHeaders() }).catch(() => null),
              fetch(`${API_URL}/timesheet/approval-history/${loggedInEmployeeId}`, { headers: getHeaders() }).catch(() => null),
            ]);
            if (!response.ok) throw new Error('Failed to fetch history');

            const data = await response.json();
            const payrolls = (data.payrolls || []).slice().reverse(); // latest first
            historyEntries = []; // reset flat list

            // Build cycle_id → approval status map
            window._approvalStatusMap = {};
            if (trackerRes && trackerRes.ok) {
              try {
                const td = await trackerRes.json();
                (td.statuses || []).forEach(s => { window._approvalStatusMap[s.cycle_id] = s; });
              } catch (e) {}
            }

            // Build cycle_id → full audit trail (submit/resubmit/reject/approve events)
            window._approvalHistoryMap = {};
            if (historyLogRes && historyLogRes.ok) {
              try {
                const hd = await historyLogRes.json();
                (hd.events || []).forEach(ev => {
                  if (!ev.cycle_id) return;
                  (window._approvalHistoryMap[ev.cycle_id] = window._approvalHistoryMap[ev.cycle_id] || []).push(ev);
                });
              } catch (e) {}
            }

            const historyContent = document.getElementById('historyContent');
            historyContent.innerHTML = '';

            if (!payrolls.length) {
                historyContent.innerHTML = '<p style="padding:2rem;color:#888;">No timesheet entries found.</p>';
                hideLoading();
                return;
            }

            // ── Build payroll filter + search bar ─────────────────────────────
            const filterWrap = document.createElement('div');
            filterWrap.style.cssText = 'margin-bottom:1.5rem;padding:1rem 1.5rem;background:#f0f4ff;border-radius:12px;border:2px solid #c5cef9;display:flex;align-items:center;gap:1rem;flex-wrap:wrap;';
            filterWrap.innerHTML = `
              <label style="font-weight:700;font-size:.9rem;color:#5d5fef;white-space:nowrap;"><i class="fas fa-calendar-alt"></i> Filter by Payroll:</label>
              <select id="historyPayrollFilter" style="padding:.6rem 1rem;border:2px solid #c5cef9;border-radius:9px;font-size:.9rem;font-family:inherit;background:#fff;color:#2c3e50;font-weight:600;min-width:220px;" onchange="filterHistoryByPayroll()">
                <option value="all">All Payrolls</option>
                ${payrolls.map(p => `<option value="${p.cycle_id}">${p.cycle_label}${p.submitted ? ' ✅' : ' (draft)'}</option>`).join('')}
              </select>
              <div id="historyPayrollSummary" style="font-size:.85rem;color:#475569;margin-left:auto;"></div>
            `;
            historyContent.appendChild(filterWrap);

            // Container for payroll cards
            const payrollsContainer = document.createElement('div');
            payrollsContainer.id = 'historyPayrollsContainer';
            historyContent.appendChild(payrollsContainer);

            // Pagination container
            const paginationContainer = document.createElement('div');
            paginationContainer.id = 'historyPagination';
            paginationContainer.style.cssText = 'display:flex;gap:.5rem;justify-content:center;margin-top:1.5rem;flex-wrap:wrap;';
            historyContent.appendChild(paginationContainer);

            // Store payrolls globally for filter
            window._historyPayrolls = payrolls;
            window._historyPage = 1;

            // Flatten for export compatibility
            payrolls.forEach(p => {
              (p.entries || []).forEach(e => historyEntries.push(e));
            });

            // Render all payrolls initially
            _renderHistoryPayrolls(payrolls);

            // Update overall summary
            _updateHistorySummary(payrolls);

            hideLoading();
          } catch (error) {
            console.error('Error fetching history:', error);
            hideLoading();
          }
}

function filterHistoryByPayroll() {
  const sel = document.getElementById('historyPayrollFilter');
  const cycleId = sel?.value || 'all';
  const payrolls = window._historyPayrolls || [];
  const filtered = cycleId === 'all' ? payrolls : payrolls.filter(p => p.cycle_id === cycleId);
  window._historyPage = 1; // reset to first page on filter change
  _renderHistoryPayrolls(filtered);
  _updateHistorySummary(filtered);
}

function _updateHistorySummary(payrolls) {
  let total = 0, billable = 0, nonBillable = 0;
  payrolls.forEach(p => {
    total      += p.totalHours || 0;
    billable   += p.totalBillableHours || 0;
    nonBillable += p.totalNonBillableHours || 0;
  });

  // Update the summary cards
  const th = document.querySelector('.history-summary .total-hours .value');
  const bh = document.querySelector('.history-summary .billable-hours .value');
  const nb = document.querySelector('.history-summary .non-billable-hours .value');
  if (th) th.textContent = total.toFixed(2);
  if (bh) bh.textContent = billable.toFixed(2);
  if (nb) nb.textContent = nonBillable.toFixed(2);

  const summary = document.getElementById('historyPayrollSummary');
  if (summary) summary.textContent = `${total.toFixed(1)} hrs total | ${billable.toFixed(1)} billable`;
}

const HISTORY_PAGE_SIZE = 5;

function _getApprovalStatusBadge(cycleId) {
  const s = (window._approvalStatusMap || {})[cycleId];
  if (!s) return '';
  const cfg = {
    draft:     { color: '#f59e0b', bg: '#fef3c7', icon: 'fa-pencil-alt',    label: 'Draft'     },
    pending:   { color: '#3b82f6', bg: '#dbeafe', icon: 'fa-hourglass-half', label: 'Pending Approval' },
    submitted: { color: '#6366f1', bg: '#e0e7ff', icon: 'fa-paper-plane',   label: 'Submitted' },
    approved:  { color: '#10b981', bg: '#d1fae5', icon: 'fa-check-circle',  label: 'Approved'  },
    rejected:  { color: '#ef4444', bg: '#fee2e2', icon: 'fa-times-circle',  label: 'Rejected'  },
  };
  const c = cfg[s.status] || cfg.submitted;
  return `<span style="display:inline-flex;align-items:center;gap:.4rem;padding:.3rem .9rem;border-radius:20px;font-weight:700;font-size:.8rem;background:${c.bg};color:${c.color};">
    <i class="fas ${c.icon}"></i> ${c.label}
  </span>`;
}

function _buildApprovalTimeline(cycleId) {
  const s = (window._approvalStatusMap || {})[cycleId];
  if (!s || !s.submitted) return '';

  const fmtDate = iso => {
    if (!iso) return '';
    try { return new Date(iso).toLocaleString('en-IN', { day:'2-digit', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' }); }
    catch { return iso; }
  };

  const steps = [
    { done: true,                      icon: 'fa-paper-plane',   color: '#6366f1', label: 'Submitted',       detail: fmtDate(s.submitted_at) },
    { done: s.status !== 'submitted',  icon: 'fa-hourglass-half',color: s.status === 'rejected' ? '#ef4444' : '#3b82f6', label: s.status === 'rejected' ? 'Rejected by Manager' : s.status === 'approved' ? 'Manager Review' : 'Waiting for Manager', detail: s.status === 'rejected' ? `${fmtDate(s.rejected_at)}${s.rejection_reason ? ' — ' + s.rejection_reason : ''}` : '' },
    { done: s.status === 'approved',   icon: 'fa-check-circle',  color: '#10b981', label: 'Approved',        detail: s.approved_by_name ? `by ${s.approved_by_name}` : '' },
  ];

  return `
    <div style="padding:1rem 1.5rem;background:#f8fafc;border-top:1px solid #e2e8f0;">
      <div style="font-weight:700;font-size:.85rem;color:#475569;margin-bottom:.9rem;"><i class="fas fa-route"></i> Approval Timeline</div>
      <div style="display:flex;align-items:flex-start;gap:0;position:relative;overflow-x:auto;padding-bottom:.5rem;">
        ${steps.map((step, i) => `
          <div style="display:flex;flex-direction:column;align-items:center;flex:1;min-width:120px;position:relative;">
            ${i < steps.length - 1 ? `<div style="position:absolute;top:16px;left:50%;width:100%;height:3px;background:${step.done ? '#10b981' : '#e2e8f0'};z-index:0;"></div>` : ''}
            <div style="width:34px;height:34px;border-radius:50%;background:${step.done ? step.color : '#e2e8f0'};color:${step.done ? '#fff' : '#94a3b8'};display:flex;align-items:center;justify-content:center;font-size:.9rem;position:relative;z-index:1;box-shadow:0 2px 6px rgba(0,0,0,.1);">
              <i class="fas ${step.icon}"></i>
            </div>
            <div style="margin-top:.5rem;text-align:center;font-size:.78rem;">
              <div style="font-weight:700;color:${step.done ? step.color : '#94a3b8'};">${step.label}</div>
              ${step.detail ? `<div style="color:#64748b;margin-top:.15rem;font-size:.72rem;max-width:130px;word-break:break-word;">${step.detail}</div>` : ''}
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function _renderHistoryPayrolls(payrolls) {
  const container = document.getElementById('historyPayrollsContainer');
  const paginationEl = document.getElementById('historyPagination');
  if (!container) return;
  container.innerHTML = '';

  if (!payrolls.length) {
    container.innerHTML = '<p style="padding:2rem;color:#888;">No entries for selected payroll.</p>';
    if (paginationEl) paginationEl.innerHTML = '';
    return;
  }

  const page = window._historyPage || 1;
  const total = payrolls.length;
  const totalPages = Math.ceil(total / HISTORY_PAGE_SIZE);
  const start = (page - 1) * HISTORY_PAGE_SIZE;
  const pageItems = payrolls.slice(start, start + HISTORY_PAGE_SIZE);

  pageItems.forEach((payroll, cardIdx) => {
    const showLunchTravel = payroll.show_lunch_travel !== false;
    const approvalBadge = _getApprovalStatusBadge(payroll.cycle_id);
    const approvalTimeline = _buildApprovalTimeline(payroll.cycle_id);
    const approvalHistoryLog = _buildApprovalHistoryLog((window._approvalHistoryMap || {})[payroll.cycle_id] || [], payroll.cycle_id);

    // Count unique working days
    const allDates = new Set();
    (payroll.entries || []).forEach(e => { if (e.date) allDates.add(e.date); });
    const workingDays = allDates.size;

    // Derive date range from entries
    const sortedDates = [...allDates].sort();
    const dateRangeStr = sortedDates.length
      ? `${sortedDates[0]} — ${sortedDates[sortedDates.length - 1]}`
      : '—';

    const submittedAt = payroll.submitted_at
      ? new Date(payroll.submitted_at).toLocaleDateString('en-IN', { day:'2-digit', month:'short', year:'numeric' })
      : null;

    const cardId = `historyCard_${start + cardIdx}`;
    const bodyId = `historyBody_${start + cardIdx}`;

    const card = document.createElement('div');
    card.className = 'history-payroll-card';
    card.style.cssText = 'margin-bottom:1.2rem;border:2px solid #e2e8f0;border-radius:16px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,.06);background:#fff;transition:box-shadow .2s;';

    card.innerHTML = `
      <!-- Card Summary Header -->
      <div class="history-card-header" onclick="toggleHistoryCard('${bodyId}','${cardId}')"
        style="padding:1.1rem 1.5rem;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:1rem;background:linear-gradient(135deg,#f0f4ff,#f5f0ff);flex-wrap:wrap;">
        <div style="display:flex;flex-direction:column;gap:.35rem;flex:1;min-width:200px;">
          <div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;">
            <span style="font-weight:800;font-size:1.05rem;color:#3730a3;"><i class="fas fa-calendar-alt"></i> ${payroll.cycle_label}</span>
            ${approvalBadge}
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:.8rem 1.5rem;font-size:.83rem;color:#475569;margin-top:.1rem;">
            <span><i class="fas fa-calendar-day" style="color:#6366f1;"></i> ${dateRangeStr}</span>
            ${submittedAt ? `<span><i class="fas fa-paper-plane" style="color:#10b981;"></i> Submitted ${submittedAt}</span>` : '<span style="color:#f59e0b;"><i class="fas fa-pencil-alt"></i> Draft</span>'}
            <span><i class="fas fa-briefcase" style="color:#f59e0b;"></i> ${workingDays} working day${workingDays !== 1 ? 's' : ''}</span>
            <span><i class="fas fa-clock" style="color:#3b82f6;"></i> ${(payroll.totalHours||0).toFixed(1)} hrs total</span>
            <span><i class="fas fa-dollar-sign" style="color:#10b981;"></i> ${(payroll.totalBillableHours||0).toFixed(1)} billable</span>
          </div>
        </div>
        <div id="${cardId}_icon" style="font-size:1.1rem;color:#6366f1;transition:transform .3s;flex-shrink:0;">
          <i class="fas fa-chevron-down"></i>
        </div>
      </div>

      <!-- Card Detail Body (collapsed by default) -->
      <div id="${bodyId}" style="display:none;">
        ${approvalTimeline}
        ${approvalHistoryLog}
        <div class="history-card-entries" style="padding:1rem 1.5rem 0;">
        </div>
        <div class="history-card-feedback"></div>
      </div>
    `;

    // Build the entries table inside the card body — flat, no week grouping
    const entriesContainer = card.querySelector('.history-card-entries');
    const tableWrapper = document.createElement('div');
    tableWrapper.className = 'table-responsive';
    const table = document.createElement('table');
    table.className = 'timesheet-table history-table';
    table.innerHTML = `
      <thead>
        <tr>
          <th class="col-narrow">S.No</th>
          <th class="col-narrow">Action</th>
          <th class="col-medium">Date</th>
          <th class="col-wide">Work</th>
          <th class="col-medium">Start</th>
          <th class="col-medium">End</th>
          <th class="col-wide">Client</th>
          <th class="col-wide">Project</th>
          <th class="col-medium">Project Code</th>
          <th class="col-wide">Reporting Manager</th>
          <th class="col-wide">Activity</th>
          <th class="col-narrow">Hours</th>
          <th class="col-medium">Billable</th>
          ${showLunchTravel ? '<th class="col-medium">Lunch Time</th>' : ''}
          ${showLunchTravel ? '<th class="col-medium">Travel Time</th>' : ''}
          <th class="col-wide">Remarks</th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector('tbody');
    (payroll.entries || []).forEach((entry, rowIndex) => {
      const isSubmitted = payroll.submitted;
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${rowIndex + 1}</td>
        <td style="min-width:120px;">
          ${isSubmitted
            ? '<span style="font-size:.78rem;color:#10b981;font-weight:600;"><i class="fas fa-lock"></i> Submitted</span>'
            : `<button class="action-btn edit-btn" onclick="editHistoryRow(this,'${entry.id}')"><i class="fas fa-edit"></i> Edit</button>
               <button class="action-btn delete-btn" onclick="deleteHistoryRow(this,'${entry.id}')"><i class="fas fa-trash"></i> Delete</button>`
          }
        </td>
        <td>${entry.date||''}</td>
        <td>${entry.location||''}</td>
        <td>${entry.projectStartTime||''}</td>
        <td>${entry.projectEndTime||''}</td>
        <td>${entry.client||''}</td>
        <td>${entry.project||''}</td>
        <td>${entry.projectCode||''}</td>
        <td>${entry.reportingManagerEntry||''}</td>
        <td>${entry.activity||''}</td>
        <td>${entry.projectHours||''}</td>
        <td>${entry.billable||''}</td>
        ${showLunchTravel ? `<td>${entry.lunchTime||''}</td>` : ''}
        ${showLunchTravel ? `<td>${entry.travelTime||''}</td>` : ''}
        <td>${entry.remarks||''}</td>
      `;
      tbody.appendChild(row);
    });
    tableWrapper.appendChild(table);
    entriesContainer.appendChild(tableWrapper);

    // Feedback section inside card
    const meta = payroll.metadata || {};
    if (meta.hits || meta.misses || meta.feedback_hr || meta.feedback_it || meta.feedback_crm || meta.feedback_others || meta.idle_time_status === 'Yes') {
      const feedbackDiv = card.querySelector('.history-card-feedback');
      feedbackDiv.style.cssText = 'padding:1rem 1.5rem 1.5rem;background:#fafbfc;border-top:1px solid #e1e8ed;';
      feedbackDiv.innerHTML = `
        <h4 style="margin-bottom:.75rem;color:#2c3e50;font-size:.88rem;font-weight:700;"><i class="fas fa-comment-alt"></i> Feedback & Idle Time</h4>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:.5rem;font-size:.83rem;">
          ${meta.hits ? `<div><strong>3 HITS:</strong> ${meta.hits}</div>` : ''}
          ${meta.misses ? `<div><strong>3 MISSES:</strong> ${meta.misses}</div>` : ''}
          ${meta.feedback_hr ? `<div><strong>HR:</strong> ${meta.feedback_hr}</div>` : ''}
          ${meta.feedback_it ? `<div><strong>IT:</strong> ${meta.feedback_it}</div>` : ''}
          ${meta.feedback_crm ? `<div><strong>CRM:</strong> ${meta.feedback_crm}</div>` : ''}
          ${meta.feedback_others ? `<div><strong>Others:</strong> ${meta.feedback_others}</div>` : ''}
          <div><strong>Idle Time?</strong> ${meta.idle_time_status || 'No'}</div>
          ${meta.idle_time_status === 'Yes' ? `<div><strong>Idle Time (Hrs):</strong> ${meta.idle_time_hours || '-'}</div><div><strong>Idle Reason:</strong> ${meta.idle_time_reason || '-'}</div>` : ''}
        </div>
      `;
    }

    container.appendChild(card);
  });

  // Render pagination
  if (paginationEl) {
    paginationEl.innerHTML = '';
    if (totalPages > 1) {
      for (let p = 1; p <= totalPages; p++) {
        const btn = document.createElement('button');
        btn.textContent = p;
        btn.style.cssText = `padding:.45rem .9rem;border-radius:8px;border:2px solid ${p === page ? '#5d5fef' : '#e2e8f0'};background:${p === page ? '#5d5fef' : '#fff'};color:${p === page ? '#fff' : '#475569'};font-weight:700;font-size:.88rem;cursor:pointer;`;
        btn.onclick = (pg => () => { window._historyPage = pg; _renderHistoryPayrolls(payrolls); })(p);
        paginationEl.appendChild(btn);
      }
    }
  }
}

function toggleHistoryCard(bodyId, cardId) {
  const body = document.getElementById(bodyId);
  const icon = document.getElementById(cardId + '_icon');
  if (!body) return;
  const isOpen = body.style.display !== 'none';
  body.style.display = isOpen ? 'none' : 'block';
  if (icon) icon.style.transform = isOpen ? '' : 'rotate(180deg)';
}

/* Edit / Delete history entry */
function editHistoryRow(button, entryId) {
  const modal = document.getElementById("modalOverlay");
  const row = button.closest("tr");
  if (!row) return;
  if (!modal) {
    showPopup("Edit modal not available in this HTML layout", true);
    return;
  }

  const cells = row.querySelectorAll("td");
  const modalInputs = modal.querySelectorAll("input, select, textarea");
  try {
    document.getElementById("modalInput1").value = cells[2].textContent.trim();  // Date
    document.getElementById("modalInput2").value = cells[3].textContent.trim();  // Location
    document.getElementById("modalInput3").value = cells[4].textContent.trim();  // Project Start
    document.getElementById("modalInput4").value = cells[5].textContent.trim();  // Project End
    // document.getElementById("modalInput5").value = cells[6].textContent.trim();  // Client
    // document.getElementById("modalInput6").value = cells[7].textContent.trim();  // Project
    // document.getElementById("modalInput7").value = cells[8].textContent.trim(); // Project Code

      const clientValue = cells[6].textContent.trim();
      const projectValue = cells[7].textContent.trim();
      const projectCodeValue = cells[8].textContent.trim();

      // 🔥 Create smart dropdowns like openModal()

      const clientContainer = document.getElementById("modalClientContainer");
      clientContainer.innerHTML = "";
      const clientDropdown = createSmartDropdown("client", clientContainer, clientValue);
      clientContainer.appendChild(clientDropdown);

      if (!window._freeTextClientProject) {
        clientDropdown.addEventListener("change", function () {
            const selectedClient = this.value;
            updateModalProjectDropdown(selectedClient, "");
        });
      }

      if (!window._freeTextClientProject && clientValue === "Other") {
        // Same "Other" treatment as openModal(): Project free text, Project
        // Code fixed and non-typable.
        _renderModalProjectOther(projectValue);
      } else {
        const projectContainer = document.getElementById("modalProjectContainer");
        projectContainer.innerHTML = "";
        const projectDropdown = createSmartDropdown(
            "project",
            projectContainer,
            projectValue,
            clientValue
        );
        projectContainer.appendChild(projectDropdown);

        if (!window._freeTextClientProject) {
          projectDropdown.addEventListener("change", function () {
              const currentClient = clientContainer?.querySelector("input")?.value;
              updateModalProjectCode(currentClient, this.value);
          });
        }

        const projectCodeContainer = document.getElementById("modalProjectCodeContainer");
        projectCodeContainer.innerHTML = "";
        if (window._freeTextClientProject) {
          projectCodeContainer.appendChild(createSharedServicesProjectCode(projectCodeValue, "modalProjectCodeInput"));
        } else {
          const codeInput = document.createElement("input");
          codeInput.type = "text";
          codeInput.id = "modalProjectCodeInput";
          codeInput.className = "form-input";
          codeInput.value = projectCodeValue;
          codeInput.readOnly = true;
          codeInput.style.backgroundColor = "#f0f0f0";
          projectCodeContainer.appendChild(codeInput);
        }
        showProjectPlanStatus(projectCodeValue, { modal: true });
      }

    document.getElementById("modalInput8").value = cells[9].textContent.trim(); // Reporting Manager
    document.getElementById("modalInput9").value = cells[10].textContent.trim(); // Activity
    document.getElementById("modalInput10").value = cells[11].textContent.trim(); // Project Hours
    document.getElementById("modalInput11").value = cells[12].textContent.trim(); // Billable
    document.getElementById("modalInput12").value = cells[13].textContent.trim(); // Remarks
  } catch (err) {
    console.warn("Mapping modal inputs failed", err);
  }

  isEditingHistory = true;
  currentEntryId = entryId;
  currentRow = row;
  modal.style.display = "flex";

  const addBtn = document.getElementById("modalAddBtn");
  if (addBtn) {
    addBtn.textContent = "Update";
    addBtn.onclick = updateHistoryEntry;
  }
}

function updateHistoryEntry() {
  if (!currentEntryId || !currentRow) {
    showPopup("No entry selected", true);
    return;
  }
  const modal = document.getElementById("modalOverlay");
  if (!modal) {
    showPopup("Modal not present", true);
    return;
  }
  const clientContainer = document.getElementById("modalClientContainer");
  const clientValue = clientContainer?.querySelector("input")?.value || "";

  const projectContainer = document.getElementById("modalProjectContainer");
  const projectValue = projectContainer?.querySelector("input")?.value || "";

  const projectCodeValue =
    document.getElementById("modalProjectCodeInput")?.value || "";

  const inputs = modal.querySelectorAll("input, select, textarea");
  const updatePayload = {
    date: document.getElementById("modalInput1").value,
    location: document.getElementById("modalInput2").value,
    projectStartTime: document.getElementById("modalInput3").value,
    projectEndTime: document.getElementById("modalInput4").value,
    // client: document.getElementById("modalInput5").value,
    // project: document.getElementById("modalInput6").value,
    // projectCode: document.getElementById("modalInput7").value,
    client: clientValue,
    project: projectValue,
    projectCode: projectCodeValue,
    
    reportingManagerEntry: document.getElementById("modalInput8").value,
    activity: document.getElementById("modalInput9").value,
    projectHours: document.getElementById("modalInput10").value,
    billable: document.getElementById("modalInput11").value,
    remarks: document.getElementById("modalInput12").value,
  };

  showLoading("Updating entry...");
  fetch(`${API_URL}/update_timesheet/${loggedInEmployeeId}/${currentEntryId}`, {
    method: "PUT",
    headers: getHeaders(),
    body: JSON.stringify(updatePayload),
  })
    .then((r) => r.json())
    .then((res) => {
      hideLoading();
      if (res && res.success) {
        showPopup("Entry updated");
        closeModal();
        loadHistory();
      } else {
        showPopup("Failed to update entry", true);
      }
    })
    .catch((err) => {
      hideLoading();
      console.error("updateHistoryEntry error", err);
      showPopup("Error updating entry", true);
    });
}

function deleteHistoryRow(button, entryId) {
  if (!confirm("Delete this entry?")) return;
  showLoading("Deleting entry...");
  fetch(`${API_URL}/delete_timesheet/${loggedInEmployeeId}/${entryId}`, {
    method: "DELETE",
    headers: getHeaders(),
  })
    .then((r) => r.json())
    .then((res) => {
      hideLoading();
      if (res && res.success) {
        showPopup("Entry deleted");
        loadHistory();
      } else {
        showPopup("Failed to delete", true);
      }
    })
    .catch((err) => {
      hideLoading();
      console.error("deleteHistoryRow error:", err);
      showPopup("Error deleting entry", true);
    });
}


// ── Collect entries from one week section ─────────────────────────────────────
function _collectEntries() {
  const section = document.getElementById(TIMESHEET_SECTION_ID);
  if (!section) return [];
  const rows = section.querySelectorAll('tbody tr');
  const entries = [];
  rows.forEach(row => {
    const date            = row.querySelector('.date-field')?.value || '';
    const location        = row.querySelector('.location-select')?.value || '';
    const projectStart    = row.querySelector('.project-start')?.value || '';
    const projectEnd      = row.querySelector('.project-end')?.value || '';
    const client          = getFieldValue(row, '.col-client') || '';
    const project         = getFieldValue(row, '.col-project') || '';
    const projectCode     = getFieldValue(row, '.col-project-code') || '';
    const reportingMgr    = row.querySelector('.reporting-manager-field')?.value || '';
    const activity        = row.querySelector('.activity-field')?.value || '';
    const projectHours    = row.querySelector('.project-hours-field')?.value || '0';
    let billable          = row.querySelector('.billable-select')?.value || 'No';
    const remarks         = row.querySelector('.remarks-field')?.value || '';
    let lunchTime         = row.querySelector('.lunch-time-select')?.value || '';
    let travelTime        = row.querySelector('.travel-time-select')?.value || '';
    if (isDayOffLocation(location)) lunchTime = '';
    if (NO_TRAVEL_TIME_LOCATIONS.includes(location.trim())) travelTime = '';
    if (isDayOffLocation(location)) billable = 'No';
    if (!date) return;
    entries.push({
      date, location,
      projectStartTime: projectStart,
      projectEndTime:   projectEnd,
      client, project, projectCode,
      reportingManagerEntry: reportingMgr,
      activity, projectHours, billable, remarks,
      lunchTime, travelTime,
    });
  });
  return entries;
}

function _collectMetadata() {
  return {
    employeeName:     document.getElementById('employeeName')?.value || '',
    designation:      document.getElementById('designation')?.value || '',
    gender:           document.getElementById('gender')?.value || '',
    partner:          document.getElementById('partner')?.value || '',
    reportingManager: document.getElementById('reportingManager')?.value || '',
    hits:             document.getElementById('hits')?.value || '',
    misses:           document.getElementById('misses')?.value || '',
    feedback_hr:      document.getElementById('feedback_hr')?.value || '',
    feedback_it:      document.getElementById('feedback_it')?.value || '',
    feedback_crm:     document.getElementById('feedback_crm')?.value || '',
    feedback_others:  document.getElementById('feedback_others')?.value || '',
    idle_time_status: document.getElementById('idle_time_status')?.value || 'No',
    idle_time_hours:  document.getElementById('idle_time_hours')?.value || '',
    idle_time_reason: document.getElementById('idle_time_reason')?.value || '',
  };
}

// ── Save the whole cycle's entries as draft ──────────────────────────────────
async function saveDraft() {
  if (!_selectedCycle) {
    showPopup('Please select a payroll cycle first.', true);
    return;
  }
  if (_selectedCycle.locked) {
    showPopup('Submission deadline has passed for this cycle.', true);
    return;
  }

  const section = document.getElementById(TIMESHEET_SECTION_ID);
  if (!section) { showPopup('Timesheet table not found.', true); return; }

  const entries = _collectEntries();
  if (!entries.length) { showPopup('No entries to save.', true); return; }

  // Save whatever the user has filled in so far — mandatory-field and lunch
  // time completeness are only enforced at submit time, not on every draft
  // save, so partially-filled rows never block saving progress.

  showLoading('Saving draft...');
  try {
    const res = await fetch(`${API_URL}/timesheet/save-draft`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({
        cycle_id:    _selectedCycle.id,
        cycle_label: _selectedCycle.cycle_label,
        entries:     entries,
        metadata:    _collectMetadata(),
      }),
    });
    const data = await res.json();
    hideLoading();
    if (res.ok && data.success) {
      showPopup('✅ Draft saved!');
      // Highlight all rows green to show they are saved
      const tbody = section.querySelector('tbody');
      if (tbody) {
        tbody.querySelectorAll('tr').forEach(row => {
          row.style.background = 'linear-gradient(90deg,#f0fdf4,#dcfce7)';
          row.dataset.saved = '1';
        });
      }
      // Brief button feedback
      const btn = section.querySelector('.save-week-btn');
      if (btn) {
        const orig = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-check"></i> Saved!';
        setTimeout(() => { btn.innerHTML = orig; }, 2000);
      }
    } else {
      showPopup(data.detail || data.message || 'Failed to save draft.', true);
    }
  } catch(err) {
    hideLoading();
    console.error('saveDraft error:', err);
    showPopup('Network error saving draft.', true);
  }
}

// Every calendar date applicable to the employee in the selected payroll
// cycle must have at least one row before submit is allowed (a Leave/Week
// Off/PHY row still counts — this only checks a row exists for the date, not
// that its other fields are filled in). Returns missing YYYY-MM-DD dates.
function _findMissingCycleDates() {
  const applicableWindow = _applicableCycleDateKeys();
  if (!applicableWindow || applicableWindow.start > applicableWindow.end) return [];

  const presentDates = new Set(_collectEntries().map(e => e.date).filter(Boolean));

  const missing = [];
  const start = new Date(`${applicableWindow.start}T00:00:00Z`);
  const end   = new Date(`${applicableWindow.end}T00:00:00Z`);
  const d = new Date(start);
  while (d <= end) {
    const dateStr = d.toISOString().split('T')[0];
    if (!presentDates.has(dateStr)) missing.push(dateStr);
    d.setDate(d.getDate() + 1);
  }
  return missing;
}

// ── Submit confirmation popup ─────────────────────────────────────────────────
function confirmSubmit() {
  if (!_selectedCycle) {
    showPopup('Please select a payroll cycle first.', true);
    return;
  }
  if (_selectedCycle.locked) {
    showPopup('Submission deadline has passed for this cycle.', true);
    return;
  }

  // Every date applicable to this employee must have an entry row.
  const missingDates = _findMissingCycleDates();
  if (missingDates.length) {
    const shown = missingDates.slice(0, 10).map(d => new Date(d).toLocaleDateString('en-GB')).join(', ');
    const extra = missingDates.length > 10 ? ` and ${missingDates.length - 10} more` : '';
    showPopup(`Cannot submit — missing entries for: ${shown}${extra}. Please add a row for every day before submitting.`, true);
    return;
  }

  // Validate Idle Time: if Yes, both hours and reason are required
  const idleStatus = document.getElementById('idle_time_status')?.value || 'No';
  if (idleStatus === 'Yes') {
    const idleHours = document.getElementById('idle_time_hours')?.value || '';
    const idleReason = document.getElementById('idle_time_reason')?.value || '';
    if (!idleHours.trim() || !idleReason.trim()) {
      showPopup("Since Idle Time is set to 'Yes', both 'Idle Time (Hours / Min)' and 'Reason' fields are required.", true);
      return;
    }
  }

  const popup = document.getElementById('submitConfirmPopup');
  if (popup) popup.style.display = 'flex';
}

// ── Final submit ──────────────────────────────────────────────────────────────
async function doSubmitTimesheet() {
  const popup = document.getElementById('submitConfirmPopup');
  if (popup) popup.style.display = 'none';

  if (!_selectedCycle) { showPopup('No cycle selected.', true); return; }

  showLoading('Submitting timesheet...');
  try {
    const res = await fetch(`${API_URL}/timesheet/submit`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({
        cycle_id:    _selectedCycle.id,
        cycle_label: _selectedCycle.cycle_label,
        metadata:    _collectMetadata(),
      }),
    });
    const data = await res.json();
    hideLoading();
    if (res.ok && data.success) {
      showPopup('🎉 Timesheet submitted successfully! You can view it in History.');
      // Refresh cycle dropdown to show submitted status
      await loadAvailableCycles();
      setTimeout(() => clearTimesheet(true), 2000);
    } else {
      showPopup(data.detail || data.message || 'Submission failed.', true);
    }
  } catch(err) {
    hideLoading();
    console.error('doSubmitTimesheet error:', err);
    showPopup('Network error during submission.', true);
  }
}


async function saveDataToMongo() {
  console.log("Starting saveDataToMongo");
  showLoading("Saving data...");

  const employeeId = document.getElementById("employeeId").value.trim();
  if (!employeeId) {
    hideLoading();
    showPopup('Please enter Employee ID', true);
    return;
  }

  const timesheetData = [];
  const sections = document.querySelectorAll('.timesheet-section');
  let hasError = false;
  let errorMessages = [];

  sections.forEach((section, secIndex) => {
    const weekSelect = section.querySelector('.week-period select');
    const weekPeriod = weekSelect?.value || '';
    if (!weekPeriod) {
      console.log("No week period")
      hasError = true;
      errorMessages.push(`Week ${secIndex + 1}: Please select a week period.`);
    }

    const rows = section.querySelectorAll('tbody tr');
    rows.forEach((row, rowIndex) => {
      const date = row.querySelector('.date-field')?.value;
      const location = row.querySelector('.location-select')?.value;
      const projectStart = row.querySelector('.project-start')?.value;
      const projectEnd = row.querySelector('.project-end')?.value;
      
      // ✅ Use helper function for smart dropdown fields
      const client = getFieldValue(row, '.col-client');
      const project = getFieldValue(row, '.col-project');
      const projectCode = getFieldValue(row, '.col-project-code');
      
      const reportingManager = row.querySelector('.reporting-manager-field')?.value;
      const activity = row.querySelector('.activity-field')?.value;
      const projectHours = row.querySelector('.project-hours-field')?.value;
      const billable = row.querySelector('.billable-select')?.value;
      const remarks = row.querySelector('.remarks-field')?.value;
      const lunchTime = row.querySelector('.lunch-time-select')?.value || '';
      const travelTime = row.querySelector('.travel-time-select')?.value || '';

      // Mandatory field check
      const mandatory = {
        date, projectStart, projectEnd,
        client, project, projectCode, reportingManager, activity
      };

      for (const [field, value] of Object.entries(mandatory)) {
        if (!value || value.trim() === '') {
          console.log(`${field}: ${value}`)
          console.log("mandatory check failed")
          hasError = true;
          errorMessages.push(`Row ${rowIndex + 1} (Week ${secIndex + 1}): ${field} is required.`);
        }
      }

      // Lunch Time is mandatory when visible for this cycle
      if (window._showLunchTravel !== false && (!lunchTime || lunchTime.trim() === '')) {
        hasError = true;
        errorMessages.push(`Row ${rowIndex + 1} (Week ${secIndex + 1}): Lunch Time is required.`);
      }

      // Only push if date is filled
      if (!date) return;

      const entry = {
        employeeId,
        employeeName: document.getElementById('employeeName')?.value || '',
        designation: document.getElementById('designation')?.value || '',
        gender: document.getElementById('gender')?.value || '',
        partner: document.getElementById('partner')?.value || '',
        reportingManager: document.getElementById('reportingManager')?.value || '',
        department: document.getElementById('department')?.value || '',
        weekPeriod,
        date,
        location,
        projectStartTime: projectStart,
        projectEndTime: projectEnd,
        client,
        project,
        projectCode,
        reportingManagerEntry: reportingManager,
        activity,
        projectHours: projectHours || "0",
        billable,
        remarks,
        lunchTime,
        travelTime,
        hits: document.getElementById('hits')?.value || '',
        misses: document.getElementById('misses')?.value || '',
        feedback_hr: document.getElementById('feedback_hr')?.value || '',
        feedback_it: document.getElementById('feedback_it')?.value || '',
        feedback_crm: document.getElementById('feedback_crm')?.value || '',
        feedback_others: document.getElementById('feedback_others')?.value || ''
      };

      timesheetData.push(entry);
    });
  });

  console.log("Final timesheetData to send:", timesheetData);

  if (hasError) {
    console.log('In has error')
    hideLoading();
    showPopup(errorMessages.join('\n'), true);
    return;
  }

  if (timesheetData.length === 0) {
    console.log("Timesheet data length is 0")
    hideLoading();
    showPopup("No valid entries to save.", true);
    return;
  }

  try {
    console.log("Sending to:", `${API_URL}/save_timesheets`);
    console.log("Payload:", timesheetData);

    const token = localStorage.getItem("access_token");
    const response = await fetch(`${API_URL}/save_timesheets`, {
      method: 'POST',
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify(timesheetData)
    });

    const result = await response.json();
    hideLoading();

    if (response.ok && result.success) {
      showPopup('Timesheet submitted successfully. You can review it in the History section.');
      // setTimeout(() => location.reload(), 1500);
      setTimeout(() => {
        clearTimesheet(true);
      }, 1500);
    } else {
      showPopup('Save failed: ' + (result.message || 'Unknown error'), true);
    }
  } catch (err) {
    hideLoading();
    console.error("Save error:", err);
    showPopup('Network error. Check console.', true);
  }
}

// ==========================================
// UPDATED copyRow FUNCTION
// ==========================================
function copyRow(button) {
  const row = button.closest("tr");
  if (!row) return;
  
  copiedData = {
    date: row.querySelector('.date-field')?.value || '',
    location: row.querySelector('.location-select')?.value || '',
    projectStart: row.querySelector('.project-start')?.value || '',
    projectEnd: row.querySelector('.project-end')?.value || '',
    client: getFieldValue(row, '.col-client'),  // ✅ Smart dropdown
    project: getFieldValue(row, '.col-project'), // ✅ Smart dropdown
    projectCode: getFieldValue(row, '.col-project-code'), // ✅ Smart dropdown
    reportingManager: row.querySelector('.reporting-manager-field')?.value || '',
    activity: row.querySelector('.activity-field')?.value || '',
    billable: row.querySelector('.billable-select')?.value || '',
    remarks: row.querySelector('.remarks-field')?.value || ''
  };
  
  showPopup("Row copied!");
}

// ==========================================
// UPDATED pasteRow FUNCTION
// ==========================================
function pasteRow(button) {
  if (!copiedData) {
    showPopup("No copied row found", true);
    return;
  }
  
  const row = button.closest("tr");
  if (!row) return;
  
  // Paste regular fields
  const dateField = row.querySelector('.date-field');
  if (dateField) dateField.value = copiedData.date;
  
  const locationField = row.querySelector('.location-select');
  if (locationField) locationField.value = copiedData.location;
  
  const projectStartField = row.querySelector('.project-start');
  if (projectStartField) projectStartField.value = copiedData.projectStart;
  
  const projectEndField = row.querySelector('.project-end');
  if (projectEndField) projectEndField.value = copiedData.projectEnd;
  
  // ✅ Paste smart dropdown fields
  setFieldValue(row, '.col-client', copiedData.client);
  setFieldValue(row, '.col-project', copiedData.project);
  setFieldValue(row, '.col-project-code', copiedData.projectCode);
  
  const reportingManagerField = row.querySelector('.reporting-manager-field');
  if (reportingManagerField) reportingManagerField.value = copiedData.reportingManager;
  
  const activityField = row.querySelector('.activity-field');
  if (activityField) activityField.value = copiedData.activity;
  
  const billableField = row.querySelector('.billable-select');
  if (billableField) billableField.value = copiedData.billable;
  
  const remarksField = row.querySelector('.remarks-field');
  if (remarksField) remarksField.value = copiedData.remarks;
  
  calculateHours(row);
  updateSummary();
  showPopup("Row pasted!");
}



// function exportTimesheetToExcel() {
//   try {
//     // ✅ 1️⃣ Employee Details
//     const empDetails = {
//       "Employee ID": document.getElementById("employeeId")?.value || "",
//       "Employee Name": document.getElementById("employeeName")?.value || "",
//       "Designation": document.getElementById("designation")?.value || "",
//       "Gender": document.getElementById("gender")?.value || "",
//       "Partner": document.getElementById("partner")?.value || "",
//       "Reporting Manager": document.getElementById("reportingManager")?.value || "",
//     };

//     // ✅ 2️⃣ Timesheet Table Data
//     const tableRows = [];
//     document.querySelectorAll(".timesheet-section tbody tr").forEach((tr, idx) => {
//       tableRows.push({
//         "S.No": idx + 1,
//         Date: tr.querySelector(".date-field")?.value || "",
//         Location: tr.querySelector(".location-select")?.value || "",
//         "Project Start": tr.querySelector(".project-start")?.value || "",
//         "Project End": tr.querySelector(".project-end")?.value || "",
//         Client: tr.querySelector(".client-field")?.value || "",
//         Project: tr.querySelector(".project-field")?.value || "",
//         "Project Code": tr.querySelector(".project-code")?.value || "",
//         "Reporting Manager (Entry)": tr.querySelector(".reporting-manager-field")?.value || "",
//         Activity: tr.querySelector(".activity-field")?.value || "",
//         "Project Hours": tr.querySelector(".project-hours-field")?.value || "",
//         Billable: tr.querySelector(".billable-select")?.value || "",
//         Remarks: tr.querySelector(".remarks-field")?.value || "",
//       });
//     });

//     // ✅ 3️⃣ Feedback Section
//     const feedbackDetails = {
//       "3 HITS": document.getElementById("hits")?.value || "",
//       "3 MISSES": document.getElementById("misses")?.value || "",
//       "Feedback HR": document.getElementById("feedback_hr")?.value || "",
//       "Feedback IT": document.getElementById("feedback_it")?.value || "",
//       "Feedback CRM": document.getElementById("feedback_crm")?.value || "",
//       "Feedback Others": document.getElementById("feedback_others")?.value || "",
//     };

//     // ✅ 4️⃣ Combine all data row-wise
//     const wsData = [];

//     // Title Row
//     wsData.push(["JHS Timesheet Report"]);
//     wsData.push([]);

//     // Employee Details (Row-wise)
//     wsData.push(["Employee Details"]);
//     wsData.push([
//       "Employee ID",
//       "Employee Name",
//       "Designation",
//       "Gender",
//       "Partner",
//       "Reporting Manager",
//     ]);
//     wsData.push([
//       empDetails["Employee ID"],
//       empDetails["Employee Name"],
//       empDetails["Designation"],
//       empDetails["Gender"],
//       empDetails["Partner"],
//       empDetails["Reporting Manager"],
//     ]);

//     wsData.push([]);

//     // Timesheet Data (Row-wise)
//     wsData.push(["Timesheet Data"]);
//     const headers = Object.keys(tableRows[0] || {});
//     wsData.push(headers);
//     tableRows.forEach((row) => {
//       wsData.push(headers.map((h) => row[h]));
//     });

//     wsData.push([]);

//     // Feedback (Row-wise)
//     wsData.push(["Employee Feedback"]);
//     wsData.push([
//       "3 HITS",
//       "3 MISSES",
//       "Feedback HR",
//       "Feedback IT",
//       "Feedback CRM",
//       "Feedback Others",
//     ]);
//     wsData.push([
//       feedbackDetails["3 HITS"],
//       feedbackDetails["3 MISSES"],
//       feedbackDetails["Feedback HR"],
//       feedbackDetails["Feedback IT"],
//       feedbackDetails["Feedback CRM"],
//       feedbackDetails["Feedback Others"],
//     ]);

//     // ✅ 5️⃣ Convert to worksheet
//     const ws = XLSX.utils.aoa_to_sheet(wsData);

//     // ✅ 6️⃣ Merge title row
//     const mergeCols = Math.max(...wsData.map((r) => r.length));
//     ws["!merges"] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: mergeCols - 1 } }];

//     // ✅ 7️⃣ Basic Styling (borders, bold headings, colors)
//     const range = XLSX.utils.decode_range(ws["!ref"]);
//     for (let R = range.s.r; R <= range.e.r; ++R) {
//       for (let C = range.s.c; C <= range.e.c; ++C) {
//         const cellRef = XLSX.utils.encode_cell({ r: R, c: C });
//         if (!ws[cellRef]) continue;
//         const val = ws[cellRef].v;

//         // Borders
//         ws[cellRef].s = {
//           border: {
//             top: { style: "thin", color: { rgb: "999999" } },
//             bottom: { style: "thin", color: { rgb: "999999" } },
//             left: { style: "thin", color: { rgb: "999999" } },
//             right: { style: "thin", color: { rgb: "999999" } },
//           },
//         };

//         // Title
//         if (val === "JHS Timesheet Report") {
//           ws[cellRef].s = {
//             font: { bold: true, sz: 16, color: { rgb: "FFFFFF" } },
//             alignment: { horizontal: "center" },
//             fill: { fgColor: { rgb: "4472C4" } },
//           };
//         }

//         // Section Headings
//         if (
//           val === "Employee Details" ||
//           val === "Timesheet Data" ||
//           val === "Employee Feedback"
//         ) {
//           ws[cellRef].s = {
//             font: { bold: true, sz: 14, color: { rgb: "1F4E78" } },
//             fill: { fgColor: { rgb: "DDEBF7" } },
//           };
//         }

//         // Header Rows
//         if (
//           wsData[R - 1] &&
//           (wsData[R - 1][0] === "Employee Details" ||
//             wsData[R - 1][0] === "Timesheet Data" ||
//             wsData[R - 1][0] === "Employee Feedback")
//         ) {
//           ws[cellRef].s = {
//             font: { bold: true },
//             fill: { fgColor: { rgb: "E2EFDA" } },
//           };
//         }
//       }
//     }

//     // ✅ 8️⃣ Auto column width
//     const colWidths = [];
//     const dataRows = wsData.filter(Boolean);
//     for (let i = 0; i < (dataRows[0]?.length || 0); i++) {
//       const maxLen = dataRows.reduce(
//         (max, row) => Math.max(max, (row[i] ? String(row[i]).length : 0)),
//         10
//       );
//       colWidths.push({ wch: maxLen + 3 });
//     }
//     ws["!cols"] = colWidths;

//     // ✅ 9️⃣ Save file
//     const wb = XLSX.utils.book_new();
//     XLSX.utils.book_append_sheet(wb, ws, "Timesheet Report");

//     const fileName = `Timesheet_${empDetails["Employee ID"] || "user"}_${new Date()
//       .toISOString()
//       .split("T")[0]}.xlsx`;

//     XLSX.writeFile(wb, fileName);

//     showPopup("✅ Timesheet exported successfully (Row-wise layout)!");
//   } catch (err) {
//     console.error("exportTimesheetToExcel error", err);
//     showPopup("❌ Failed to export Excel", true);
//   }
// }

function getEmployeeInfoForExport() {
    return {
        'Employee ID': document.getElementById('employeeId').value || '',
        'Employee Name': document.getElementById('employeeName').value || '',
        'Designation': document.getElementById('designation').value || '',
        'Gender': document.getElementById('gender').value || '',
        'Partner': document.getElementById('partner').value || '',
        'Reporting Manager': document.getElementById('reportingManager').value || '',
        'S.No': '',
        'Date': '',
        'Work': '',
        'Project Start Time': '',
        'Project End Time': '',
        'Client': '',
        'Project': '',
        'Project Code': '',
        'Reporting Manager Entry': '',
        'Activity': '',
        'Project Hours': '',
        'Billable': '',
        'Remarks': '',
        '3 HITS': '',
        '3 MISSES': '',
        'FEEDBACK FOR HR': '',
        'FEEDBACK FOR IT': '',
        'FEEDBACK FOR CRM': '',
        'FEEDBACK FOR OTHERS': ''
    };
}

function exportTimesheetToExcel() {
    const employeeInfo = getEmployeeInfoForExport();
    const wb = XLSX.utils.book_new();

    const columns = [
        "employeeId","employeeName","designation","gender","partner","reportingManager",
        "date","location","projectStartTime","projectEndTime",
        "client","project","projectCode","reportingManagerEntry","activity",
        "projectHours","billable","lunchTime","travelTime","remarks",
        "hits","misses","feedback_hr","feedback_it","feedback_crm","feedback_others"
    ];

    const headersPretty = [
        "Employee ID","Employee Name","Designation","Gender","Partner","Reporting Manager",
        "Date","Work","Project Start Time","Project End Time",
        "Client","Project","Project Code","Reporting Manager Entry","Activity",
        "Project Hours","Billable","Lunch Time","Travel Time","Remarks",
        "3 HITS","3 MISSES","Feedback for HR","Feedback for IT","Feedback for CRM","Feedback for Others"
    ];

    let cleanedRows = [];
    const rows = document.querySelectorAll(".timesheet-section tbody tr");

    rows.forEach((row) => {
        const date            = row.querySelector('.date-field')?.value?.trim() || "";
        const location        = row.querySelector('.location-select')?.value || "";
        const projectStart    = row.querySelector('.project-start')?.value || "";
        const projectEnd      = row.querySelector('.project-end')?.value || "";
        const client          = getFieldValue(row, '.col-client') || "";
        const project          = getFieldValue(row, '.col-project') || "";
        const projectCode     = getFieldValue(row, '.col-project-code') || "";
        const reportingMgr    = row.querySelector('.reporting-manager-field')?.value || "";
        const activity        = row.querySelector('.activity-field')?.value || "";
        const projectHours    = row.querySelector('.project-hours-field')?.value || "";
        const billable        = row.querySelector('.billable-select')?.value || "";
        const lunchTime       = row.querySelector('.lunch-time-select')?.value || "";
        const travelTime      = row.querySelector('.travel-time-select')?.value || "";
        const remarks         = row.querySelector('.remarks-field')?.value || "";

        if (!date && !project && !client) return;

        cleanedRows.push({
            employeeId: employeeInfo["Employee ID"],
            employeeName: employeeInfo["Employee Name"],
            designation: employeeInfo["Designation"],
            gender: employeeInfo["Gender"],
            partner: employeeInfo["Partner"],
            reportingManager: employeeInfo["Reporting Manager"],
            date, location,
            projectStartTime: projectStart,
            projectEndTime: projectEnd,
            client, project, projectCode,
            reportingManagerEntry: reportingMgr,
            activity, projectHours, billable, lunchTime, travelTime, remarks,
            hits: document.getElementById("hits")?.value || "",
            misses: document.getElementById("misses")?.value || "",
            feedback_hr: document.getElementById("feedback_hr")?.value || "",
            feedback_it: document.getElementById("feedback_it")?.value || "",
            feedback_crm: document.getElementById("feedback_crm")?.value || "",
            feedback_others: document.getElementById("feedback_others")?.value || ""
        });
    });

    if (cleanedRows.length === 0) { showPopup("No valid data to export!", true); return; }

    const ws = XLSX.utils.json_to_sheet(cleanedRows, { header: columns });
    XLSX.utils.sheet_add_aoa(ws, [headersPretty], { origin: "A1" });
    const fileName = `Timesheet_${employeeInfo["Employee ID"]}_${new Date().toISOString().split("T")[0]}.xlsx`;
    XLSX.utils.book_append_sheet(wb, ws, "Timesheet");
    XLSX.writeFile(wb, fileName);
    showPopup("Timesheet exported successfully!");
}


function exportHistoryToExcel() {
    if (!historyEntries || historyEntries.length === 0) {
        showPopup("No history available!");
        return;
    }

    const columns = [
        "employeeId","employeeName","designation","gender","partner","reportingManager",
        "date","location","projectStartTime","projectEndTime",
        "client","project","projectCode","reportingManagerEntry","activity",
        "projectHours","billable","lunchTime","travelTime","remarks",
        "hits","misses","feedback_hr","feedback_it","feedback_crm","feedback_others",
        "totalHours","totalBillableHours","totalNonBillableHours"
    ];

    const headersPretty = [
        "Employee ID","Employee Name","Designation","Gender","Partner","Reporting Manager",
        "Date","Work","Project Start Time","Project End Time",
        "Client","Project","Project Code","Reporting Manager Entry","Activity",
        "Project Hours","Billable","Lunch Time","Travel Time","Remarks",
        "3 HITS","3 MISSES","Feedback for HR","Feedback for IT","Feedback for CRM","Feedback for Others",
        "Total Hours","Total Billable Hours","Total Non Billable Hours"
    ];

    const cleanedRows = historyEntries.map((row) => ({
        employeeId: row.employeeId || "",
        employeeName: row.employeeName || "",
        designation: row.designation || "",
        gender: row.gender || "",
        partner: row.partner || "",
        reportingManager: row.reportingManager || "",
        date: row.date || "",
        location: row.location || "",
        projectStartTime: row.projectStartTime || "",
        projectEndTime: row.projectEndTime || "",
        client: row.client || "",
        project: row.project || "",
        projectCode: row.projectCode || "",
        reportingManagerEntry: row.reportingManagerEntry || "",
        activity: row.activity || "",
        projectHours: row.projectHours || "",
        billable: row.billable || "",
        lunchTime: row.lunchTime || "",
        travelTime: row.travelTime || "",
        remarks: row.remarks || "",
        hits: row.hits || "",
        misses: row.misses || "",
        feedback_hr: row.feedback_hr || "",
        feedback_it: row.feedback_it || "",
        feedback_crm: row.feedback_crm || "",
        feedback_others: row.feedback_others || "",
        totalHours: row.totalHours || "",
        totalBillableHours: row.totalBillableHours || "",
        totalNonBillableHours: row.totalNonBillableHours || ""
    }));

    const worksheet = XLSX.utils.json_to_sheet(cleanedRows, { header: columns });
    XLSX.utils.sheet_add_aoa(worksheet, [headersPretty], { origin: "A1" });
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "History");
    const fileName = `History_${loggedInEmployeeId}_${new Date().toISOString().split("T")[0]}.xlsx`;
    XLSX.writeFile(workbook, fileName);
    showPopup("History exported successfully!");
}


// ✅ Updated checkUserRole function (final version)
async function checkUserRole() {
  try {
    if (!loggedInEmployeeId) {
      document.querySelectorAll(".manager-only").forEach(btn => btn.style.display = "none");
      return;
    }

    // Check if current user is a reporting manager
    const resMgr = await fetch(`${API_URL}/check_reporting_manager/${loggedInEmployeeId}`, {
      headers: getHeaders(),
    });

    let isManager = false;
    if (resMgr.ok) {
      const js = await resMgr.json();
      isManager = !!js.isManager;
    }

    // Show manager buttons if user is a TL — no PAR check needed
    document.querySelectorAll(".manager-only").forEach(btn => {
      btn.style.display = isManager ? "inline-block" : "none";
    });

  } catch (err) {
    console.error("Error checking role:", err);
    document.querySelectorAll(".manager-only").forEach(btn => btn.style.display = "none");
  }
}





async function loadApprovedList() {
  try {
    const res = await fetch(
      `${API_URL}/get_approved_employees/${loggedInEmployeeId}`,
      { headers: getHeaders() }
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();

    const data = Array.isArray(result.employees) ? result.employees : result.data || result.Data || [];

    const tbody = document.getElementById("approveTableBody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!data.length) {
      tbody.innerHTML = `<tr><td colspan="4">No approved employees</td></tr>`;
      return;
    }

    data.forEach((item) => {
      const emp = item.timesheetData || {};
      const empName = emp.employeeName || "N/A";
      const empId = item.employeeId || emp.employeeId || "N/A";
      const cycleId = item.cycle_id || "";
      const cycleLabel = emp.cycle_label || "-";

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${empId}</td>
        <td><a href="#" class="employee-link" onclick="openEmployeeDetails('${empId}','${cycleId}')">
        ${empName}
      </a></td>
        <td><span style="background:#d1fae5;color:#065f46;padding:.2rem .6rem;border-radius:6px;font-size:.82rem;font-weight:700;">${cycleLabel}</span></td>
        <td>
          <button class="action-btn reject-btn" onclick="rejectEmployee('${empId}')">
            <i class="fas fa-times"></i> Reject
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("loadApprovedList error", err);
  }
}

async function loadPendingList() {
  try {
    const res = await fetch(
      `${API_URL}/get_pending_employees/${loggedInEmployeeId}`,
      { headers: getHeaders() }
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();

    const data = Array.isArray(result.employees) ? result.employees : result.data || result.Data || [];

    const tbody = document.getElementById("pendingTableBody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!data.length) {
      tbody.innerHTML = `<tr><td colspan="3">No pending approvals</td></tr>`;
      return;
    }

    data.forEach((item) => {
      const emp = item.timesheetData || {};
      const empName = emp.employeeName || "N/A";
      const empId = item.employeeId || emp.employeeId || "N/A";
      const cycleId = item.cycle_id || "";
      const cycleLabel = emp.cycle_label || "-";

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${empId}</td>
        <td><a href="#" class="employee-link" onclick="openEmployeeDetails('${empId}','${cycleId}')">
        ${empName}
      </a></td>
        <td><span style="background:#e0e7ff;color:#3730a3;padding:.2rem .6rem;border-radius:6px;font-size:.82rem;font-weight:700;">${cycleLabel}</span></td>
        <td>
          <button type="button" class="action-btn approve-btn">
            <i class="fas fa-check"></i> Approve
          </button>
          <button type="button" class="action-btn reject-btn">
            <i class="fas fa-times"></i> Reject
          </button>
        </td>
      `;
      tbody.appendChild(tr);

      const approveBtn = tr.querySelector(".approve-btn");
      const rejectBtn = tr.querySelector(".reject-btn");

      approveBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        approveEmployee(empId);
      });

      rejectBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        rejectEmployee(empId);
      });
    });
  } catch (err) {
    console.error("loadPendingList error:", err);
  }
  updateApproveAllButtons();
}

async function loadRejectedList() {
  try {
    const res = await fetch(
      `${API_URL}/get_rejected_employees/${loggedInEmployeeId}`,
      { headers: getHeaders() }
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();

    const data = Array.isArray(result.employees) ? result.employees : result.data || result.Data || [];

    const tbody = document.getElementById("rejectedTableBody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!data.length) {
      tbody.innerHTML = `<tr><td colspan="4">No rejected employees</td></tr>`;
      return;
    }

    data.forEach((item) => {
      const emp = item.timesheetData || {};
      const empName = emp.employeeName || "N/A";
      const empId = item.employeeId || emp.employeeId || "N/A";
      const cycleId = item.cycle_id || "";
      const cycleLabel = emp.cycle_label || "-";

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${empId}</td>
        <td><a href="#" class="employee-link" onclick="openEmployeeDetails('${empId}','${cycleId}')">
        ${empName}
      </a></td>
        <td><span style="background:#fee2e2;color:#991b1b;padding:.2rem .6rem;border-radius:6px;font-size:.82rem;font-weight:700;">${cycleLabel}</span></td>
        <td>
          <button
            class="action-btn approve-btn"
            onclick="approveEmployee('${empId}')">
            <i class="fas fa-check"></i> Approve
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("loadRejectedList error", err);
  }
  updateApproveAllButtons();
}

/* Approve / Reject employee flows */
async function approveEmployee(employeeId) {
  try {
    let token =
      localStorage.getItem("access_token") ||
      localStorage.getItem("token") ||
      sessionStorage.getItem("token");

    if (!token) {
      showPopup("Session expired. Please login again.", true);
      return;
    }

    const managerCode =
      loggedInEmployeeId ||
      localStorage.getItem("loggedInEmployeeId") ||
      sessionStorage.getItem("loggedInEmployeeId");

    if (!managerCode) {
      showPopup("Manager session missing. Please login again.", true);
      return;
    }

    const payload = {
      reporting_emp_code: managerCode,
      employee_code: employeeId,
    };

    const res = await fetch(`${API_URL}/approve_timesheet`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const result = await res.json().catch(() => ({}));

    if (res.status === 401 || result.detail === "Invalid token") {
      showPopup("Session expired. Please login again.", true);
      localStorage.clear();
      sessionStorage.clear();
      window.location.href = "/static/login.html";
      return;
    }

    if (!res.ok || !result.success) {
      showPopup("Approve failed", true);
      return;
    }

    showPopup(`Employee ${employeeId} approved successfully`);

    document
      .querySelectorAll("#pendingTableBody tr, #rejectedTableBody tr")
      .forEach((tr) => {
        const idCell = tr.querySelector("td");
        if (idCell && idCell.textContent.trim() === employeeId) {
          tr.remove();
        }
      });

    await loadPendingList();
    await loadApprovedList();
    await loadRejectedList();
  } catch (err) {
    console.error("approveEmployee error:", err);
    showPopup("Approve failed", true);
  }
}

async function rejectEmployee(employeeId) {
  // Show rejection reason dialog
  const reason = await _promptRejectionReason(employeeId);
  if (reason === null) return; // user cancelled

  try {
    let token =
      localStorage.getItem("access_token") ||
      localStorage.getItem("token") ||
      sessionStorage.getItem("token");

    if (!token) {
      showPopup("Session expired. Please login again.", true);
      return;
    }

    window.onbeforeunload = null;

    const payload = {
      reporting_emp_code: loggedInEmployeeId,
      employee_code: employeeId,
      reason: reason,
    };

    const res = await fetch(`${API_URL}/reject_timesheet`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const result = await res.json().catch(() => ({}));

    if (res.status === 401 || result.detail === "Invalid token") {
      showPopup("Session expired. Please login again.", true);
      localStorage.clear();
      sessionStorage.clear();
      window.location.href = "/static/login.html";
      return;
    }

    if (!res.ok || !result.success) {
      showPopup("Reject failed", true);
      return;
    }

    showPopup(`Employee ${employeeId} rejected successfully`);
    await loadPendingList();
    await loadApprovedList();
    await loadRejectedList();
  } catch (err) {
    console.error("rejectEmployee error:", err);
    showPopup("Reject failed", true);
  }
}

function _promptRejectionReason(employeeId) {
  return new Promise(resolve => {
    // Build inline modal
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;display:flex;align-items:center;justify-content:center;';
    overlay.innerHTML = `
      <div style="background:#fff;border-radius:16px;padding:2rem 2.2rem;max-width:440px;width:90%;box-shadow:0 20px 50px rgba(0,0,0,.2);">
        <div style="font-size:1.8rem;text-align:center;margin-bottom:.8rem;">⚠️</div>
        <h3 style="font-size:1.1rem;font-weight:700;color:#1e293b;margin-bottom:.5rem;text-align:center;">Reject Timesheet</h3>
        <p style="font-size:.88rem;color:#64748b;margin-bottom:1.2rem;text-align:center;">Employee: <strong>${employeeId}</strong></p>
        <label style="font-weight:600;font-size:.9rem;color:#475569;display:block;margin-bottom:.4rem;">Rejection Reason (optional)</label>
        <textarea id="_rejectReasonInput" rows="3" placeholder="Enter reason for rejection..." style="width:100%;padding:.75rem;border:2px solid #e2e8f0;border-radius:10px;font-size:.95rem;font-family:inherit;resize:vertical;outline:none;box-sizing:border-box;"></textarea>
        <div style="display:flex;gap:.8rem;justify-content:center;margin-top:1.2rem;">
          <button id="_rejectConfirmBtn" style="background:#ef4444;color:#fff;border:none;padding:.75rem 1.8rem;border-radius:10px;font-size:.95rem;font-weight:700;cursor:pointer;">Reject</button>
          <button id="_rejectCancelBtn" style="background:#f1f5f9;color:#475569;border:none;padding:.75rem 1.5rem;border-radius:10px;font-size:.95rem;font-weight:600;cursor:pointer;">Cancel</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.querySelector('#_rejectConfirmBtn').onclick = () => {
      const reason = (overlay.querySelector('#_rejectReasonInput').value || '').trim();
      document.body.removeChild(overlay);
      resolve(reason);
    };
    overlay.querySelector('#_rejectCancelBtn').onclick = () => {
      document.body.removeChild(overlay);
      resolve(null);
    };
  });
}

/* Navigation helper */
async function showSection(section) {
  await checkUserRole();
  const sections = ["timesheet", "history", "approve", "pending", "rejected"];
  sections.forEach((s) => {
    const el = document.getElementById(`${s}Section`);
    if (el) el.style.display = s === section ? "block" : "none";
  });

  try {
    document
      .querySelectorAll(".nav-menu a")
      .forEach((a) => a.classList.remove("active"));
    const link = Array.from(document.querySelectorAll(".nav-menu a")).find(
      (a) => a.getAttribute("onclick")?.includes(`'${section}'`)
    );
    if (link) link.classList.add("active");
  } catch (e) {}

  if (section === "history") {
    await loadHistory();
  }
  if (section === "approve") await loadApprovedList();
  if (section === "pending") await loadPendingList();
  if (section === "rejected") await loadRejectedList();
}

/* Logout & UI helpers */
function logout() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("loggedInEmployeeId");
  fetch(`${API_URL}/logout`, { method: "POST", headers: getHeaders() }).finally(
    () => {
      window.location.href = "/static/login.html";
    }
  );
}
function toggleNavMenu() {
  const el = document.getElementById("navMenu");
  if (el) el.classList.toggle("active");
}

function clearTimesheet(auto = false) {
  if (!auto && !confirm("Clear all timesheet data from the form?")) return;
  renderTimesheetTable();
  if (_selectedCycle) populateAllCycleDateRows();
  document.querySelectorAll("textarea").forEach((t) => (t.value = ""));
  // Reset idle time fields
  const statusEl = document.getElementById('idle_time_status');
  if (statusEl) statusEl.value = 'No';
  const hoursEl = document.getElementById('idle_time_hours');
  if (hoursEl) hoursEl.value = '';
  const reasonEl = document.getElementById('idle_time_reason');
  if (reasonEl) reasonEl.value = '';
  if (typeof toggleIdleTimeFields === 'function') toggleIdleTimeFields();
  updateSummary();
  if (!auto) showPopup("Timesheet cleared");
}

/* beforeunload protection */
let isExiting = false;
window.addEventListener("beforeunload", function (e) {
  if (!isExiting) {
    e.preventDefault();
    e.returnValue = "";
    return "";
  }
});

/* modal close / exit confirmation popups */
function showPopup(message, isError = false) {
  console.log("🟢 showPopup triggered with:", message, "isError:", isError);

  const popup = document.getElementById("successPopup");
  const msg = document.getElementById("popupMessage");
  // if (!popup || !msg) return alert(message);

  msg.innerHTML = isError
    ? `<i class='fas fa-times-circle'></i> ${message}`
    : `<i class='fas fa-check-circle'></i> ${message}`;

  popup.classList.remove("error", "show");
  if (isError) popup.classList.add("error");

  popup.style.visibility = "visible";
  popup.style.opacity = "1";
  popup.classList.add("show");

  setTimeout(() => {
    popup.classList.remove("show");
    popup.style.opacity = "0";
    popup.style.visibility = "hidden";
  }, 3000);
}

function closePopup() {
  const popup = document.getElementById("successPopup");
  if (!popup) return;
  popup.classList.remove("show");
  popup.style.opacity = "0";
  popup.style.visibility = "hidden";
}

function showExitConfirmation() {
  const popup = document.getElementById("exitConfirmation");
  if (popup) {
    popup.style.display = "block";
  } else {
    console.error("⚠️ Exit confirmation popup not found!");
  }
}

function confirmExit() {
  const popup = document.getElementById("exitConfirmation");
  if (popup) popup.style.display = "none";
  window.onbeforeunload = null;
  localStorage.clear();
  sessionStorage.clear();
  setTimeout(() => {
    window.location.href = "/static/login.html";
  }, 300);
}

function cancelExit() {
  const popup = document.getElementById("exitConfirmation");
  if (popup) popup.style.display = "none";
}

/* Excel upload */
// async function handleExcelUpload(event) {
//   const file = event.target.files[0];
//   if (!file) return;

//   try {
//     showPopup("Uploading Excel data...", false);

//     const reader = new FileReader();
//     reader.onload = async function (e) {
//       const data = new Uint8Array(e.target.result);
//       const workbook = XLSX.read(data, { type: "array" });

//       const firstSheet = workbook.SheetNames[0];
//       const worksheet = workbook.Sheets[firstSheet];
//       const jsonData = XLSX.utils.sheet_to_json(worksheet, { defval: "" });

//       console.log("✅ Parsed Excel Data:", jsonData);

//       const response = await fetch(`${API_URL}/upload_excel_timesheet`, {
//         method: "POST",
//         headers: {
//           "Content-Type": "application/json",
//           ...getHeaders()
//         },
//         body: JSON.stringify({ entries: jsonData }),
//       });

//       if (!response.ok) throw new Error("Upload failed!");

//       const result = await response.json();
//       console.log("✅ Server response:", result);

//       if (typeof loadTimesheetHistory === "function") {
//         await loadTimesheetHistory();
//       }

//       showPopup("Excel uploaded successfully!");
//     };

//     reader.readAsArrayBuffer(file);
//   } catch (error) {
//     console.error("❌ Error uploading Excel:", error);
//     showPopup("Failed to upload Excel file!", true);
//   }
// }

// function validateModalDate(input) {
//     const weekSel = document.querySelector(".week-period select");
//     const week = weekOptions.find(w => w.value === weekSel.value);
//     if (!week) return;

//     const start = formatDate(new Date(week.start));
//     const end = formatDate(new Date(week.end));

//     input.setAttribute("min", start);
//     input.setAttribute("max", end);

//     if (input.value < start || input.value > end) {
//         showPopup(`Please select a date within ${start} - ${end}`, true);
//         input.value = start;
//         input.classList.add("validation-error");
//     } else {
//         input.classList.remove("validation-error");
//     }
// }


function validateModalDate(dateInput) {
    if (!dateInput || !currentRow) return;
    const win = window._currentPayrollWindow;
    if (!win) return;

    const inputDateStr = dateInput.value;
    const cycleStartStr = new Date(win.start).toISOString().split('T')[0];
    const cycleEndStr = new Date(win.end).toISOString().split('T')[0];

    if (inputDateStr < cycleStartStr || inputDateStr > cycleEndStr) {
        dateInput.classList.add('validation-error');
        showValidationMessage(dateInput, 'Please select a date within the selected payroll cycle only.');
    } else {
        dateInput.classList.remove('validation-error');
        clearValidationMessage(dateInput);
    }

    const today = new Date();
    const sixtyDaysAgo = new Date(today.getTime() - (60 * 24 * 60 * 60 * 1000));
    const yesterday = new Date(today.getTime() - (24 * 60 * 60 * 1000));
    const sixtyDaysAgoStr = sixtyDaysAgo.toISOString().split('T')[0];
    const yesterdayStr = yesterday.toISOString().split('T')[0];

    if (inputDateStr < sixtyDaysAgoStr || inputDateStr > yesterdayStr) {
        dateInput.classList.add('validation-error');
        showValidationMessage(dateInput, 'Date must be within last 60 days up to yesterday');
    }
}




// Admin side: call when admin clicks Save
async function savePayrollWindow(month, year, par_status = "enable") {
  try {
    const token = localStorage.getItem("access_token"); // ya jo token use karte ho
    const res = await fetch("/admin/set-payroll", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: token ? `Bearer ${token}` : ""
      },
      body: JSON.stringify({ month: Number(month), year: Number(year), par_status })
    });
    const js = await res.json();
    if (!res.ok) throw new Error(js.detail || js.message || "Failed to save payroll");
    showPopup("Payroll saved"); // tumhara popup function
    return js;
  } catch (err) {
    console.error("savePayrollWindow error", err);
    showPopup("Failed to save payroll: " + err.message, true);
  }
}

// function validateDate(input) {
//     if (!input) return;

//     const section = input.closest(".timesheet-section") ||
//                     document.getElementById("modalOverlay");

//     const weekSelect = section.querySelector(".week-period select");
//     const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value);

//     const weekStart = formatDate(selectedWeek.start);
//     const weekEnd = formatDate(selectedWeek.end);

//     if (input.value < weekStart || input.value > weekEnd) {
//         showPopup(`Please select a date within the specified week only.`, true);
//         input.classList.add("validation-error");
//         input.value = weekStart; // Reset to valid
//     } else {
//         input.classList.remove("validation-error");
//     }
// }


async function handleExcelUpload(event) {
    console.log("Excel upload initiated");
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async function (e) {
        try {
            const data = new Uint8Array(e.target.result);
            // const workbook = XLSX.read(data, { type: 'array' });
            const workbook = XLSX.read(data, {
              type: 'array',
              cellDates: true
            });

            const sheetName = workbook.SheetNames[0];
            const sheet = workbook.Sheets[sheetName];
            // const jsonData = XLSX.utils.sheet_to_json(sheet, { defval: '' });
            const jsonData = XLSX.utils.sheet_to_json(sheet, {
              defval: '',
              raw: false
            });


            if (!jsonData || jsonData.length === 0) {
                showPopup('Excel file is empty.', true);
                return;
            }

            // ✅ Required columns to validate (Lunch Time & Travel Time are optional)
            const requiredColumns = [
                'Employee ID', 'Employee Name', 'Designation', 'Gender', 'Partner',
                'Reporting Manager', 'Date', 'Work',
                'Project Start Time', 'Project End Time', 'Client', 'Project', 'Project Code',
                'Reporting Manager Entry', 'Activity', 'Project Hours', 'Billable', 'Remarks'
            ];

            const fileColumns = Object.keys(jsonData[0]);
            const missingColumns = requiredColumns.filter(col => !fileColumns.includes(col));

            if (missingColumns.length > 0) {
                showPopup(`Invalid Excel format. Missing columns: ${missingColumns.join(', ')}`, true);
                return;
            }

            showLoading("Uploading Excel data");
            const toStr = v =>
              v instanceof Date
                ? v.toISOString().split('T')[0]
                : v !== null && v !== undefined
                ? String(v)
                : "";

            function excelTimeToMinutes(value) {
              if (value === '' || value === null || value === undefined) return null;

              // Already formatted string "HH:mm"
              if (typeof value === 'string' && value.includes(':')) {
                const [h, m] = value.split(':').map(Number);
                if (isNaN(h) || isNaN(m)) return null;
                return h * 60 + m;
              }

              // Excel time fraction (0–1)
              if (!isNaN(value)) {
                return Math.round(Number(value) * 24 * 60);
              }

              return null;
            }

            function minutesToHours(minutes) {
              return +(minutes / 60).toFixed(2);
            }

            function excelTimeToHHMM(value) {
              const mins = excelTimeToMinutes(value);
              if (mins === null) return '';

              const h = String(Math.floor(mins / 60)).padStart(2, '0');
              const m = String(mins % 60).padStart(2, '0');
              return `${h}:${m}`;
            }
            
            function calculateHours(row) {
              const start = excelTimeToMinutes(row['Project Start Time']);
              const end = excelTimeToMinutes(row['Project End Time']);

              if (start !== null && end !== null && end > start) {
                return minutesToHours(end - start);
              }

              // No valid time data → explicitly zero
              return 0;
            }

          const timesheetData = jsonData.map(row => {
            const calculatedHours = calculateHours(row);

            return {
              employeeId: toStr(row['Employee ID']) || '',
              employeeName: toStr(row['Employee Name']) || '',
              designation: toStr(row['Designation']) || '',
              gender: toStr(row['Gender']) || '',
              partner: toStr(row['Partner']) || '',
              reportingManager: toStr(row['Reporting Manager']) || '',
              date: toStr(row['Date']) || '',
              location: toStr(row['Work']) || '',

              projectStartTime: excelTimeToHHMM(row['Project Start Time']),
              projectEndTime: excelTimeToHHMM(row['Project End Time']),

              client: toStr(row['Client']) || '',
              project: toStr(row['Project']) || '',
              projectCode: toStr(row['Project Code']) || '',
              reportingManagerEntry: toStr(row['Reporting Manager Entry']) || '',
              activity: toStr(row['Activity']) || '',

              // 🔥 ONLY calculated values (as per your rule)
              projectHours: calculatedHours.toString(),

              billable: toStr(row['Billable']) || '',
              lunchTime: toStr(row['Lunch Time']) || '',
              travelTime: toStr(row['Travel Time']) || '',
              remarks: toStr(row['Remarks']) || '',
              hits: toStr(row['3 Hits']) || toStr(row['3 HITS']) || '',
              misses: toStr(row['3 Misses']) || toStr(row['3 MISSES']) || '',
              feedback_hr: toStr(row['Feedback for HR']) || '',
              feedback_it: toStr(row['Feedback for IT']) || '',
              feedback_crm: toStr(row['Feedback for CRM']) || '',
              feedback_others: toStr(row['Feedback for Others']) || '',
              idle_time_status: 'No',
              idle_time_hours: '',
              idle_time_reason: ''
            };
          });

          // Rows with no Date are unused buffer rows from the template (dropdown/
          // validation formatting can materialize a cell even when nothing was
          // typed into it) — they aren't real entries, so drop them here.
          const realEntries = timesheetData.filter(entry => entry.date && entry.date.trim() !== '');

          if (realEntries.length === 0) {
            hideLoading();
            showPopup('No filled-in rows found in this Excel file.', true);
            return;
          }

          // Same mandatory-field rule the manual "Save Week" flow enforces:
          // working-day rows must have every project field filled in. Leave /
          // PHY / Week Off rows are exempt (but whatever is filled stays).
          {
            const requireLunch = window._showLunchTravel !== false;
            const mandatoryFields = ['date', 'projectStartTime', 'projectEndTime', 'client', 'project', 'projectCode', 'reportingManagerEntry', 'activity'];
            const uploadErrors = [];
            realEntries.forEach((entry, i) => {
              if (isDayOffLocation(entry.location)) return;
              mandatoryFields.forEach(f => {
                if (!entry[f] || !entry[f].trim()) uploadErrors.push(`Row ${i + 1} (${entry.date || 'no date'}): ${f} is required`);
              });
              if (requireLunch && (!entry.lunchTime || !entry.lunchTime.trim())) {
                uploadErrors.push(`Row ${i + 1} (${entry.date || 'no date'}): Lunch Time is required`);
              }
            });
            if (uploadErrors.length) {
              hideLoading();
              showPopup(uploadErrors.slice(0, 5).join('\n'), true);
              return;
            }
          }

          // Every partner except the free-text one (JHS01) must use real Nexus
          // Quant project codes (they all start with "PL"). Non-working days
          // ("Leave" / "PHY" / "Week Off") have no project to charge, so they're
          // exempt from this check — as is a Client of "Other" (no fixed
          // project list to charge against), but its Project Code must then
          // literally read "Other".
          if (!window._freeTextClientProject) {
            const nonWorkingLocations = ['Leave', 'PHY', 'Week Off'];
            const badRow = realEntries.find(entry => {
              if (nonWorkingLocations.includes(entry.location)) return false;
              const isOtherClient = entry.client.trim().toUpperCase() === 'OTHER';
              if (isOtherClient) return entry.projectCode.trim().toUpperCase() !== 'OTHER';
              return !entry.projectCode.trim().toUpperCase().startsWith('PL');
            });
            if (badRow) {
              hideLoading();
              const isOtherClient = badRow.client.trim().toUpperCase() === 'OTHER';
              showPopup(
                isOtherClient
                  ? `Row with Client "Other" on ${badRow.date} must have Project Code "Other" (found "${badRow.projectCode || '(blank)'}").`
                  : `Invalid project code "${badRow.projectCode || '(blank)'}" on ${badRow.date}. ` +
                    `Projects must be from Nexus Quant only (project code must start with "PL").`,
                true
              );
              return;
            }
          }

          // Populate feedback fields from first row. Idle time is filled in the app, not the Excel template.
          if (timesheetData.length > 0) {
            const firstRow = jsonData[0];
            const statusEl = document.getElementById('idle_time_status');
            if (statusEl) statusEl.value = 'No';
            const hoursEl = document.getElementById('idle_time_hours');
            if (hoursEl) hoursEl.value = '';
            const reasonEl = document.getElementById('idle_time_reason');
            if (reasonEl) reasonEl.value = '';
            if (typeof toggleIdleTimeFields === 'function') toggleIdleTimeFields();
            ['hits','misses','feedback_hr','feedback_it','feedback_crm','feedback_others'].forEach(f => {
              const el = document.getElementById(f);
              const pretty = { hits:'3 Hits', misses:'3 Misses', feedback_hr:'Feedback for HR', feedback_it:'Feedback for IT', feedback_crm:'Feedback for CRM', feedback_others:'Feedback for Others' }[f];
              if (el) el.value = toStr(firstRow[pretty]) || toStr(firstRow[f]) || '';
            });
          }

          // Save the whole flat set of parsed rows as one draft
          const resDraft = await fetch(`${API_URL}/timesheet/save-draft`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
              cycle_id:    _selectedCycle.id,
              cycle_label: _selectedCycle.cycle_label,
              entries:     realEntries,
              metadata:    _collectMetadata()
            })
          });
          if (!resDraft.ok) {
            const errJson = await resDraft.json();
            throw new Error(errJson.detail || 'Failed to save draft from uploaded Excel');
          }

          // Load saved drafts onto the screen
          await loadDraftForCycle(_selectedCycle.id);
          hideLoading();
          showPopup('Excel uploaded and saved as drafts! Review your entries, fill in Idle Time if needed, then Submit.');

        } catch (error) {
            console.error('Error reading Excel:', error);
            hideLoading();
            showPopup(`Failed to upload Excel: ${error.message}`, true);
        }
    };

    reader.readAsArrayBuffer(file);
}

window.handleExcelUpload = handleExcelUpload;


function formatDate(date) {
  if (!date || !(date instanceof Date) || isNaN(date)) return "";
  return date.toISOString().split("T")[0]; // YYYY-MM-DD
}

// --------------------------------------------------------------
// Approve All (Pending or Rejected)
// --------------------------------------------------------------
async function approveAll(source) {        // source = "Pending" | "Rejected"
    if (!confirm(`Approve ALL ${source.toUpperCase()} timesheets?`)) return;

    showLoading(`Approving all ${source.toLowerCase()} timesheets...`);

    try {
        const payload = {
            reporting_emp_code: loggedInEmployeeId,
            source: source               // "Pending" or "Rejected"
        };

        const res = await fetch(`${API_URL}/approve_all_timesheets`, {
            method: "POST",
            headers: getHeaders(),
            body: JSON.stringify(payload)
        });

        const result = await res.json();

        hideLoading();

        if (!res.ok || !result.success) {
            showPopup(result.message || "Approve All failed", true);
            return;
        }

        showPopup(result.message);

        // Refresh the three lists
        await loadPendingList();
        await loadApprovedList();
        await loadRejectedList();

        // Hide the button again if the list became empty
        updateApproveAllButtons();

    } catch (err) {
        hideLoading();
        console.error("approveAll error:", err);
        showPopup("Approve All failed", true);
    }
}

// --------------------------------------------------------------
// Show “Approve All” button only when there is at least one row
// --------------------------------------------------------------
function updateApproveAllButtons() {
    const pendingRows   = document.querySelectorAll("#pendingTableBody tr").length;
    const rejectedRows  = document.querySelectorAll("#rejectedTableBody tr").length;

    document.getElementById("approveAllPendingContainer").style.display =
        pendingRows > 0 ? "block" : "none";

    document.getElementById("approveAllRejectedContainer").style.display =
        rejectedRows > 0 ? "block" : "none";
}

// Call this after every load of the tables
// (add it at the end of loadPendingList() and loadRejectedList())


// ── Idle Time toggle ─────────────────────────────────────────────────────────
function toggleIdleTimeFields() {
  const status = document.getElementById('idle_time_status')?.value || 'No';
  const hoursWrap = document.getElementById('idle_time_hours_wrapper');
  const reasonWrap = document.getElementById('idle_time_reason_wrapper');
  if (hoursWrap && reasonWrap) {
    if (status === 'Yes') {
      hoursWrap.style.display = 'block';
      reasonWrap.style.display = 'block';
    } else {
      hoursWrap.style.display = 'none';
      reasonWrap.style.display = 'none';
      const hi = document.getElementById('idle_time_hours');
      if (hi) hi.value = '';
      const ri = document.getElementById('idle_time_reason');
      if (ri) ri.value = '';
    }
  }
}
window.toggleIdleTimeFields = toggleIdleTimeFields;


// ── Download Sample Excel Template ───────────────────────────────────────────
// Uses ExcelJS (not the SheetJS/XLSX community build) because SheetJS's free
// build silently drops '!dataValidation' on write — the dropdowns never
// actually made it into the downloaded file. ExcelJS writes real, enforced
// dropdown validation (errorStyle: 'error' rejects anything typed that isn't
// in the list), matching the dropdown fields in the timesheet app itself.
async function downloadSampleTemplate() {
  if (!_selectedCycle) {
    showPopup('Please select a payroll cycle first.', true);
    return;
  }
  if (!employeeProjects || !employeeProjects.projects_by_client) {
    showPopup('Project details are not loaded yet. Please wait and try again.', true);
    return;
  }
  if (typeof ExcelJS === 'undefined') {
    showPopup('Template generator failed to load. Please refresh the page and try again.', true);
    return;
  }

  try {
    const empId       = document.getElementById('employeeId')?.value || '';
    const empName     = document.getElementById('employeeName')?.value || '';
    const designation = document.getElementById('designation')?.value || '';
    const gender      = document.getElementById('gender')?.value || '';
    const partner     = document.getElementById('partner')?.value || '';
    const repManager  = document.getElementById('reportingManager')?.value || '';

    const start = new Date(_selectedCycle.start_date);
    const end   = new Date(_selectedCycle.end_date);

    const wb = new ExcelJS.Workbook();
    const ws = wb.addWorksheet('Timesheet');
    const metaWS = wb.addWorksheet('MetadataLists', { state: 'hidden' });
    // Plain, visible reference tab — a flat, alphabetical Client/Project/Code
    // list with no formulas at all, so it can never break regardless of
    // Excel version (unlike a live-filtered dropdown, which needs the
    // FILTER() function that many real installs — e.g. Microsoft Office
    // LTSC — don't have and never will). Ctrl+F searches it like any text.
    const refWS = window._freeTextClientProject ? null : wb.addWorksheet('Client-Project List');

    const headers = [
      'Employee ID','Employee Name','Designation','Gender','Partner','Reporting Manager',
      'Date','Work','Project Start Time','Project End Time',
      'Client','Project','Project Code','Reporting Manager Entry','Activity',
      'Project Hours','Billable','Lunch Time','Travel Time','Remarks',
      '3 Hits','3 Misses','Feedback for HR','Feedback for IT','Feedback for CRM','Feedback for Others'
    ];
    const headerRow = ws.addRow(headers);
    headerRow.font = { bold: true };
    headerRow.eachCell(c => { c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8ECFB' } }; });
    ws.views = [{ state: 'frozen', ySplit: 1 }];

    let curr = new Date(start);
    let lastDateRow = 1;

    while (curr <= end) {
      const rIdx        = ws.rowCount + 1;
      const dateStr     = curr.toISOString().split('T')[0];
      const hFormula    = `IF(AND(I${rIdx}<>"",J${rIdx}<>""),(J${rIdx}-I${rIdx})*24,"")`;

      ws.addRow([
        empId, empName, designation, gender, partner, repManager,
        dateStr, '', '', '',
        '', '', '', repManager, '',
        { formula: hFormula }, 'Yes', '30 min', 'None', '',
        '', '', '', '', '', ''
      ]);
      lastDateRow = ws.rowCount;
      curr.setDate(curr.getDate() + 1);
    }

    // bufferRows gives room for extra rows beyond the cycle's actual dates —
    // both the pre-existing blank rows at the bottom, and any row a user
    // inserts in between via Excel's own Insert Row, since it's this whole
    // range (not just the date rows) that carries formulas/formatting/
    // validation identically throughout.
    const bufferRows = lastDateRow + 60;

    // Apply hh:mm format to Project Start/End Time columns (I, J) across the
    // full buffer range, not just the date rows, so inserted/extra rows format correctly too.
    for (let r = 2; r <= bufferRows; r++) {
      ws.getCell(`I${r}`).numFmt = 'hh:mm';
      ws.getCell(`J${r}`).numFmt = 'hh:mm';
    }

    // ── Build MetadataLists sheet (hidden helper sheet backing the dropdowns) ──
    const dateValues = [];
    let d = new Date(start);
    while (d <= end) { dateValues.push(d.toISOString().split('T')[0]); d.setDate(d.getDate() + 1); }

    const locations = ['Office','Client Site','Work From Home','Field Work','Leave','PHY','Week Off'];
    const billable  = ['Yes','No'];
    const lunch     = ['None','15 min','30 min','45 min','1 hr','1.5 hr','2 hr'];
    const travel    = ['None','15 min','30 min','45 min','1 hr','1.5 hr','2 hr','2.5 hr','3 hr'];
    // This partner's employees have no fixed client/project list to pick
    // from in the app (free-typed fields instead), so the template mirrors
    // that: no Client/Project/Project Code dropdowns or lookup formula.
    const freeTextClientProject = window._freeTextClientProject;
    // "Other" lets a dropdown-mode employee log against something outside
    // their assigned client list — same escape hatch as the app's Client
    // dropdown. Appended last so the real client list still reads cleanly.
    const clients   = freeTextClientProject ? [] : [...(employeeProjects.clients || []), 'Other'];
    // Reporting Manager is a free-text field in the app (no <select>/manager
    // list exists), so there is nothing to build a dropdown from — keep the
    // template's "Reporting Manager Entry" column as free text too.
    const managers  = [repManager].filter(v => v !== '');

    const clientCols = {};
    const projectCodeLookup = [];
    clients.forEach(c => {
      const projs = employeeProjects.projects_by_client[c] || []; // [] for "Other" — no fixed project list
      clientCols[c] = projs.map(p => p.project_name);
      projs.forEach(p => projectCodeLookup.push([p.project_name, p.project_code]));
    });

    const lookupNames = projectCodeLookup.map(p => p[0]);
    const lookupCodes = projectCodeLookup.map(p => p[1]);

    // ── Populate the plain Client-Project List reference tab ──
    if (refWS) {
      refWS.getCell('A1').value =
        'Use Ctrl+F to search for a Client or Project name below, then go back to the Timesheet tab ' +
        'and pick the matching entry from the dropdown in your row.';
      refWS.getCell('A1').font = { italic: true, size: 10, color: { argb: 'FF6B7280' } };
      refWS.mergeCells('A1:C1');
      refWS.getRow(1).height = 30;
      refWS.getCell('A1').alignment = { wrapText: true, vertical: 'middle' };

      const refHeaderRow = refWS.addRow(['Client', 'Project', 'Project Code']);
      refHeaderRow.font = { bold: true };
      refHeaderRow.eachCell(c => { c.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE8ECFB' } }; });

      clients.forEach(c => {
        if (c === 'Other') return; // "Other" has no fixed project list to reference
        const projs = employeeProjects.projects_by_client[c] || [];
        if (!projs.length) {
          refWS.addRow([c, '', '']);
        } else {
          projs.forEach(p => refWS.addRow([c, p.project_name, p.project_code]));
        }
      });

      refWS.views = [{ state: 'frozen', ySplit: 2 }];
      refWS.getColumn(1).width = 40;
      refWS.getColumn(2).width = 50;
      refWS.getColumn(3).width = 16;
    }

    // Column 1 (was "Week Periods") is intentionally left unused now that
    // week-wise grouping has been removed. Fixed columns B-H, per-client
    // project columns I+, lookup pair at X(24) & Y(25).
    const maxRows = Math.max(
      dateValues.length, locations.length,
      billable.length, lunch.length, travel.length, clients.length,
      managers.length, 1, ...clients.map(c => clientCols[c].length), lookupNames.length
    );

    metaWS.addRow(['', 'Dates','Locations','Billables','Lunch','Travel','Clients','Managers']);
    for (let r = 0; r < maxRows; r++) {
      metaWS.getCell(r + 2, 2).value = dateValues[r]       || '';
      metaWS.getCell(r + 2, 3).value = locations[r]        || '';
      metaWS.getCell(r + 2, 4).value = billable[r]         || '';
      metaWS.getCell(r + 2, 5).value = lunch[r]            || '';
      metaWS.getCell(r + 2, 6).value = travel[r]           || '';
      metaWS.getCell(r + 2, 7).value = clients[r]          || '';
      metaWS.getCell(r + 2, 8).value = managers[r]         || '';
    }
    clients.forEach((c, i) => {
      clientCols[c].forEach((projName, r) => { metaWS.getCell(r + 2, 9 + i).value = projName; });
    });
    metaWS.getCell(1, 24).value = 'ProjectName';
    metaWS.getCell(1, 25).value = 'ProjectCode';
    lookupNames.forEach((name, r) => { metaWS.getCell(r + 2, 24).value = name; });
    lookupCodes.forEach((code, r) => { metaWS.getCell(r + 2, 25).value = code; });

    // Shared-services (free-text partner) Project Code options — the fixed
    // SS-team list plus "Type Here", mirroring the app's dropdown.
    const ssProjectCodeOptions = freeTextClientProject
      ? [...SHARED_SERVICES_PROJECT_CODES, SHARED_SERVICES_TYPE_HERE]
      : [];
    metaWS.getCell(1, 27).value = 'SSProjectCodes';
    ssProjectCodeOptions.forEach((code, r) => { metaWS.getCell(r + 2, 27).value = code; });

    // ── Named ranges for the Client -> Project dependent dropdown ──
    // (indexed by position rather than a sanitized client name, so client
    // names with punctuation/special characters still resolve correctly)
    const colLetter = (n) => { // 1-based column index -> Excel letter
      let s = '';
      while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
      return s;
    };
    if (!freeTextClientProject) {
      clients.forEach((c, i) => {
        const col     = colLetter(9 + i);
        const numProj = Math.max(clientCols[c].length, 1);
        wb.definedNames.add(`MetadataLists!$${col}$2:$${col}$${numProj + 1}`, `Client_${i + 1}`);
      });
    }

    // Plain informational text below the table — no formula, no input cell,
    // just a pointer to the searchable reference tab. Can never break.
    if (!freeTextClientProject) {
      const noteCell = ws.getCell(`A${bufferRows + 2}`);
      noteCell.value = 'Looking for a specific Client or Project? See the "Client-Project List" tab — press Ctrl+F there to search. ' +
        'Need an extra row? Right-click a row number and choose Insert — the new row keeps working dropdowns for Client/Project/Project Code ' +
        '(pick Project Code from its dropdown too — it\'ll show the one matching code). ' +
        'For Project Code and Hours to auto-fill with no clicks at all, copy an existing row and use "Insert Copied Cells" instead.';
      noteCell.font = { italic: true, size: 9, color: { argb: 'FF6B7280' } };
      noteCell.protection = { locked: true };
    }

    // ── Data validations (strict: errorStyle 'error' blocks anything not on the list) ──
    const strictList = (formula1, allowBlank = true) => ({
      type: 'list',
      allowBlank,
      showErrorMessage: true,
      errorStyle: 'error',
      errorTitle: 'Invalid entry',
      error: 'Please choose a value from the dropdown list.',
      formulae: [formula1]
    });

    const clientsEnd = Math.max(clients.length + 1, 2);
    const lookupEnd  = Math.max(lookupNames.length + 1, 2);
    const dvDate     = strictList(`MetadataLists!$B$2:$B$${dateValues.length + 1}`);
    const dvLocation = strictList(`MetadataLists!$C$2:$C$${locations.length + 1}`);
    const dvBillable = strictList(`MetadataLists!$D$2:$D$${billable.length + 1}`);
    const dvLunch    = strictList(`MetadataLists!$E$2:$E$${lunch.length + 1}`);
    const dvTravel   = strictList(`MetadataLists!$F$2:$F$${travel.length + 1}`);
    // Plain static strict list — Excel dropdowns can't live-filter based on
    // their own in-progress typed text without a dynamic-array function
    // (FILTER), which many real-world Excel installs don't have (notably
    // Microsoft Office LTSC, which is permanently frozen without it — no
    // future update adds it). A live-search dropdown isn't reliably
    // achievable here, so this stays the plain, always-works list, same as
    // the app's own dropdown, with "Other" as the last option.
    const dvClient   = freeTextClientProject ? null : strictList(`MetadataLists!$G$2:$G$${clientsEnd}`);
    // Non-strict: shows the SS-team list as a dropdown but doesn't reject
    // typed text, so "Type Here" behaves the same as it does in the app —
    // pick a preset, or just type over it with anything else.
    const dvSSProjectCode = freeTextClientProject ? {
      type: 'list',
      allowBlank: true,
      showErrorMessage: false,
      formulae: [`MetadataLists!$AA$2:$AA$${ssProjectCodeOptions.length + 1}`]
    } : null;
    // Strict time-of-day validation so Project Start/End Time can only ever
    // hold an actual time value (rejects plain text, numbers, etc.).
    const dvTime = {
      type: 'time', operator: 'between', allowBlank: true,
      showErrorMessage: true, errorStyle: 'error',
      errorTitle: 'Invalid time',
      error: 'Enter a valid time (hh:mm), e.g. 09:30.',
      formulae: [0, 0.9999884259259259]
    };

    // (bufferRows was computed earlier, alongside the search-helper block)
    for (let r = 2; r <= bufferRows; r++) {
      ws.getCell(`G${r}`).dataValidation  = dvDate;
      ws.getCell(`H${r}`).dataValidation  = dvLocation;
      ws.getCell(`I${r}`).dataValidation  = dvTime;
      ws.getCell(`J${r}`).dataValidation  = dvTime;
      if (dvClient) ws.getCell(`K${r}`).dataValidation = dvClient;
      if (dvSSProjectCode) ws.getCell(`M${r}`).dataValidation = dvSSProjectCode;
      // Project's dependent-dropdown formula must reference *this* row's
      // Client cell explicitly (MATCH(K{r}, ...)) rather than a single
      // shared reference — ExcelJS splits a 500-row range into several XML
      // <dataValidation> blocks internally, and each block re-anchors its
      // relative references to its own first row. A shared formula silently
      // produced wrong (or empty) results for every row past the first
      // block, which is why Project stopped working partway down the sheet.
      // A per-row literal formula sidesteps that entirely. Non-strict (not
      // errorStyle 'error') so a Client of "Other" — which has no fixed
      // project list — can still be typed into freely.
      if (!freeTextClientProject) {
        ws.getCell(`L${r}`).dataValidation = {
          type: 'list', allowBlank: true, showErrorMessage: false,
          formulae: [`INDIRECT("Client_"&MATCH(K${r},MetadataLists!$G$2:$G$${clientsEnd},0))`]
        };
        // Project Code (M) is normally auto-filled by the formula set below —
        // but a row a user inserts via Excel's own Insert Row only inherits
        // formatting/validation, never formulas/values, which would otherwise
        // leave Project Code blank on an inserted row. Backing it with this
        // same dependent-dropdown trick as Project (a list formula resolving
        // to the single matching code's cell) means it still comes through on
        // an inserted row too — one click instead of zero, but no dead end.
        // Doesn't fight the formula: a formula-derived value never triggers
        // its own cell's validation, only a value the user types/picks does.
        ws.getCell(`M${r}`).dataValidation = {
          type: 'list', allowBlank: true, showErrorMessage: false,
          formulae: [`INDEX(MetadataLists!$Y$2:$Y$${lookupEnd},MATCH(L${r},MetadataLists!$X$2:$X$${lookupEnd},0))`]
        };
      }
      ws.getCell(`Q${r}`).dataValidation  = dvBillable;
      ws.getCell(`R${r}`).dataValidation  = dvLunch;
      ws.getCell(`S${r}`).dataValidation  = dvTravel;
    }

    // ── Project Code formula (Column M) — auto-fills "Other" when Client is
    // "Other", otherwise looks the code up from the picked Project. Skipped
    // for the free-text partner, whose Project Code column is plain typed text.
    // Applied across the full buffer range (not just the cycle's date rows) so
    // extra/inserted rows compute the code too, not just the original dates. ──
    if (!freeTextClientProject) {
      for (let r = 2; r <= bufferRows; r++) {
        ws.getCell(`M${r}`).value = {
          formula: `IF(K${r}="Other","Other",IFERROR(VLOOKUP(L${r},MetadataLists!$X$2:$Y$${lookupEnd},2,FALSE),""))`
        };
      }
    }

    // ── Project Hours formula (Column P) — computed from Start/End Time.
    // Only the cycle's date rows get it inline when created (above); extend it
    // across the full buffer range too, so extra/inserted rows compute hours
    // automatically as well, exactly like the real date rows do. ──
    for (let r = lastDateRow + 1; r <= bufferRows; r++) {
      ws.getCell(`P${r}`).value = {
        formula: `IF(AND(I${r}<>"",J${r}<>""),(J${r}-I${r})*24,"")`
      };
    }

    // ── Every column stays editable, including Project Code (M) — it's
    // auto-populated by formula for every row that already exists in the
    // file, but a row a user inserts via Excel's own Insert Row only
    // inherits formatting/validation (dropdowns), never formulas/values, so
    // a locked-but-formula-less Project Code cell on an inserted row would
    // be a permanent dead end. Leaving it unlocked means an inserted row
    // falls back to the same manual entry the "Client-Project List" tab
    // already exists to support. Every cell's protection is set explicitly
    // (never left at the default): ExcelJS appears to share a default style
    // object across untouched cells, so leaving one column "untouched" let
    // it silently pick up whatever locked state a neighboring cell happened
    // to set. ──
    const allDataCols = ['A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S','T','U','V','W','X','Y','Z'];
    const lockedCols = [];
    for (let r = 2; r <= bufferRows; r++) {
      allDataCols.forEach(col => {
        ws.getCell(`${col}${r}`).protection = { locked: lockedCols.includes(col) };
      });
      // A full row spans far more columns than A:Z. Excel's "Insert Copied
      // Cells" (the standard way to insert a fully-working row — dropdowns
      // *and* the Project Code/Hours formulas — by copying an existing row)
      // operates on the entire row width, and fails under sheet protection
      // if ANY cell in that width is still locked — including the untouched
      // columns beyond Z that the per-cell loop above never reaches. Setting
      // row-level protection covers the whole row so that paste succeeds.
      ws.getRow(r).protection = { locked: false };
    }
    await ws.protect('', {
      selectLockedCells: true,
      selectUnlockedCells: true,
      formatCells: false, formatColumns: false, formatRows: false,
      // Allow inserting rows (e.g. to add an extra entry between two existing
      // dates) even while the sheet stays protected. Every row up to
      // bufferRows already carries identical dropdowns/formulas/protection,
      // so a row inserted anywhere in that span inherits them the same way
      // Excel always extends validation/formatting into a row inserted inside
      // a uniformly-formatted range.
      insertRows: true, insertColumns: false, insertHyperlinks: false,
      deleteRows: false, deleteColumns: false,
      sort: false, autoFilter: false, pivotTables: false
    });

    // Reasonable column widths so the template reads like the app, not a raw dump
    const widths = [12,18,14,10,14,18,12,16,12,12,16,20,14,20,16,12,10,10,10,22,16,16,20,20,20,20];
    widths.forEach((w, i) => { ws.getColumn(i + 1).width = w; });

    const cycleLabel = _selectedCycle.cycle_label.replace(/[^a-zA-Z0-9]/g, '_');
    const fileName   = `Timesheet_Template_${empId}_${cycleLabel}.xlsx`;

    const buffer = await wb.xlsx.writeBuffer();
    const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    showPopup(`Template downloaded: ${fileName}`);

  } catch (err) {
    console.error('downloadSampleTemplate error:', err);
    showPopup(`Failed to generate template: ${err.message}`, true);
  }
}
window.downloadSampleTemplate = downloadSampleTemplate;


/* End of file */
