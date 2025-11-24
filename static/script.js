/* script.js - cleaned (punchIn/punchOut removed) */
console.log("✅ script.js loaded successfully");

let sectionCount = 0;
let employeeData = [];
let clientData = [];
let weekOptions = [];
let loggedInEmployeeId = localStorage.getItem("loggedInEmployeeId") || "";
// const API_URL = "http://localhost:8000";
const API_URL = "";
let copiedData = null; // for copy/paste row
let currentRow = null; // used by modal if present
let isEditingHistory = false;
let currentEntryId = null;
let historyEntries = [];



// Ye variable bana de top me
let weekOptionsReady = false;
window.weekOptions = [];

// Jab backend se weekOptions aaye (jo bhi function se aa raha hai, usme ye add kar de)
function loadWeekOptionsFromBackend() {
    // Ye tera existing function hoga jo /get-par-current-status call karta hai
    fetch("/get-par-current-status")
        .then(res => res.json())
        .then(data => {
            if (data && data.weeks && Array.isArray(data.weeks)) {
                window.weekOptions = data.weeks;
                console.log("weekOptions loaded successfully:", window.weekOptions);
                weekOptionsReady = true;

                // Ab saare existing sections ko update kar do
                document.querySelectorAll('.timesheet-section').forEach(section => {
                    const sectionId = section.id;
                    const weekSelect = section.querySelector('select[id^="weekPeriod_"]');
                    if (weekSelect) {
                        // Re-populate options if needed
                        populateWeekDropdown(weekSelect, window.weekOptions);
                        // Reset week value if invalid
                        if (!window.weekOptions.find(w => w.value === weekSelect.value)) {
                            weekSelect.value = window.weekOptions[0]?.value || "";
                        }
                        updateExistingRowDates(sectionId);
                    }
                });
            }
        })
        .catch(err => {
            console.error("Failed to load weeks:", err);
            window.weekOptions = [];
        });
}
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

// Ye line backend se data aane ke baad chalana
weekOptionsReady = true;
console.log("weekOptions ready! Validation enabled.");

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
  setTimeout(() => {
    dv.style.display = "none";
  }, 5000);
}

document.addEventListener("DOMContentLoaded", function () {
    // Ye line sabse important hai — weekOptions ko global bana de
    if (typeof weekOptions !== "undefined" && Array.isArray(weekOptions)) {
        window.weekOptions = weekOptions;
        console.log("weekOptions loaded:", window.weekOptions);
    } else {
        console.error("weekOptions not found or not array!");
       // Ye line daal de — bas itna hi kaafi hai
        window.weekOptions = typeof weekOptions !== "undefined" ? weekOptions : [];
    }

    // Baaki sab initialization yaha hoga...
});

document.addEventListener("DOMContentLoaded", async () => {
  const token = localStorage.getItem("access_token");
  if (!token) {
    window.location.href = "/static/login.html";
    return;
  }

  // ✅ Step 1: Verify session
  try {
    const res = await fetch(`${API_URL}/verify_session`, {
      method: "POST",
      headers: getHeaders(),
    });
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
    clientData = await safeFetchJson("/clients");

    // ✅ Step 2: initialize week options BEFORE creating UI
    await initWeekOptions();

    // ✅ Step 3: populate employee data + week sections
    populateEmployeeInfo();
    addWeekSection();

    // ✅ Step 4: show correct role
    await checkUserRole();
    showSection("timesheet");
  } catch (err) {
    console.error("Init error:", err);
    showPopup("Failed to initialize data. See console.", true);
  } finally {
    hideLoading();
  }
});


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


function generateWeekOptions(start, end) {
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const weeks = [];
  let weekNum = 1;

  // Clone start date
  let current = new Date(start);

  // 🟢 1️⃣ First week: from payroll start → upcoming Sunday
  const firstWeekEnd = new Date(current);
  const daysToSunday = 7 - firstWeekEnd.getDay(); // e.g. if Wed → 4 days to Sunday
  firstWeekEnd.setDate(firstWeekEnd.getDate() + (daysToSunday === 7 ? 0 : daysToSunday));

  weeks.push(makeWeekObject(current, firstWeekEnd, weekNum++, months));

  // 🟢 2️⃣ Move to next Monday
  current = new Date(firstWeekEnd);
  current.setDate(current.getDate() + 1);

  // 🟢 3️⃣ Add full Mon–Sun weeks
  while (current < end) {
    const weekStart = new Date(current);
    const weekEnd = new Date(weekStart);
    weekEnd.setDate(weekStart.getDate() + 6);

    if (weekEnd > end) weekEnd.setTime(end.getTime()); // last week truncated
    weeks.push(makeWeekObject(weekStart, weekEnd, weekNum++, months));

    current = new Date(weekEnd);
    current.setDate(current.getDate() + 1);
  }

  return weeks;
}


// 🔹 Helper to build each week object
function makeWeekObject(start, end, weekNum, months) {
  const wsDay = start.getDate().toString().padStart(2, '0');
  const wsMonth = months[start.getMonth()];
  const weDay = end.getDate().toString().padStart(2, '0');
  const weMonth = months[end.getMonth()];
  const value = `${wsDay}/${start.getMonth() + 1}/${start.getFullYear()} to ${weDay}/${end.getMonth() + 1}/${end.getFullYear()}`;
  const text = `Week ${weekNum} (${wsDay} ${wsMonth} - ${weDay} ${weMonth})`;

  return { value, text, start, end };
}



// top-level cache for current payroll window
window._currentPayrollWindow = null; // { start: ISO, end: ISO }

// Improved init — fetch from server and build weekOptions
async function initWeekOptions() {
  try {
    // If /get-par-current-status requires auth, use getHeaders() else getHeaders(false)
    const res = await fetch("/get-par-current-status", { headers: getHeaders() });
    const data = await res.json();

    let start, end;
    if (data && data.start && data.end) {
      start = new Date(data.start);
      end = new Date(data.end);
      window._currentPayrollWindow = { start: start.toISOString(), end: end.toISOString() };
    } else {
      const fallback = getPayrollWindow();
      start = fallback.start;
      end = fallback.end;
      window._currentPayrollWindow = { start: start.toISOString(), end: end.toISOString() };
    }

    window.weekOptions = generateWeekOptions(start, end);

    // update all existing selects
    document.querySelectorAll('select[id^="weekPeriod_"]').forEach(select => {
      select.innerHTML = "";
      window.weekOptions.forEach(week => {
        const o = document.createElement("option");
        o.value = week.value;
        o.textContent = week.text;
        select.appendChild(o);
      });
    });

    console.log(`✅ Payroll Period: ${start.toDateString()} → ${end.toDateString()}`);

  } catch (err) {
    console.error("❌ Error fetching payroll window:", err);
    const { start, end } = getPayrollWindow();
    window._currentPayrollWindow = { start: start.toISOString(), end: end.toISOString() };
    window.weekOptions = generateWeekOptions(start, end);
  }
}

// Refresh function — update weekOptions only if admin changed payroll window
async function refreshPayrollWeeks() {
  try {
    const res = await fetch("/get-par-current-status", { headers: getHeaders() });
    if (!res.ok) {
      console.warn("refreshPayrollWeeks: server returned", res.status);
      return;
    }
    const data = await res.json();

    let startISO = data && data.start ? (new Date(data.start)).toISOString() : null;
    let endISO = data && data.end ? (new Date(data.end)).toISOString() : null;

    if (!startISO || !endISO) {
      const local = getPayrollWindow();
      startISO = local.start.toISOString();
      endISO = local.end.toISOString();
    }

    const newWindowHash = startISO + "|" + endISO;
    const oldWindow = window._currentPayrollWindow ? (window._currentPayrollWindow.start + "|" + window._currentPayrollWindow.end) : null;

    if (oldWindow !== newWindowHash) {
      console.log("🔄 Payroll window changed — updating week dropdowns");
      window._currentPayrollWindow = { start: startISO, end: endISO };
      const start = new Date(startISO);
      const end = new Date(endISO);
      window.weekOptions = generateWeekOptions(start, end);

      document.querySelectorAll('select[id^="weekPeriod_"]').forEach(select => {
        const prevVal = select.value;
        select.innerHTML = "";
        window.weekOptions.forEach(week => {
          const o = document.createElement("option");
          o.value = week.value;
          o.textContent = week.text;
          select.appendChild(o);
        });

        // try to keep selection if same value exists
        if (prevVal) {
          const found = Array.from(select.options).find(opt => opt.value === prevVal);
          if (found) select.value = prevVal;
        }
      });

      showPopup("Payroll weeks updated by admin — week period dropdown refreshed.");
    }
  } catch (err) {
    console.error("❌ Error refreshing payroll weeks:", err);
  }
}

// Auto-polling every 20 seconds (only when tab visible)
setInterval(() => {
  if (document.visibilityState === "visible") {
    refreshPayrollWeeks();
  }
}, 30000);

// Ensure initial run
(async () => {
  await initWeekOptions();
})();




function addWeekSection() {
  if (typeof sectionCount === "undefined") window.sectionCount = 0;
  sectionCount++;

  const sectionsDiv = document.getElementById("timesheetSections");
  if (!sectionsDiv) {
    console.error("❌ timesheetSections container not found");
    return;
  }

  const sectionId = `section_${sectionCount}`;
  const section = document.createElement("div");
  section.className = "timesheet-section";
  section.id = sectionId;

  const weekDiv = document.createElement("div");
  weekDiv.className = "week-period form-group";
  weekDiv.innerHTML = `<label>Week Period ${sectionCount}</label>`;

  const select = document.createElement("select");
  select.id = `weekPeriod_${sectionCount}`;
  select.className = "form-control";
  select.style.fontWeight = "500";          
  select.style.fontSize = "18px";          
  select.style.padding = "8px 12px";  
  select.style.color = "#2c3e50" ; 
  select.style.padding = "15px"   



  select.onchange = () => {
    if (typeof updateSummary === "function") updateSummary();
    if (typeof updateExistingRowDates === "function")
      updateExistingRowDates(sectionId);
  };

  

  // ✅ Step 2: Populate dropdown
  // ✅ Step 2: Populate dropdown directly from window.weekOptions
select.innerHTML = "";

if (window.weekOptions && window.weekOptions.length > 0) {
  window.weekOptions.forEach((week) => {
    const o = document.createElement("option");
    o.value = week.value; // "21/10/2025 to 26/10/2025"
    o.textContent = week.text; // "Week 1 (21 Oct - 26 Oct)"
    o.style.fontWeight = "500";
    select.appendChild(o);
  });
} else {
  const o = document.createElement("option");
  o.value = "";
  o.textContent = "No week periods found";
  o.style.fontWeight = "500";
  select.appendChild(o);
}


  weekDiv.appendChild(select);

  // Delete week button
  const delBtn = document.createElement("button");
  delBtn.className = "delete-week-btn";
  delBtn.textContent = "Delete Week";
  delBtn.onclick = () => {
    if (typeof deleteWeekSection === "function") deleteWeekSection(sectionId);
    else document.getElementById(sectionId)?.remove();
  };
  weekDiv.appendChild(delBtn);

  section.appendChild(weekDiv);

  // Table skeleton
  const tableWrapper = document.createElement("div");
  tableWrapper.className = "table-responsive";
  tableWrapper.innerHTML = `
    <table class="timesheet-table">
      <thead>
        <tr>
          <th>S.No</th><th>Add</th><th>Action</th><th>Date</th><th>Location</th><th>Punch In</th><th>Punch Out</th>
          <th>Project Start</th><th>Project End</th><th>Client</th><th>Project</th>
          <th>Project Code</th><th>Reporting Manager</th><th>Activity</th>
          <th>Project Hours</th><th>Working Hours</th><th>Billable</th><th>Remarks</th><th>Delete</th>
        </tr>
      </thead>
      <tbody id="timesheetBody_${sectionCount}"></tbody>
    </table>
  `;
  section.appendChild(tableWrapper);

  // Buttons
  const btnDiv = document.createElement("div");
  btnDiv.className = "button-container";
  btnDiv.innerHTML = `
    <button class="add-row-btn" onclick="addRow('${sectionId}')">+ Add New Entry</button>
  `;
  section.appendChild(btnDiv);

  sectionsDiv.appendChild(section);

  // Initial row
  if (typeof addRow === "function") addRow(sectionId);
  if (typeof updateExistingRowDates === "function")
    updateExistingRowDates(sectionId);

  console.log(`✅ Week section ${sectionId} added`);
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

/* update dates in existing rows to match selected week */
// function updateExistingRowDates(sectionId) {
//   const tbody = document.getElementById(
//     `timesheetBody_${sectionId.split("_")[1]}`
//   );
//   if (!tbody) return;

//   const weekSelect = document.getElementById(
//     `weekPeriod_${sectionId.split("_")[1]}`
//   );
//   const selectedWeekValue = weekSelect.value;
//   const selectedWeek = weekOptions.find(
//     (opt) => opt.value === selectedWeekValue
//   );

//   if (selectedWeek && selectedWeek.start) {
//     const weekStart = new Date(selectedWeek.start);
//     const defaultDate = `${weekStart.getFullYear()}-${String(
//       weekStart.getMonth() + 1
//     ).padStart(2, "0")}-${String(weekStart.getDate()).padStart(2, "0")}`;

//     const dateInputs = tbody.querySelectorAll(".date-field");
//     dateInputs.forEach((dateInput) => {
//       const currentDate = new Date(dateInput.value + "T00:00:00");
//       const weekStartDate = new Date(weekStart);
//       const weekEndDate = new Date(selectedWeek.end);

//       if (
//         !dateInput.value ||
//         currentDate < weekStartDate ||
//         currentDate > weekEndDate
//       ) {
//         dateInput.value = defaultDate;
//         validateDate(dateInput);
//       }
//     });
//   }
// }

// function updateExistingRowDates(sectionId) {
//     // YE LINE ADD KAR DO — SAB FIX HO JAYEGA
//     if (!weekOptionsReady || !window.weekOptions || window.weekOptions.length === 0) {
//         return; // Wait karo, abhi validate mat karo
//     }

//     const secNum = sectionId.split("_")[1];
//     const tbody = document.getElementById(`timesheetBody_${secNum}`);
//     const weekSelect = document.getElementById(`weekPeriod_${secNum}`);

//     if (!tbody || !weekSelect || !weekSelect.value) return;

//     const selectedWeek = window.weekOptions.find(w => w.value === weekSelect.value);
//     if (!selectedWeek || !selectedWeek.start || !selectedWeek.end) return;

//     const start = new Date(selectedWeek.start).toISOString().split("T")[0];
//     const end = new Date(selectedWeek.end).toISOString().split("T")[0];

//     tbody.querySelectorAll("input[type='date'], .date-field").forEach(input => {
//         input.min = start;
//         input.max = end;
//         if (!input.value || input.value < start || input.value > end) {
//             input.value = start;
//         }
//         validateDate(input);
//     });
// }
function updateExistingRowDates(sectionId) {
    const secNum = sectionId.split("_")[1];
    const tbody = document.getElementById(`timesheetBody_${secNum}`);
    if (!tbody) return;

    const weekSel = document.getElementById(`weekPeriod_${secNum}`);
    if (!weekSel) return;

    const week = weekOptions.find(w => w.value === weekSel.value);
    if (!week) return;

    const start = formatDate(new Date(week.start));
    const end = formatDate(new Date(week.end));

    tbody.querySelectorAll(".date-field").forEach(input => {
        input.setAttribute("min", start);
        input.setAttribute("max", end);

        if (!input.value || input.value < start || input.value > end) {
            input.value = start;
        }
    });

    // also sync modal (if open)
    const modalDate = document.getElementById("modalInput1");
    if (modalDate) {
        modalDate.setAttribute("min", start);
        modalDate.setAttribute("max", end);

        if (!modalDate.value || modalDate.value < start || modalDate.value > end) {
            modalDate.value = start;
        }
    }
}






/* add a new entry row */
function addRow(sectionId, specificDate = null) {
  const sectionNum = sectionId.split("_")[1];
  const tbody = document.getElementById(`timesheetBody_${sectionNum}`);
  if (!tbody) {
    console.error("Table body not found for", sectionId);
    return;
  }

  const weekSelect = document.getElementById(`weekPeriod_${sectionNum}`);
  const selectedWeek = weekOptions.find(
    (opt) => opt.value === (weekSelect ? weekSelect.value : "")
  );
  // const weekDates =
  //   selectedWeek && selectedWeek.start ? getWeekDates(selectedWeek.start) : [];
  // const defaultDate =
  //   specificDate ||
  //   (weekDates.length ? weekDates[0] : new Date().toISOString().split("T")[0]);
  let defaultDate;

if (specificDate) {
    defaultDate = specificDate;
} else if (selectedWeek && selectedWeek.start) {
    const ws = new Date(selectedWeek.start);
    defaultDate = `${ws.getFullYear()}-${String(ws.getMonth()+1).padStart(2,"0")}-${String(ws.getDate()).padStart(2,"0")}`;
} else {
    defaultDate = new Date().toISOString().split("T")[0];
}


  const rowIndex = tbody.querySelectorAll("tr").length + 1;
  const tr = document.createElement("tr");
  tr.innerHTML = `
  <td class="col-sno">${rowIndex}</td>
  <td class="col-add"><button class="eye-btn" onclick="openModal(this)"><i class="fas fa-eye"></i></button></td>
  <td class="col-action">
    <button class="copy-btn" onclick="copyRow(this)"><i class="fas fa-copy"></i> Copy</button>
    <button class="paste-btn" onclick="pasteRow(this)"><i class="fas fa-paste"></i> Paste</button>
  </td>
  <td class="col-date form-input"><input type="date" class="date-field form-input" value="${defaultDate}" onchange="validateDate(this); updateSummary()"></td>
  <td class="col-location">
    <select class="location-select form-input" onchange="updateSummary()">
      <option value="Office">Office</option>
      <option value="Client Site">Client Site</option>
      <option value="Work From Home">Work From Home</option>
      <option value="Field Work">Field Work</option>
    </select>
  </td>

  <!-- NEW: Punch In / Punch Out / Working Hours -->
  <td class="col-punch-in"><input type="time" class="punch-in form-input" onchange="validateTimes(this.closest('tr')); calculateWorkingHours(this.closest('tr'))"></td>
  <td class="col-punch-out"><input type="time" class="punch-out form-input" onchange="validateTimes(this.closest('tr')); calculateWorkingHours(this.closest('tr'))"></td>
  <td class="col-project-start"><input type="time" class="project-start form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
  <td class="col-project-end"><input type="time" class="project-end form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
  <td class="col-client form-input "><input type="text" class="client-field form-input" placeholder="Enter Client"></td>
  <td class="col-project"><input type="text" class="project-field form-input" placeholder="Enter Project"></td>
  <td class="col-project-code"><input type="text" class="project-code form-input" placeholder="Enter Project Code"></td>
  <td class="col-reporting-manager"><input type="text" class="reporting-manager-field form-input" placeholder="Enter Reporting Manager"></td>
  <td class="col-activity" style="min-width: 200px;"><input type="text" class="activity-field form-input" placeholder="Enter Activity" oninput="updateSummary()"></td>
  <td class="col-project-hours"><input type="number" class="project-hours-field form-input" readonly></td>
   <td class="col-working-hours"><input type="number" step="0.01" class="working-hours-field form-input" readonly></td>
  <td class="col-billable">
    <select class="billable-select form-input" onchange="updateSummary()">
      <option value="Yes">Billable</option>
      <option value="No">Non-Billable</option>
    </select>
  </td>
  <td class="col-remarks"><input type="text" class="remarks-field form-input" placeholder="Additional notes"></td>
  <td class="col-delete"><button class="delete-btn" onclick="deleteRow(this)">Delete</button></td>
`;

  tbody.appendChild(tr);

  const dateInput = tr.querySelector(".date-field");
  if (dateInput) validateDate(dateInput);
  updateRowNumbers(tbody.id);
  updateSummary();
}

// function addRow(sectionId) {
//     const tbody = document.getElementById(`timesheetBody_${sectionId.split('_')[1]}`);
//     if (!tbody) return;

//     const weekSelect = document.getElementById(`weekPeriod_${sectionId.split('_')[1]}`);
//     if (!weekSelect) return;

//     let defaultDate = new Date().toISOString().split('T')[0];
//     let minDate = "";
//     let maxDate = "";

//     // Safe check – agar weekOptions load nahi hua ya empty hai to crash nahi hoga
//     if (window.weekOptions && Array.isArray(window.weekOptions) && weekSelect.value) {
//         const selectedWeek = window.weekOptions.find(w => w.value === weekSelect.value);
//         if (selectedWeek && selectedWeek.start && selectedWeek.end) {
//             const start = new Date(selectedWeek.start);
//             const end = new Date(selectedWeek.end);
            
//             defaultDate = start.toISOString().split('T')[0];
//             minDate = defaultDate;
//             maxDate = end.toISOString().split('T')[0];
//         }
//     }


//     const rowCount = tbody.rows.length + 1;
//     const row = document.createElement('tr');
//     row.innerHTML = `
//         <td class="col-sno" style="min-width: 60px;">${rowCount}</td>
//         <td class="col-add" style="min-width: 60px;"><button class="eye-btn" onclick="openModal(this)"><i class="fas fa-eye"></i></button></td>
//         <td class="col-action" style="min-width: 120px;">
//             <button class="copy-btn" onclick="copyRow(this)">Copy</button>
//             <button class="paste-btn" onclick="pasteRow(this)">Paste</button>
//         </td>
//         <td class="col-date" style="min-width: 120px;">
//             <input type="date" value="${defaultDate}" class="date-field form-input"
//                    min="${minDate}" max="${maxDate}"
//                    onchange="validateDate(this); updateSummary()">
//         </td>
//         <td class="clo-location" style="min-width: 200px;"><select class="location-select form-input" onchange="updateSummary()">
//             <option value="Office">Office</option>
//             <option value="Client Site">Client Site</option>
//             <option value="Work From Home">Work From Home</option>
//             <option value="Field Work">Field Work</option>
//         </select></td>
//         <td class="col-punch-in" style="min-width: 120px;"><input type="time" class="punch-in form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
//         <td class="col-punch-out" style="min-width: 120px;"><input type="time" class="punch-out form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
//         <td class="col-project-start" style="min-width: 120px;"><input type="time" class="project-start form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
//         <td class="col-project-end" style="min-width: 120px;"><input type="time" class="project-end form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
//         <td class="col-client" style="min-width: 250px;"><input type="text" class="client-field form-input" placeholder="Enter Client" oninput="updateSummary()"></td>
//         <td class="col-project" style="min-width: 200px;"><input type="text" class="project-field form-input" placeholder="Enter Project" oninput="updateSummary()"></td>
//         <td class="col-project-code" style="min-width: 200px;"><input type="text" class="project-code form-input" placeholder="Enter Project Code" oninput="updateSummary()"></td>
//         <td class="col-reporting-manager"><input type="text" class="reporting-manager-field form-input" placeholder="Enter Reporting Manager" onchange="updateSummary()"></td>
//         <td class="col-activity" style="min-width: 200px;"><input type="text" class="activity-field form-input" placeholder="Enter Activity" oninput="updateSummary()"></td>
//         <td class="col-project-hours" style="min-width: 80px;"><input type="number" class="project-hours-field form-input" readonly></td>
//         <td class="col-working-hours" style="min-width: 80px;"><input type="number" class="working-hours-field form-input" readonly></td>
//         <td class="col-billable" style="min-width: 120px;"><select class="billable-select form-input" onchange="updateSummary()">
//             <option value="Yes">Billable</option>
//             <option value="No">Non-Billable</option>
//         </select></td>
//         <td class="col-remarks" style="min-width: 200px;"><input type="text" class="remarks-field form-input" placeholder="Additional notes"></td>
//         <td class="col-delete" style="min-width: 80px;"><button class="delete-btn" onclick="deleteRow(this)">Delete</button></td>
//     `;

//     tbody.appendChild(row);
//     updateSummary();
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

/* delete row / week */
function deleteRow(btn) {
  const row = btn.closest("tr");
  if (!row) return;
  const tbody = row.closest("tbody");
  row.remove();
  updateRowNumbers(tbody.id);
  updateSummary();
}
function deleteWeekSection(sectionId) {
  if (!confirm("Delete this week section?")) return;
  const section = document.getElementById(sectionId);
  if (section) section.remove();
  updateSummary();
}

/* Calculations & validations (punch removed) */
function calculateHours(row) {
  if (!row) return;
  const start = row.querySelector(".project-start")?.value;
  const end = row.querySelector(".project-end")?.value;
  const hoursField = row.querySelector(".project-hours-field");
  if (!start || !end) {
    if (hoursField) hoursField.value = "";
    // still compute working hours separately (if any)
    calculateWorkingHours(row);
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

  // also update working hours (punch-in/out) if those are present
  calculateWorkingHours(row);
  updateSummary();
}


function calculateWorkingHours(row) {
  if (!row) return;
  const punchIn = row.querySelector(".punch-in")?.value;
  const punchOut = row.querySelector(".punch-out")?.value;
  const workingField = row.querySelector(".working-hours-field");

  if (!punchIn || !punchOut) {
    if (workingField) workingField.value = "";
    updateSummary();
    return;
  }

  const [ih, im] = punchIn.split(":").map(Number);
  const [oh, om] = punchOut.split(":").map(Number);
  let inMin = ih * 60 + im;
  let outMin = oh * 60 + om;
  if (outMin < inMin) outMin += 24 * 60; // overnight
  const whrs = ((outMin - inMin) / 60).toFixed(2);
  if (workingField) workingField.value = whrs;
  updateSummary();
}


function validateTimes(rowOrModal, isModal = false) {
  try {
    if (!rowOrModal) return true;
    let startEl, endEl;

    if (isModal) {
      // For modal, we have both punch and project times - validate via modal ids
      // modal project start/end ids: modalInput5 & modalInput6
      // modal punch in/out ids: modalInput3 & modalInput4
      const mPS = document.getElementById("modalInput5");
      const mPE = document.getElementById("modalInput6");
      const mPI = document.getElementById("modalInput3");
      const mPO = document.getElementById("modalInput4");

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

      // check punch in/out
      if (mPI && mPO && mPI.value && mPO.value) {
        const [ph, pm] = mPI.value.split(":").map(Number);
        const [oh, om] = mPO.value.split(":").map(Number);
        let p = ph * 60 + pm, o = oh * 60 + om;
        if (o <= p) {
          mPO.classList.add("validation-error");
          showPopup("Punch Out must be later than Punch In", true);
          return false;
        } else mPO.classList.remove("validation-error");
      }

    } else {
      // row validation - validate both project and punch pairs
      const projStart = rowOrModal.querySelector(".project-start");
      const projEnd = rowOrModal.querySelector(".project-end");
      const pIn = rowOrModal.querySelector(".punch-in");
      const pOut = rowOrModal.querySelector(".punch-out");

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

      if (pIn && pOut && pIn.value && pOut.value) {
        const [ph, pm] = pIn.value.split(":").map(Number);
        const [oh, om] = pOut.value.split(":").map(Number);
        let p = ph * 60 + pm, o = oh * 60 + om;
        if (o <= p) {
          pOut.classList.add("validation-error");
          showPopup("Punch Out must be later than Punch In", true);
          return false;
        } else pOut.classList.remove("validation-error");
      }
    }
    return true;
  } catch (err) {
    console.warn("validateTimes error", err);
    return true;
  }
}


function validateDate(input) {
    if (!input || !input.value) return;

    const section = input.closest(".timesheet-section");
    if (!section) return;

    const weekSelect = section.querySelector('select[id^="weekPeriod_"]');
    if (!weekSelect || !weekSelect.value) return;

    // YE LINE SABSE ZAROORI HAI
    if (!weekOptionsReady || !window.weekOptions || window.weekOptions.length === 0) {
        return; // Ab koi error nahi aayega
    }

    const selectedWeek = window.weekOptions.find(w => w.value === weekSelect.value);
    if (!selectedWeek || !selectedWeek.start || !selectedWeek.end) return;

    const start = new Date(selectedWeek.start).toISOString().split("T")[0];
    const end = new Date(selectedWeek.end).toISOString().split("T")[0];

    input.min = start;
    input.max = end;

    if (input.value < start || input.value > end) {
        const prettyStart = new Date(start).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
        const prettyEnd = new Date(end).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
        showPopup(`Invalid Date! Must be ${prettyStart} - ${prettyEnd}`, true);
        input.value = start;
        input.style.border = "2px solid #e74c3c";
        setTimeout(() => input.style.border = "", 2000);
    }

    updateSummary();
}

// Backend se week options aane ke baad
// window.weekOptions = response.weekOptions || [];





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

function openModal(button) {
  isEditingHistory = false;
  currentRow = button.closest("tr");

  const modalOverlay = document.getElementById("modalOverlay");
  if (!modalOverlay) {
    showPopup("Modal not available in layout. Please add modalOverlay div.", true);
    return;
  }

  modalOverlay.style.display = "flex";

  // NEW → clean class-based mapping (supports punch in/out + working hours)
  const modalMap = [
    { modalId: "modalInput1", cls: ".date-field" },
    { modalId: "modalInput2", cls: ".location-select" },
    { modalId: "modalInput3", cls: ".punch-in" },
    { modalId: "modalInput4", cls: ".punch-out" },
    { modalId: "modalInput5", cls: ".project-start" },
    { modalId: "modalInput6", cls: ".project-end" },
    { modalId: "modalInput7", cls: ".client-field" },
    { modalId: "modalInput8", cls: ".project-field" },
    { modalId: "modalInput9", cls: ".project-code" },
    { modalId: "modalInput10", cls: ".reporting-manager-field" },
    { modalId: "modalInput11", cls: ".activity-field" },
    { modalId: "modalInput12", cls: ".project-hours-field" },
    { modalId: "modalInput13", cls: ".working-hours-field" },
    { modalId: "modalInput14", cls: ".billable-select" },
    { modalId: "modalInput15", cls: ".remarks-field" }
  ];

  modalMap.forEach(m => {
    const modalEl = document.getElementById(m.modalId);
    const rowEl = currentRow.querySelector(m.cls);

    if (modalEl) {
      modalEl.value = rowEl
        ? (rowEl.value || rowEl.textContent || "")
        : "";
    }
  });

  updateModalProjectHours();

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


function closeModal() {
  const modal = document.getElementById("modalOverlay");
  if (modal) modal.style.display = "none";
  currentRow = null;
  isEditingHistory = false;
  currentEntryId = null;
}

function updateModalProjectHours() {
  // Project hours from modalInput5/6 -> modalInput12
  const projectStart = document.getElementById("modalInput5")?.value;
  const projectEnd = document.getElementById("modalInput6")?.value;
  const projectHoursInput = document.getElementById("modalInput12");

  if (projectStart && projectEnd && projectHoursInput) {
    const [sh, sm] = projectStart.split(":").map(Number);
    const [eh, em] = projectEnd.split(":").map(Number);
    let s = sh * 60 + sm;
    let e = eh * 60 + em;
    if (e < s) e += 24 * 60;
    projectHoursInput.value = ((e - s) / 60).toFixed(2);
  }

  // Working hours from modalInput3/4 -> modalInput13
  const punchIn = document.getElementById("modalInput3")?.value;
  const punchOut = document.getElementById("modalInput4")?.value;
  const workingHoursInput = document.getElementById("modalInput13");

  if (punchIn && punchOut && workingHoursInput) {
    const [ph, pm] = punchIn.split(":").map(Number);
    const [oh, om] = punchOut.split(":").map(Number);
    let p = ph * 60 + pm;
    let o = oh * 60 + om;
    if (o < p) o += 24 * 60;
    workingHoursInput.value = ((o - p) / 60).toFixed(2);
  }
}


function saveModalEntry() {
  if (!currentRow) return;

  const modalInputs = document.querySelectorAll(
    "#modalOverlay input, #modalOverlay select"
  );
  const mapping = [
  { modalId: "modalInput1", rowClass: ".date-field" },
  { modalId: "modalInput2", rowClass: ".location-select" },
  { modalId: "modalInput3", rowClass: ".punch-in" },
  { modalId: "modalInput4", rowClass: ".punch-out" },
  { modalId: "modalInput5", rowClass: ".project-start" },
  { modalId: "modalInput6", rowClass: ".project-end" },
  { modalId: "modalInput7", rowClass: ".client-field" },
  { modalId: "modalInput8", rowClass: ".project-field" },
  { modalId: "modalInput9", rowClass: ".project-code" },
  { modalId: "modalInput10", rowClass: ".reporting-manager-field" },
  { modalId: "modalInput11", rowClass: ".activity-field" },
  { modalId: "modalInput12", rowClass: ".project-hours-field" },
  { modalId: "modalInput13", rowClass: ".working-hours-field" },
  { modalId: "modalInput14", rowClass: ".billable-select" },
  { modalId: "modalInput15", rowClass: ".remarks-field" }
];


  mapping.forEach((map) => {
  const modalInput = document.getElementById(map.modalId);
  const rowField = currentRow.querySelector(map.rowClass);

  if (modalInput && rowField) {
    if (
      rowField.tagName === "INPUT" ||
      rowField.tagName === "SELECT" ||
      rowField.tagName === "TEXTAREA"
    ) {
      rowField.value = modalInput.value;
    } else {
      const inner = rowField.querySelector("input, select, textarea");
      if (inner) inner.value = modalInput.value;
    }
  }
});


  calculateHours(currentRow);
  validateDate(currentRow.querySelector(".date-field"));
  closeModal();
  updateSummary();
}

/* Manager employee details modal (opens timeline and feedback) */
async function openEmployeeDetails(employeeId) {
  console.log("🔹 Opening employee timesheet for:", employeeId);

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
    const response = await fetch(`${API_URL}/get_timesheet/${employeeId}`, {
      method: "GET",
      headers: getHeaders(),
    });

    if (!response.ok) throw new Error("Failed to fetch timesheet data");
    const data = await response.json();

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
        </div>
      </div>
    `;

    let tableHTML = `
      <div style="max-height:55vh;overflow-y:auto;">
      <table class="timesheet-table" style="width:100%;font-size:14px;">
        <thead>
          <tr>
            <th>Date</th>
            <th>Week Period</th>
            <th>Client</th>
            <th>Project</th>
            <th>Activity</th>
            <th>Location</th>
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
              <td>${entry.weekPeriod || "-"}</td>
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
      </div>
    `;

    modalContent.innerHTML = `
      <div class="manager-view-wrapper">
        <h2 style="text-align:center;margin-bottom:1rem;">Employee Timesheet</h2>
        ${empDetailsHTML}
        ${tableHTML}
        ${feedbackHTML}
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

// /* History loader */
// async function loadHistory() {
//   if (!loggedInEmployeeId) {
//     showPopup("Employee ID not found", true);
//     return;
//   }

//   showLoading("Fetching history...");

//   try {
//     const res = await fetch(`${API_URL}/timesheets/${loggedInEmployeeId}`, {
//       headers: getHeaders(),
//     });
//     if (!res.ok) throw new Error(`Failed to fetch history: ${res.status}`);

//     const data = await res.json();
//     historyEntries = Array.isArray(data.Data) ? data.Data : [];
//     console.log(data);
//     const historyContent = document.getElementById("historyContent");
//     console.log(`History Entries: ${historyEntries}`)
//     if (!historyContent) {
//       showPopup("History container not found", true);
//       hideLoading();
//       return;
//     }

//     historyContent.innerHTML = "";

//     const totalEl = document.querySelector(
//       ".history-summary .total-hours .value"
//     );
//     const billEl = document.querySelector(
//       ".history-summary .billable-hours .value"
//     );
//     const nonBillEl = document.querySelector(
//       ".history-summary .non-billable-hours .value"
//     );

//     if (totalEl) totalEl.textContent = (data.totalHours || 0).toFixed(2);
//     if (billEl) billEl.textContent = (data.totalBillableHours || 0).toFixed(2);
//     if (nonBillEl)
//       nonBillEl.textContent = (data.totalNonBillableHours || 0).toFixed(2);

//     const entriesList = data.Data || [];
//     if (!entriesList.length) {
//       historyContent.innerHTML = "<p>No timesheet entries found.</p>";
//       hideLoading();
//       return;
//     }

//     const groupedWeeks = {};
//     entriesList.forEach((entry) => {
//       const week = entry.weekPeriod || "No Week";
//       if (!groupedWeeks[week]) groupedWeeks[week] = [];
//       groupedWeeks[week].push(entry);
//     });

//     Object.keys(groupedWeeks).forEach((weekPeriod, index) => {
//       const weekEntries = groupedWeeks[weekPeriod];
//       const weekDiv = document.createElement("div");
//       weekDiv.className = "history-week";
//       weekDiv.innerHTML = `<h3>Week Period: ${weekPeriod}</h3>`;

//       const tableWrapper = document.createElement("div");
//       tableWrapper.className = "table-responsive";
//       const table = document.createElement("table");
//       table.className = "timesheet-table history-table";
//       table.innerHTML = `
//         <thead>
//           <tr>
//             <th>S.No</th>
//             <th>Action</th>
//             <th>Date</th>
//             <th>Location</th>
//             <th>Punch IN</th>
//             <th>Punch Out</th>
//             <th>Project Start</th>
//             <th>Project End</th>
//             <th>Client</th>
//             <th>Project</th>
//             <th>Project Code</th>
//             <th>Reporting Manager</th>
//             <th>Activity</th>
//             <th>working Hours</th>
//             <th>project Hours</th>
//             <th>Billable</th>
//             <th>Remarks</th>
//           </tr>
//         </thead>
//         <tbody></tbody>
//       `;

//       const tbody = table.querySelector("tbody");

//       weekEntries.forEach((entry, idx) => {
//         const tr = document.createElement("tr");
//         const id = entry.id || "";

//         tr.innerHTML = `
//           <td>${idx + 1}</td>
//           <td style="min-width:160px;">
//             <button class="action-btn edit-btn" onclick="editHistoryRow(this, '${id}')"><i class="fas fa-edit"></i> Edit</button>
//             <button class="action-btn delete-btn" onclick="deleteHistoryRow(this, '${id}')"><i class="fas fa-trash"></i> Delete</button>
//           </td>
//           <td>${entry.date || ""}</td>
//           <td>${entry.location || ""}</td>
//           <td>${entry.punchIn || ""}</td>
//           <td>${entry.punchOut || ""}</td>
//           <td>${entry.projectStartTime || ""}</td>
//           <td>${entry.projectEndTime || ""}</td>
//           <td>${entry.client || ""}</td>
//           <td>${entry.project || ""}</td>
//           <td>${entry.projectCode || ""}</td>
//           <td>${entry.reportingManagerEntry || ""}</td>
//           <td>${entry.activity || ""}</td>
//           <td>${entry.workingHours || ""}</td>
//           <td>${entry.projectHours || ""}</td>
//           <td>${entry.billable || ""}</td>
//           <td>${entry.remarks || ""}</td>
//         `;
//         tbody.appendChild(tr);
//       });

//       tableWrapper.appendChild(table);
//       weekDiv.appendChild(tableWrapper);

//       const fb = weekEntries[0] || {};
//       const feedbackHtml = `
//         <div class="history-feedback">
//           <strong>3 HITS:</strong> ${fb.hits || ""} <br>
//           <strong>3 MISSES:</strong> ${fb.misses || ""} <br>
//           <strong>Feedback HR:</strong> ${fb.feedback_hr || ""} <br>
//           <strong>Feedback IT:</strong> ${fb.feedback_it || ""} <br>
//           <strong>Feedback CRM:</strong> ${fb.feedback_crm || ""} <br>
//           <strong>Feedback Others:</strong> ${fb.feedback_others || ""}
//         </div>
//       `;
//       weekDiv.insertAdjacentHTML("beforeend", feedbackHtml);

//       historyEntries.appendChild(weekDiv);
//     });

//     hideLoading();
//   } catch (err) {
//     console.error("loadHistory error:", err);
//     showPopup("Failed to load history", true);
//     hideLoading();
//   }
// }

async function loadHistory(){
          try {
            showLoading("Fetching History...");
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_URL}/timesheets/${loggedInEmployeeId}`, {
                headers: getHeaders()
            });

            if (!response.ok) {
                throw new Error('Failed to fetch history');
            }

            const data = await response.json();
            historyEntries = Array.isArray(data.Data) ? data.Data : [];
            console.log('API Response:', data); // Debug log to check structure
            const historyContent = document.getElementById('historyContent');
            historyContent.innerHTML = '';

            // Update summary hours in history section
            const totalHoursElement = document.querySelector('.history-summary .total-hours .value');
            const billableHoursElement = document.querySelector('.history-summary .billable-hours .value');
            const nonBillableHoursElement = document.querySelector('.history-summary .non-billable-hours .value');

            if (totalHoursElement && billableHoursElement && nonBillableHoursElement) {
                totalHoursElement.textContent = (data.totalHours || 0).toFixed(2);
                billableHoursElement.textContent = (data.totalBillableHours || 0).toFixed(2);
                nonBillableHoursElement.textContent = (data.totalNonBillableHours || 0).toFixed(2);

                if (!data.totalHours && data.Data && Array.isArray(data.Data)) {
                    const summary = data.Data.reduce(
                        (acc, entry) => {
                            const hours = parseFloat(entry.projectHours) || 0;
                            acc.totalHours += hours;
                            if (entry.billable === 'Yes') {
                                acc.totalBillableHours += hours;
                            } else if (entry.billable === 'No') {
                                acc.totalNonBillableHours += hours;
                            }
                            return acc;
                        },
                        { totalHours: 0, totalBillableHours: 0, totalNonBillableHours: 0 }
                    );
                    totalHoursElement.textContent = summary.totalHours.toFixed(2);
                    billableHoursElement.textContent = summary.totalBillableHours.toFixed(2);
                    nonBillableHoursElement.textContent = summary.totalNonBillableHours.toFixed(2);
                }
            }

            if (!data.Data || data.Data.length === 0) {
                historyContent.innerHTML = '<p>No timesheet entries found.</p>';
                hideLoading();
                return;
            }

            const groupedByWeek = {};
            data.Data.forEach(entry => {
                const week = entry.weekPeriod || 'No Week';
                if (!groupedByWeek[week]) {
                    groupedByWeek[week] = [];
                }
                groupedByWeek[week].push(entry);
            });

            Object.keys(groupedByWeek).forEach((week, index) => {
                const weekDiv = document.createElement('div');
                weekDiv.className = 'history-week';
                weekDiv.innerHTML = `<h3>Week Period: ${week}</h3>`;

                const tableWrapper = document.createElement('div');
                tableWrapper.className = 'table-responsive';
                const table = document.createElement('table');
                table.className = 'timesheet-table history-table';
                table.innerHTML = `
                    <thead>
                        <tr>
                            <th class="col-narrow col-sno">S.No</th>
                            <th class="col-narrow col-action">Action</th>
                            <th class="col-medium col-date">Date</th>
                            <th class="col-wide col-location">Location of Work</th>
                            <th class="col-medium col-punch-in">Punch In</th>
                            <th class="col-medium col-punch-out">Punch Out</th>
                            <th class="col-medium col-project-start">Project Start Time</th>
                            <th class="col-medium col-project-end">Project End Time</th>
                            <th class="col-wide col-client">Client</th>
                            <th class="col-wide col-project">Project</th>
                            <th class="col-project col-project-code">Project Code</th>
                            <th class="col-wide col-reporting-manager">Reporting Manager</th>
                            <th class="col-wide col-activity">Activity</th>
                            <th class="col-narrow col-project-hours">Project Hours</th>
                            <th class="col-narrow col-working-hours">Working Hours</th>
                            <th class="col-medium col-billable">Billable</th>
                            <th class="col-wide col-remarks">Remarks</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                `;
                const tbody = table.querySelector('tbody');

                

                groupedByWeek[week].forEach((entry, rowIndex) => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="col-sno">${rowIndex + 1}</td>
                    <td class="col-action" style="min-width: 120px;">
                        <button class="action-btn edit-btn" onclick="editHistoryRow(this, '${entry.id}')"><i class="fas fa-edit"></i> Edit</button>
                        <button class="action-btn delete-btn" onclick="deleteHistoryRow(this, '${entry.id}')"><i class="fas fa-trash"></i> Delete</button>
                    </td>
                    <td class="col-date">${entry.date || ''}</td>
                    <td class="col-location">${entry.location || ''}</td>
                    <td class="col-punch-in">${entry.punchIn || ''}</td>
                    <td class="col-punch-out">${entry.punchOut || ''}</td>
                    <td class="col-project-start">${entry.projectStartTime || ''}</td>
                    <td class="col-project-end">${entry.projectEndTime || ''}</td>
                    <td class="col-client">${entry.client || ''}</td>
                    <td class="col-project">${entry.project || ''}</td>
                    <td class="col-project-code">${entry.projectCode || ''}</td>
                    <td class="col-reporting-manager">${entry.reportingManagerEntry || ''}</td>
                    <td class="col-activity">${entry.activity || ''}</td>
                    <td class="col-project-hours">${entry.projectHours || ''}</td>
                    <td class="col-working-hours">${entry.workingHours || ''}</td>
                    <td class="col-billable">${entry.billable || ''}</td>
                    <td class="col-remarks">${entry.remarks || ''}</td>
                `;
                tbody.appendChild(row);
            });

                tableWrapper.appendChild(table);
                weekDiv.appendChild(tableWrapper);
                historyContent.appendChild(weekDiv);

                const feedbackDiv = document.createElement('div');
                feedbackDiv.className = 'history-feedback';
                feedbackDiv.innerHTML = `
                    <h4>Feedback for Week: ${week}</h4>
                    <div class="feedback-item"><strong>3 HITS:</strong> ${groupedByWeek[week][0].hits || ''}</div>
                    <div class="feedback-item"><strong>3 MISSES:</strong> ${groupedByWeek[week][0].misses || ''}</div>
                    <div class="feedback-item"><strong>FEEDBACK FOR HR:</strong> ${groupedByWeek[week][0].feedback_hr || ''}</div>
                    <div class="feedback-item"><strong>FEEDBACK FOR IT:</strong> ${groupedByWeek[week][0].feedback_it || ''}</div>
                    <div class="feedback-item"><strong>FEEDBACK FOR CRM:</strong> ${groupedByWeek[week][0].feedback_crm || ''}</div>
                    <div class="feedback-item"><strong>FEEDBACK FOR OTHERS:</strong> ${groupedByWeek[week][0].feedback_others || ''}</div>
                `;
                historyContent.appendChild(feedbackDiv);
            });

            hideLoading();
        } catch (error) {
            console.error('Error fetching history:', error);
            hideLoading();
            showPopup('Failed to load history: ' + error.message, true);
        }
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
    modalInputs[0].value = cells[2].textContent.trim(); // date
    modalInputs[1].value = cells[3].textContent.trim(); // location
    modalInputs[2].value = cells[4].textContent.trim(); // projectStartTime
    modalInputs[3].value = cells[5].textContent.trim(); // projectEndTime
    modalInputs[4].value = cells[6].textContent.trim(); // client
    modalInputs[5].value = cells[7].textContent.trim(); // project
    modalInputs[6].value = cells[8].textContent.trim(); // projectCode
    modalInputs[7].value = cells[9].textContent.trim(); // reportingManagerEntry
    modalInputs[8].value = cells[10].textContent.trim(); // activity
    modalInputs[9].value = cells[11].textContent.trim(); // projectHours
    modalInputs[10].value = cells[12].textContent.trim(); // billable
    modalInputs[11].value = cells[13].textContent.trim(); // remarks
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
  const inputs = modal.querySelectorAll("input, select, textarea");
  const updatePayload = {
    date: inputs[0].value,
    location: inputs[1].value,
    projectStartTime: inputs[2].value,
    projectEndTime: inputs[3].value,
    client: inputs[4].value,
    project: inputs[5].value,
    projectCode: inputs[6].value,
    reportingManagerEntry: inputs[7].value,
    activity: inputs[8].value,
    projectHours: inputs[9].value,
    billable: inputs[10].value,
    remarks: inputs[11].value,
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


// document.getElementById("submitBtn").addEventListener("click", saveDataToMongo);
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
      // Get inputs by CLASS, not by index
      const date = row.querySelector('.date-field')?.value;
      const location = row.querySelector('.location-select')?.value;
      const punchIn = row.querySelector('.punch-in')?.value;
      const punchOut = row.querySelector('.punch-out')?.value;
      const projectStart = row.querySelector('.project-start')?.value;
      const projectEnd = row.querySelector('.project-end')?.value;
      const client = row.querySelector('.client-field')?.value;
      const project = row.querySelector('.project-field')?.value;
      const projectCode = row.querySelector('.project-code')?.value;
      const reportingManager = row.querySelector('.reporting-manager-field')?.value;
      const activity = row.querySelector('.activity-field')?.value;
      const workingHours = row.querySelector('.working-hours-field')?.value;
      const projectHours = row.querySelector('.project-hours-field')?.value;
      const billable = row.querySelector('.billable-select')?.value;
      const remarks = row.querySelector('.remarks-field')?.value;

      // Mandatory field check
      const mandatory = { date,punchIn,punchOut, projectStart, projectEnd, client, project, projectCode, reportingManager, activity };
      for (const [field, value] of Object.entries(mandatory)) {
        if (!value || value.trim() === '') {
          console.log(`${field}: ${value}`)
          console.log("mandatory check failed")
          hasError = true;
          errorMessages.push(`Row ${rowIndex + 1} (Week ${secIndex + 1}): ${field} is required.`);
        }
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
        punchIn,
        punchOut,
        projectStartTime: projectStart,
        projectEndTime: projectEnd,
        client,
        project,
        projectCode,
        reportingManagerEntry: reportingManager,
        activity,
        projectHours: projectHours || "0",
        workingHours: workingHours || "0",
        billable,
        remarks,
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
      showPopup('Timesheet saved successfully!');
      setTimeout(() => location.reload(), 1500);
    } else {
      showPopup('Save failed: ' + (result.message || 'Unknown error'), true);
    }
  } catch (err) {
    hideLoading();
    console.error("Save error:", err);
    showPopup('Network error. Check console.', true);
  }
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
        'Week Period': '',
        'S.No': '',
        'Date': '',
        'Location of Work': '',
        'Project Start Time': '',
        'Project End Time': '',
        'Punch In': '',
        'Punch Out': '',
        'Client': '',
        'Project': '',
        'Project Code': '',
        'Reporting Manager Entry': '',
        'Activity': '',
        'Project Hours': '',
        'Working Hours': '',
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

    // Columns (same order as history)
    const columns = [
        "employeeId",
        "employeeName",
        "designation",
        "gender",
        "partner",
        "reportingManager",
        "weekPeriod",
        "date",
        "location",
        "punchIn",
        "punchOut",
        "projectStartTime",
        "projectEndTime",
        "client",
        "project",
        "projectCode",
        "reportingManagerEntry",
        "activity",
        "projectHours",
        "workingHours",
        "billable",
        "remarks",
        "hits",
        "misses",
        "feedback_hr",
        "feedback_it",
        "feedback_crm",
        "feedback_others"
    ];

    // Pretty Headers (same as history)
    const headersPretty = [
        "Employee ID",
        "Employee Name",
        "Designation",
        "Gender",
        "Partner",
        "Reporting Manager",
        "Week Period",
        "Date",
        "Location of Work",
        "Punch In",
        "Punch Out",
        "Project Start Time",
        "Project End Time",
        "Client",
        "Project",
        "Project Code",
        "Reporting Manager Entry",
        "Activity",
        "Project Hours",
        "Working Hours",
        "Billable",
        "Remarks",
        "3 HITS",
        "3 MISSES",
        "Feedback for HR",
        "Feedback for IT",
        "Feedback for CRM",
        "Feedback for Others"
    ];

    let cleanedRows = [];

    const sections = document.querySelectorAll(".timesheet-section");

    sections.forEach((section) => {
        const weekPeriod =
            section.querySelector(".week-period select")?.value || "";

        const rows = section.querySelectorAll("tbody tr");

        rows.forEach((row) => {
            const inputs = row.querySelectorAll("input, select");

            // Detect empty row (same logic as history)
            const date = inputs[0]?.value?.trim() || "";
            const project = inputs[7]?.value?.trim() || "";
            const client =
                inputs[6]?.value ||
                inputs[6]?.querySelector("option:checked")?.value ||
                "";

            if (!date && !project && !client) return;

            cleanedRows.push({
                employeeId: employeeInfo["Employee ID"],
                employeeName: employeeInfo["Employee Name"],
                designation: employeeInfo["Designation"],
                gender: employeeInfo["Gender"],
                partner: employeeInfo["Partner"],
                reportingManager: employeeInfo["Reporting Manager"],
                weekPeriod: weekPeriod,
                date,
                location:
                    inputs[1]?.value ||
                    inputs[1]?.querySelector("option:checked")?.value ||
                    "",
                punchIn: inputs[4]?.value || "",
                punchOut: inputs[5]?.value || "",
                projectStartTime: inputs[2]?.value || "",
                projectEndTime: inputs[3]?.value || "",
                client: client,
                project: project,
                projectCode: inputs[8]?.value || "",
                reportingManagerEntry: inputs[9]?.value || "",
                activity: inputs[10]?.value || "",
                projectHours: inputs[11]?.value || "",
                workingHours: inputs[12]?.value || "",
                billable: inputs[13]?.value || "",
                remarks: inputs[14]?.value || "",
                hits: document.getElementById("hits").value || "",
                misses: document.getElementById("misses").value || "",
                feedback_hr: document.getElementById("feedback_hr").value || "",
                feedback_it: document.getElementById("feedback_it").value || "",
                feedback_crm: document.getElementById("feedback_crm").value || "",
                feedback_others:
                    document.getElementById("feedback_others").value || ""
            });
        });
    });

    if (cleanedRows.length === 0) {
        showPopup("No valid data to export!", true);
        return;
    }

    const ws = XLSX.utils.json_to_sheet(cleanedRows, { header: columns });
    XLSX.utils.sheet_add_aoa(ws, [headersPretty], { origin: "A1" });

    const fileName = `Timesheet_${employeeInfo["Employee ID"]}_${new Date()
        .toISOString()
        .split("T")[0]}.xlsx`;

    XLSX.utils.book_append_sheet(wb, ws, "Timesheet");
    XLSX.writeFile(wb, fileName);

    showPopup("Timesheet exported successfully!");
}


function exportHistoryToExcel() {
    if (!historyEntries || historyEntries.length === 0) {
        showPopup("No history available!");
        return;
    }

    // Columns WITHOUT S.No
    const columns = [
        "employeeId",
        "employeeName",
        "designation",
        "gender",
        "partner",
        "reportingManager",
        "weekPeriod",
        "date",
        "location",
        "punchIn",
        "punchOut",
        "projectStartTime",
        "projectEndTime",
        "client",
        "project",
        "projectCode",
        "reportingManagerEntry",
        "activity",
        "projectHours",
        "workingHours",
        "billable",
        "remarks",
        "hits",
        "misses",
        "feedback_hr",
        "feedback_it",
        "feedback_crm",
        "feedback_others",
        "totalHours",
        "totalBillableHours",
        "totalNonBillableHours"
    ];

    // Header labels WITHOUT S.No
    const headersPretty = [
        "Employee ID",
        "Employee Name",
        "Designation",
        "Gender",
        "Partner",
        "Reporting Manager",
        "Week Period",
        "Date",
        "Location of Work",
        "Punch In",
        "Punch Out",
        "Project Start Time",
        "Project End Time",
        "Client",
        "Project",
        "Project Code",
        "Reporting Manager Entry",
        "Activity",
        "Project Hours",
        "Working Hours",
        "Billable",
        "Remarks",
        "3 HITS",
        "3 MISSES",
        "Feedback for HR",
        "Feedback for IT",
        "Feedback for CRM",
        "Feedback for Others",
        "Total Hours",
        "Total Billable Hours",
        "Total Non Billable Hours"
    ];

    // Prepare cleaned rows WITHOUT S.No
    const cleanedRows = historyEntries.map((row) => ({
        employeeId: row.employeeId || "",
        employeeName: row.employeeName || "",
        designation: row.designation || "",
        gender: row.gender || "",
        partner: row.partner || "",
        reportingManager: row.reportingManager || "",
        weekPeriod: row.weekPeriod || "",
        date: row.date || "",
        location: row.location || "",
        punchIn: row.punchIn || "",
        punchOut: row.punchOut || "",
        projectStartTime: row.projectStartTime || "",
        projectEndTime: row.projectEndTime || "",
        client: row.client || "",
        project: row.project || "",
        projectCode: row.projectCode || "",
        reportingManagerEntry: row.reportingManagerEntry || "",
        activity: row.activity || "",
        projectHours: row.projectHours || "",
        workingHours: row.workingHours || "",
        billable: row.billable || "",
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

    // Convert rows → sheet
    const worksheet = XLSX.utils.json_to_sheet(cleanedRows, { header: columns });

    // Insert Pretty Headers
    XLSX.utils.sheet_add_aoa(worksheet, [headersPretty], { origin: "A1" });

    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "History");

    const fileName = `History_${loggedInEmployeeId}_${new Date()
        .toISOString()
        .split("T")[0]}.xlsx`;

    XLSX.writeFile(workbook, fileName);

    showPopup("History exported successfully!");
}


// ✅ Updated checkUserRole function (final version)
async function checkUserRole() {
  try {
    console.log("🔎 Running checkUserRole()");

    // Step 1️⃣ - Get logged in user ID
    if (!loggedInEmployeeId) {
      console.warn("No loggedInEmployeeId found, hiding manager buttons by default");
      document.querySelectorAll(".manager-only").forEach(btn => btn.style.display = "none");
      return;
    }

    // Step 2️⃣ - Check if current user is a reporting manager
    const resMgr = await fetch(`${API_URL}/check_reporting_manager/${loggedInEmployeeId}`, {
      headers: getHeaders(),
    });

    let isManager = false;
    if (resMgr.ok) {
      const js = await resMgr.json();
      isManager = !!js.isManager;
      console.log("✅ Reporting manager check:", isManager);
    } else {
      console.warn("Reporting manager API returned", resMgr.status);
    }

    // Step 3️⃣ - Check Admin's global PAR status
    let parDisabled = false;
    try {
      const token = localStorage.getItem("access_token");
      console.log("🔍 Fetching PAR status from:", `${API_URL}/get-par-current-status`);

      const parRes = await fetch(`${API_URL}/get-par-current-status`, {
        method: "GET",
        headers: getHeaders()
        // body: JSON.stringify({ token }),
      });

      if (parRes.ok) {
        const pjson = await parRes.json();
        console.log("✅ PAR API Response:", pjson);
        const parStatus = pjson.par_status || "disable";
        parDisabled = parStatus === "disable";
      } else {
        console.warn("⚠️ PAR status API error:", parRes.status);
      }
    } catch (e) {
      console.error("🔥 PAR status fetch failed:", e);
    }

    // Step 4️⃣ - Final decision for showing/hiding manager buttons
    const managerButtons = document.querySelectorAll(".manager-only");
    managerButtons.forEach(btn => {
      if (isManager && !parDisabled) {
        btn.style.display = "inline-block";
      } else {
        btn.style.display = "none";
      }
    });

    if (!isManager) console.log("ℹ️ User is not a manager - manager buttons hidden.");
    else if (parDisabled) console.log("ℹ️ PAR is disabled - hiding manager buttons even though user is manager.");
    else console.log("ℹ️ Manager buttons visible.");

  } catch (err) {
    console.error("🔥 Error checking role or PAR status:", err);
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
      tbody.innerHTML = `<tr><td colspan="3">No approved employees</td></tr>`;
      return;
    }

    data.forEach((item) => {
      const emp = item.timesheetData || {};
      const empName = emp.employeeName || "N/A";
      const empId = item.employeeId || emp.employeeId || "N/A";

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${empId}</td>
        <td><a href="#" class="employee-link" onclick="openEmployeeDetails('${empId}')">
        ${empName}
      </a></td>
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

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${empId}</td>
        <td><a href="#" class="employee-link" onclick="openEmployeeDetails('${empId}')">
        ${empName}
      </a></td>
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
      tbody.innerHTML = `<tr><td colspan="3">No rejected employees</td></tr>`;
      return;
    }

    data.forEach((item) => {
      const emp = item.timesheetData || {};
      const empName = emp.employeeName || "N/A";
      const empId = item.employeeId || emp.employeeId || "N/A";

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${empId}</td>
        <td><a href="#" class="employee-link" onclick="openEmployeeDetails('${empId}')">
        ${empName}
      </a></td>
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
  document.querySelectorAll(".timesheet-section").forEach((s) => s.remove());
  sectionCount = 0;
  addWeekSection();
  document.querySelectorAll("textarea").forEach((t) => (t.value = ""));
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
  if (!popup || !msg) return alert(message);

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
    const section = currentRow.closest('.timesheet-section');
    const weekSelect = section.querySelector('.week-period select');
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value);
    if (!selectedWeek) return;

    const inputDateStr = dateInput.value;
    console.log("Selected week:", selectedWeek);
    const weekStartStr = `${selectedWeek.start.getFullYear()}-${String(selectedWeek.start.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.start.getDate()).padStart(2, '0')}`;
    const weekEndStr = `${selectedWeek.end.getFullYear()}-${String(selectedWeek.end.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.end.getDate()).padStart(2, '0')}`;

    console.log('Validation check:', inputDateStr, weekStartStr, weekEndStr);

    if (inputDateStr < weekStartStr || inputDateStr > weekEndStr) {
        dateInput.classList.add('validation-error');
        console.log('Validation error on modal date:', inputDateStr, weekStartStr, weekEndStr);
        showValidationMessage(dateInput, 'Please select a date within the specified week only.');
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

function syncAndValidateModalDate() {
    if (!weekOptionsReady || !window.weekOptions || window.weekOptions.length === 0) {
        return; // Wait karo, abhi week load nahi hua
    }

    const modalDateInput = document.getElementById("modalInput1");
    if (!modalDateInput) return;

    // Current row ka section find karo
    if (!currentRow) return;
    const section = currentRow.closest(".timesheet-section");
    if (!section) return;

    const weekSelect = section.querySelector('select[id^="weekPeriod_"]');
    if (!weekSelect || !weekSelect.value) return;

    const selectedWeek = window.weekOptions.find(w => w.value === weekSelect.value);
    if (!selectedWeek || !selectedWeek.start || !selectedWeek.end) return;

    const start = new Date(selectedWeek.start).toISOString().split("T")[0];
    const end = new Date(selectedWeek.end).toISOString().split("T")[0];

    // Set min/max
    modalDateInput.min = start;
    modalDateInput.max = end;

    // Agar date week ke bahar hai → auto-correct
    if (!modalDateInput.value || modalDateInput.value < start || modalDateInput.value > end) {
        modalDateInput.value = start;
        showPopup(`Date auto-corrected to valid week: ${formatDate(start)}`, false);
    }

    // Red border hatao agar thi
    modalDateInput.style.border = "";
}



function updateWeekDateLimits(sectionId) {
    const section = document.getElementById(sectionId);
    const weekSelect = section.querySelector(".week-period select");
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value);

    if (!selectedWeek) return;

    const weekStart = formatDate(selectedWeek.start);
    const weekEnd = formatDate(selectedWeek.end);

    const rows = section.querySelectorAll(".date-field");

    rows.forEach(input => {
        input.setAttribute("min", weekStart);
        input.setAttribute("max", weekEnd);

        if (!input.value || input.value < weekStart || input.value > weekEnd) {
            input.value = weekStart; // FORCE FIRST DATE
        }
    });
}

function updateModalWeekLimits(sectionId) {
    const section = document.getElementById(sectionId);
    const weekSelect = section.querySelector(".week-period select");
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value);

    const modal = document.getElementById("modalOverlay");
    const input = modal.querySelector("#modalInput1");

    const weekStart = formatDate(selectedWeek.start);
    const weekEnd = formatDate(selectedWeek.end);

    input.setAttribute("min", weekStart);
    input.setAttribute("max", weekEnd);

    if (!input.value || input.value < weekStart || input.value > weekEnd) {
        input.value = weekStart;
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

function validateDate(input) {
    if (!input) return;

    const section = input.closest(".timesheet-section") || document.getElementById("modalOverlay");
    if (!section) return;

    const weekSelect = section.querySelector(".week-period select");
    if (!weekSelect) return;

    const week = weekOptions.find(w => w.value === weekSelect.value);
    if (!week) return;

    const start = formatDate(new Date(week.start));
    const end = formatDate(new Date(week.end));

    input.setAttribute("min", start);
    input.setAttribute("max", end);

    if (input.value < start || input.value > end) {
        showPopup(`Please select a date within ${start} - ${end}`, true);
        input.classList.add("validation-error");
        input.value = start;
    } else {
        input.classList.remove("validation-error");
    }
}




async function handleExcelUpload(event) {
    console.log("Excel upload initiated");
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async function (e) {
        try {
            const data = new Uint8Array(e.target.result);
            const workbook = XLSX.read(data, { type: 'array' });
            const sheetName = workbook.SheetNames[0];
            const sheet = workbook.Sheets[sheetName];
            const jsonData = XLSX.utils.sheet_to_json(sheet, { defval: '' });

            if (!jsonData || jsonData.length === 0) {
                showPopup('Excel file is empty.', true);
                return;
            }

            // ✅ Required columns to validate
            const requiredColumns = [
                'Employee ID', 'Employee Name', 'Designation', 'Gender', 'Partner',
                'Reporting Manager', 'Week Period', 'Date', 'Location of Work',
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

            // ✅ Convert Excel data into API format
            const timesheetData = jsonData.map(row => ({
                employeeId: row['Employee ID'] || '',
                employeeName: row['Employee Name'] || '',
                designation: row['Designation'] || '',
                gender: row['Gender'] || '',
                partner: row['Partner'] || '',
                reportingManager: row['Reporting Manager'] || '',
                weekPeriod: row['Week Period'] || '',
                date: row['Date'] || '',
                location: row['Location of Work'] || '',
                projectStartTime: row['Project Start Time'] || '',
                projectEndTime: row['Project End Time'] || '',
                punchIn: row['Punch In'] || '',
                punchOut: row['Punch Out'] || '',
                client: row['Client'] || '',
                project: row['Project'] || '',
                projectCode: row['Project Code'] || '',
                reportingManagerEntry: row['Reporting Manager Entry'] || '',
                activity: row['Activity'] || '',
                projectHours: row['Project Hours'] || '',
                workingHours: row['Working Hours'] || '',
                billable: row['Billable'] || '',
                remarks: row['Remarks'] || '',
                hits: row['3 HITS'] || '',
                misses: row['3 MISSES'] || '',
                feedback_hr: row['FEEDBACK FOR HR'] || '',
                feedback_it: row['FEEDBACK FOR IT'] || '',
                feedback_crm: row['FEEDBACK FOR CRM'] || '',
                feedback_others: row['FEEDBACK FOR OTHERS'] || '',
                totalHours: row['Total Hours'] || '0.00',
                totalBillableHours: row['Total Billable Hours'] || '0.00',
                totalNonBillableHours: row['Total Non-Billable Hours'] || '0.00'
            }));

            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_URL}/save_timesheets`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify(timesheetData)
            });

            hideLoading();

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to upload Excel data.');
            }

            const result = await response.json();
            showPopup('Excel uploaded and saved successfully!');
            setTimeout(() => window.location.reload(), 2000);

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


/* End of file */
