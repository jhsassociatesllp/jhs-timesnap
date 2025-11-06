/* script.js - cleaned (punchIn/punchOut removed) */
console.log("✅ script.js loaded successfully");

let sectionCount = 0;
let employeeData = [];
let clientData = [];
let weekOptions = [];
let loggedInEmployeeId = localStorage.getItem("loggedInEmployeeId") || "";
const API_URL = "http://localhost:8000";
let copiedData = null; // for copy/paste row
let currentRow = null; // used by modal if present
let isEditingHistory = false;
let currentEntryId = null;

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

// Helpers
const getHeaders = () => {
  const token =
    localStorage.getItem("access_token") ||
    localStorage.getItem("token") ||
    sessionStorage.getItem("token");
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
};

async function checkPARStatus() {
  try {
    const res = await fetch(`${API_URL}/get-par-current-status`);
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

document.addEventListener("DOMContentLoaded", async () => {
  const token = localStorage.getItem("access_token");
  if (!token) {
    window.location.href = "/static/login.html";
    return;
  }

  // verify session
  try {
    const res = await fetch("/verify_session", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("loggedInEmployeeId");
      window.location.href = "/static/login.html";
      return;
    }
  } catch (err) {
    console.error("Session verify failed:", err);
    localStorage.removeItem("access_token");
    localStorage.removeItem("loggedInEmployeeId");
    window.location.href = "/static/login.html";
    return;
  }

  showLoading("Fetching initial data...");
  try {
    employeeData = await safeFetchJson("/employees");
    clientData = await safeFetchJson("/clients");
    populateEmployeeInfo();
    addWeekSection();
    await checkUserRole();
    showSection("timesheet");
  } catch (err) {
    console.error("Init error:", err);
    showPopup("Failed to initialize data. See console.", true);
  } finally {
    hideLoading();
  }
});

async function safeFetchJson(endpoint) {
  try {
    const res = await fetch(`${API_URL}${endpoint}`, { headers: getHeaders() });
    if (!res.ok) {
      console.warn(`Fetch ${endpoint} returned ${res.status}`);
      return [];
    }
    return await res.json();
  } catch (err) {
    console.error(`Error fetching ${endpoint}:`, err);
    return [];
  }
}

/* Payroll 21→20 window utilities */
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
  const months = [
    "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"
  ];
  const output = [];
  let weekNum = 1;
  let ws = new Date(start);

  while (ws <= end) {
    const we = new Date(ws);
    we.setDate(ws.getDate() + (6 - ((ws.getDay() + 6) % 7))); // up to Sunday
    if (we > end) we.setTime(end.getTime());

    const wsDay = String(ws.getDate()).padStart(2, "0");
    const weDay = String(we.getDate()).padStart(2, "0");
    const value = `${wsDay}/${ws.getMonth()+1}/${ws.getFullYear()} to ${weDay}/${we.getMonth()+1}/${we.getFullYear()}`;
    const text = `Week ${weekNum} (${wsDay} ${months[ws.getMonth()]} - ${weDay} ${months[we.getMonth()]})`;

    output.push({ value, text, start: new Date(ws), end: new Date(we) });

    ws = new Date(we);
    ws.setDate(ws.getDate() + 1); // next Monday
    weekNum++;
  }
  return output;
}

/* initialize weekOptions automatically from payroll window */
(function initWeekOptions() {
  const { start, end } = getPayrollWindow();
  window.weekOptions = generateWeekOptions(start, end);
  console.log(`✅ Payroll Period: ${start.toDateString()} → ${end.toDateString()}`);
  console.log(`📅 Total Weeks: ${window.weekOptions.length}`);
})();

/* add week section (UI) */
// function addWeekSection() {
//   if (typeof sectionCount === "undefined") window.sectionCount = 0;
//   sectionCount++;

//   const sectionsDiv = document.getElementById("timesheetSections");
//   if (!sectionsDiv) {
//     console.error("❌ timesheetSections container not found");
//     return;
//   }

//   const sectionId = `section_${sectionCount}`;
//   const section = document.createElement("div");
//   section.className = "timesheet-section";
//   section.id = sectionId;

//   const weekDiv = document.createElement("div");
//   weekDiv.className = "week-period form-group";
//   weekDiv.innerHTML = `<label>Week Period ${sectionCount}</label>`;

//   const select = document.createElement("select");
//   select.id = `weekPeriod_${sectionCount}`;
//   select.className = "form-control";
//   select.onchange = () => {
//     if (typeof updateSummary === "function") updateSummary();
//     if (typeof updateExistingRowDates === "function")
//       updateExistingRowDates(sectionId);
//   };

//   if (window.weekOptions && window.weekOptions.length > 0) {
//     window.weekOptions.forEach((opt) => {
//       const o = document.createElement("option");
//       o.value = opt.value;
//       o.textContent = opt.text;
//       select.appendChild(o);
//     });
//     select.value = window.weekOptions[0].value;
//   } else {
//     const o = document.createElement("option");
//     o.value = "";
//     o.textContent = "No weeks available";
//     select.appendChild(o);
//   }
//   weekDiv.appendChild(select);

//   // Delete week button
//   const delBtn = document.createElement("button");
//   delBtn.className = "delete-week-btn";
//   delBtn.textContent = "Delete Week";
//   delBtn.onclick = () => {
//     if (typeof deleteWeekSection === "function") deleteWeekSection(sectionId);
//     else document.getElementById(sectionId)?.remove();
//   };
//   weekDiv.appendChild(delBtn);

//   section.appendChild(weekDiv);

//   // Table skeleton
//   const tableWrapper = document.createElement("div");
//   tableWrapper.className = "table-responsive";
//   tableWrapper.innerHTML = `
//     <table class="timesheet-table">
//       <thead>
//         <tr>
//           <th>S.No</th><th>Add</th><th>Action</th><th>Date</th><th>Location</th>
//           <th>Project Start</th><th>Project End</th><th>Client</th><th>Project</th>
//           <th>Project Code</th><th>Reporting Manager</th><th>Activity</th>
//           <th>Project Hours</th><th>Billable</th><th>Remarks</th><th>Delete</th>
//         </tr>
//       </thead>
//       <tbody id="timesheetBody_${sectionCount}"></tbody>
//     </table>
//   `;
//   section.appendChild(tableWrapper);

//   // Buttons
//   const btnDiv = document.createElement("div");
//   btnDiv.className = "button-container";
//   btnDiv.innerHTML = `
//     <button class="add-row-btn" onclick="addRow('${sectionId}')">+ Add New Entry</button>
//   `;
//   section.appendChild(btnDiv);

//   sectionsDiv.appendChild(section);

//   // Initial row
//   if (typeof addRow === "function") addRow(sectionId);
//   if (typeof updateExistingRowDates === "function")
//     updateExistingRowDates(sectionId);

//   console.log(`✅ Week section ${sectionId} added`);
// }

// function addWeekSection() {
//   if (typeof sectionCount === "undefined") window.sectionCount = 0;
//   sectionCount++;

//   const sectionsDiv = document.getElementById("timesheetSections");
//   if (!sectionsDiv) {
//     console.error("❌ timesheetSections container not found");
//     return;
//   }

//   const sectionId = `section_${sectionCount}`;
//   const section = document.createElement("div");
//   section.className = "timesheet-section";
//   section.id = sectionId;

//   const weekDiv = document.createElement("div");
//   weekDiv.className = "week-period form-group";
//   weekDiv.innerHTML = `<label>Week Period ${sectionCount}</label>`;

//   const select = document.createElement("select");
//   select.id = `weekPeriod_${sectionCount}`;
//   select.className = "form-control";
//   select.style.fontWeight = "bold";
//   select.style.color = "#2c3e50" 
//   select.onchange = () => {
//     if (typeof updateSummary === "function") updateSummary();
//     if (typeof updateExistingRowDates === "function")
//       updateExistingRowDates(sectionId);
//   };

//   // ✅ Updated Dropdown Section (Pick data from upper .week-period headings)
//   const weekHeadings = document.querySelectorAll(".week-period:not(.form-group)");
//   select.innerHTML = ""; // clear any existing options

//   if (weekHeadings.length > 0) {
//     weekHeadings.forEach((div, index) => {
//       let text = div.textContent.trim(); // e.g. "Week 1: 21-May-2025 → 27-May-2025"
//       text = text.replace(/-\d{4}/g, ""); // 🧠 Remove year part

//       if (text) {
//         const o = document.createElement("option");
//         o.value = text;
//         o.textContent = text;
//         o.style.fontWeight = "bold"; // ✅ Bold each option text
//         select.appendChild(o);
//       }
//     });

//     // auto-select current week based on today's date
//     const today = new Date();
//     for (let opt of select.options) {
//       const match = opt.text.match(/(\d{2})-(\w{3})/g); // only date & month
//       if (match && match.length === 2) {
//         const [startStr, endStr] = match;
//         const year = today.getFullYear();
//         const start = new Date(`${startStr}-${year}`);
//         const end = new Date(`${endStr}-${year}`);
//         if (today >= start && today <= end) {
//           select.value = opt.value;
//           break;
//         }
//       }
//     }
//   } else {
//     const o = document.createElement("option");
//     o.value = "";
//     o.textContent = "No week headings found";
//     o.style.fontWeight = "bold"; // just in case
//     select.appendChild(o);
//   }

//   weekDiv.appendChild(select);

//   // Delete week button
//   const delBtn = document.createElement("button");
//   delBtn.className = "delete-week-btn";
//   delBtn.textContent = "Delete Week";
//   delBtn.onclick = () => {
//     if (typeof deleteWeekSection === "function") deleteWeekSection(sectionId);
//     else document.getElementById(sectionId)?.remove();
//   };
//   weekDiv.appendChild(delBtn);

//   section.appendChild(weekDiv);

//   // Table skeleton
//   const tableWrapper = document.createElement("div");
//   tableWrapper.className = "table-responsive";
//   tableWrapper.innerHTML = `
//     <table class="timesheet-table">
//       <thead>
//         <tr>
//           <th>S.No</th><th>Add</th><th>Action</th><th>Date</th><th>Location</th>
//           <th>Project Start</th><th>Project End</th><th>Client</th><th>Project</th>
//           <th>Project Code</th><th>Reporting Manager</th><th>Activity</th>
//           <th>Project Hours</th><th>Billable</th><th>Remarks</th><th>Delete</th>
//         </tr>
//       </thead>
//       <tbody id="timesheetBody_${sectionCount}"></tbody>
//     </table>
//   `;
//   section.appendChild(tableWrapper);

//   // Buttons
//   const btnDiv = document.createElement("div");
//   btnDiv.className = "button-container";
//   btnDiv.innerHTML = `
//     <button class="add-row-btn" onclick="addRow('${sectionId}')">+ Add New Entry</button>
//   `;
//   section.appendChild(btnDiv);

//   sectionsDiv.appendChild(section);

//   // Initial row
//   if (typeof addRow === "function") addRow(sectionId);
//   if (typeof updateExistingRowDates === "function")
//     updateExistingRowDates(sectionId);

//   console.log(`✅ Week section ${sectionId} added`);
// }

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
  select.style.fontWeight = "bold"; // bold dropdown text
  select.onchange = () => {
    if (typeof updateSummary === "function") updateSummary();
    if (typeof updateExistingRowDates === "function")
      updateExistingRowDates(sectionId);
  };

  // ✅ Step 1: Collect all week headings before removing them
  if (!window.cachedWeekHeadings) {
    const weekHeadings = document.querySelectorAll(".week-period:not(.form-group)");
    window.cachedWeekHeadings = [];

    weekHeadings.forEach((div) => {
      let text = div.textContent.trim();
      text = text.replace(/-\d{4}/g, ""); // remove year
      if (text) window.cachedWeekHeadings.push(text);
    });

    // ✅ Now safely remove the top week headings
    weekHeadings.forEach(div => div.remove());
  }

  // ✅ Step 2: Populate dropdown using cached headings
  select.innerHTML = "";
  if (window.cachedWeekHeadings && window.cachedWeekHeadings.length > 0) {
    window.cachedWeekHeadings.forEach((text) => {
      const o = document.createElement("option");
      o.value = text;
      o.textContent = text;
      o.style.fontWeight = "bold";
      select.appendChild(o);
    });
  } else {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "No week headings found";
    o.style.fontWeight = "bold";
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
          <th>S.No</th><th>Add</th><th>Action</th><th>Date</th><th>Location</th>
          <th>Project Start</th><th>Project End</th><th>Client</th><th>Project</th>
          <th>Project Code</th><th>Reporting Manager</th><th>Activity</th>
          <th>Project Hours</th><th>Billable</th><th>Remarks</th><th>Delete</th>
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
function updateExistingRowDates(sectionId) {
  const tbody = document.getElementById(
    `timesheetBody_${sectionId.split("_")[1]}`
  );
  if (!tbody) return;

  const weekSelect = document.getElementById(
    `weekPeriod_${sectionId.split("_")[1]}`
  );
  const selectedWeekValue = weekSelect.value;
  const selectedWeek = weekOptions.find(
    (opt) => opt.value === selectedWeekValue
  );

  if (selectedWeek && selectedWeek.start) {
    const weekStart = new Date(selectedWeek.start);
    const defaultDate = `${weekStart.getFullYear()}-${String(
      weekStart.getMonth() + 1
    ).padStart(2, "0")}-${String(weekStart.getDate()).padStart(2, "0")}`;

    const dateInputs = tbody.querySelectorAll(".date-field");
    dateInputs.forEach((dateInput) => {
      const currentDate = new Date(dateInput.value + "T00:00:00");
      const weekStartDate = new Date(weekStart);
      const weekEndDate = new Date(selectedWeek.end);

      if (
        !dateInput.value ||
        currentDate < weekStartDate ||
        currentDate > weekEndDate
      ) {
        dateInput.value = defaultDate;
        validateDate(dateInput);
      }
    });
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
  const weekDates =
    selectedWeek && selectedWeek.start ? getWeekDates(selectedWeek.start) : [];
  const defaultDate =
    specificDate ||
    (weekDates.length ? weekDates[0] : new Date().toISOString().split("T")[0]);

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
    <td class="col-project-start"><input type="time" class="project-start form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
    <td class="col-project-end"><input type="time" class="project-end form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
    <td class="col-client form-input "><input type="text" class="client-field form-input" placeholder="Enter Client"></td>
    <td class="col-project"><input type="text" class="project-field form-input" placeholder="Enter Project"></td>
    <td class="col-project-code"><input type="text" class="project-code form-input" placeholder="Enter Project Code"></td>
    <td class="col-reporting-manager"><input type="text" class="reporting-manager-field form-input" placeholder="Enter Reporting Manager"></td>
    <td>
      <select class="activity-select form-input" required>
        <option value="" disabled selected>Select Activity</option>
        <option value="Hit">Hit</option>
        <option value="Mis">Mis</option>
        <option value="Non">Non</option>
      </select>
    </td>
    <td class="col-project-hours"><input type="number" class="project-hours-field form-input" readonly></td>
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
    let projectStart, projectEnd, startEl, endEl;

    if (isModal) {
      startEl = document.getElementById("modalInput3");
      endEl = document.getElementById("modalInput4");
    } else {
      startEl = rowOrModal.querySelector(".project-start");
      endEl = rowOrModal.querySelector(".project-end");
    }
    projectStart = startEl?.value;
    projectEnd = endEl?.value;

    if (projectStart && projectEnd) {
      const [sh, sm] = projectStart.split(":").map(Number);
      const [eh, em] = projectEnd.split(":").map(Number);
      let s = sh * 60 + sm;
      let e = eh * 60 + em;
      if (e <= s) {
        if (endEl) endEl.classList.add("validation-error");
        showPopup("Project End Time must be later than Start Time", true);
        return false;
      } else {
        if (endEl) endEl.classList.remove("validation-error");
      }
    }
    return true;
  } catch (err) {
    console.warn("validateTimes error", err);
    return true;
  }
}

function validateDate(dateInput) {
  if (!dateInput) return;
  const section = dateInput.closest(".timesheet-section");
  const weekSelect = section?.querySelector(".week-period select");
  const selectedWeek = weekOptions.find(
    (opt) => opt.value === (weekSelect ? weekSelect.value : "")
  );
  if (!selectedWeek) return;

  const inputDateStr = dateInput.value;
  const weekStartStr = `${selectedWeek.start.getFullYear()}-${String(
    selectedWeek.start.getMonth() + 1
  ).padStart(2, "0")}-${String(selectedWeek.start.getDate()).padStart(2, "0")}`;
  const weekEndStr = `${selectedWeek.end.getFullYear()}-${String(
    selectedWeek.end.getMonth() + 1
  ).padStart(2, "0")}-${String(selectedWeek.end.getDate()).padStart(2, "0")}`;

  if (inputDateStr < weekStartStr || inputDateStr > weekEndStr) {
    dateInput.classList.add("validation-error");
    showPopup("Please select a date within the selected week", true);
  } else {
    dateInput.classList.remove("validation-error");
  }

  // Also ensure date is within last 60 days up to yesterday
  const today = new Date();
  const sixtyDaysAgo = new Date(today.getTime() - 60 * 24 * 60 * 60 * 1000);
  const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);
  const minStr = sixtyDaysAgo.toISOString().split("T")[0];
  const maxStr = yesterday.toISOString().split("T")[0];
  if (inputDateStr < minStr || inputDateStr > maxStr) {
    dateInput.classList.add("validation-error");
    showPopup("Date must be within last 60 days up to yesterday", true);
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

/* Modal support (maps modal inputs to row fields) */
function openModal(button) {
  isEditingHistory = false;
  currentRow = button.closest("tr");

  const modalOverlay = document.getElementById("modalOverlay");
  if (!modalOverlay) {
    showPopup("Modal not available in layout. Please add modalOverlay div.", true);
    return;
  }

  modalOverlay.style.display = "flex";

  // collect all fields in row except buttons
  const inputs = Array.from(
    currentRow.querySelectorAll("input, select")
  ).filter(
    (el) =>
      !el.classList.contains("copy-btn") &&
      !el.classList.contains("paste-btn") &&
      !el.classList.contains("delete-btn") &&
      !el.classList.contains("eye-btn")
  );

  // labels (for clarity) - modal fields are modalInput1..modalInput12 as per HTML
  for (let i = 0; i < 12; i++) {
    const input = document.getElementById(`modalInput${i + 1}`) || document.getElementById(`modalInput${i}`);
    if (input && inputs[i]) {
      input.value = inputs[i].value || "";
    }
  }

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
  const projectStart = document.getElementById("modalInput3")?.value;
  const projectEnd = document.getElementById("modalInput4")?.value;
  const projectHoursInput =
    document.getElementById("modalInput10") ||
    document.getElementById("modalInput9");

  if (!projectStart || !projectEnd || !projectHoursInput) return;

  const [sh, sm] = projectStart.split(":").map(Number);
  const [eh, em] = projectEnd.split(":").map(Number);

  let startMinutes = sh * 60 + sm;
  let endMinutes = eh * 60 + em;
  if (endMinutes < startMinutes) endMinutes += 24 * 60;

  const hours = ((endMinutes - startMinutes) / 60).toFixed(2);
  projectHoursInput.value = hours;
}

function saveModalEntry() {
  if (!currentRow) return;

  const modalInputs = document.querySelectorAll(
    "#modalOverlay input, #modalOverlay select"
  );
  const mapping = [
    { modalIndex: 0, rowClass: ".date-field" },
    { modalIndex: 1, rowClass: ".location-select" },
    { modalIndex: 2, rowClass: ".project-start" },
    { modalIndex: 3, rowClass: ".project-end" },
    { modalIndex: 4, rowClass: ".client-field" },
    { modalIndex: 5, rowClass: ".project-field" },
    { modalIndex: 6, rowClass: ".project-code" },
    { modalIndex: 7, rowClass: ".reporting-manager-field" },
    { modalIndex: 8, rowClass: ".activity-select" },
    { modalIndex: 9, rowClass: ".project-hours-field" },
    { modalIndex: 10, rowClass: ".billable-select" },
    { modalIndex: 11, rowClass: ".remarks-field" },
  ];

  mapping.forEach((map) => {
    const modalInput = modalInputs[map.modalIndex];
    const rowField = currentRow.querySelector(map.rowClass);
    if (modalInput && rowField) {
      rowField.value = modalInput.value;
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

/* History loader */
async function loadHistory() {
  if (!loggedInEmployeeId) {
    showPopup("Employee ID not found", true);
    return;
  }

  showLoading("Fetching history...");

  try {
    const res = await fetch(`${API_URL}/timesheets/${loggedInEmployeeId}`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to fetch history: ${res.status}`);

    const data = await res.json();
    const historyContent = document.getElementById("historyContent");
    if (!historyContent) {
      showPopup("History container not found", true);
      hideLoading();
      return;
    }

    historyContent.innerHTML = "";

    const totalEl = document.querySelector(
      ".history-summary .total-hours .value"
    );
    const billEl = document.querySelector(
      ".history-summary .billable-hours .value"
    );
    const nonBillEl = document.querySelector(
      ".history-summary .non-billable-hours .value"
    );

    if (totalEl) totalEl.textContent = (data.totalHours || 0).toFixed(2);
    if (billEl) billEl.textContent = (data.totalBillableHours || 0).toFixed(2);
    if (nonBillEl)
      nonBillEl.textContent = (data.totalNonBillableHours || 0).toFixed(2);

    const entriesList = data.Data || [];
    if (!entriesList.length) {
      historyContent.innerHTML = "<p>No timesheet entries found.</p>";
      hideLoading();
      return;
    }

    const groupedWeeks = {};
    entriesList.forEach((entry) => {
      const week = entry.weekPeriod || "No Week";
      if (!groupedWeeks[week]) groupedWeeks[week] = [];
      groupedWeeks[week].push(entry);
    });

    Object.keys(groupedWeeks).forEach((weekPeriod, index) => {
      const weekEntries = groupedWeeks[weekPeriod];
      const weekDiv = document.createElement("div");
      weekDiv.className = "history-week";
      weekDiv.innerHTML = `<h3>Week Period: ${weekPeriod}</h3>`;

      const tableWrapper = document.createElement("div");
      tableWrapper.className = "table-responsive";
      const table = document.createElement("table");
      table.className = "timesheet-table history-table";
      table.innerHTML = `
        <thead>
          <tr>
            <th>S.No</th>
            <th>Action</th>
            <th>Date</th>
            <th>Location</th>
            <th>Project Start</th>
            <th>Project End</th>
            <th>Client</th>
            <th>Project</th>
            <th>Code</th>
            <th>Reporting Manager</th>
            <th>Activity</th>
            <th>Hours</th>
            <th>Billable</th>
            <th>Remarks</th>
          </tr>
        </thead>
        <tbody></tbody>
      `;

      const tbody = table.querySelector("tbody");

      weekEntries.forEach((entry, idx) => {
        const tr = document.createElement("tr");
        const id = entry.id || "";

        tr.innerHTML = `
          <td>${idx + 1}</td>
          <td style="min-width:160px;">
            <button class="action-btn edit-btn" onclick="editHistoryRow(this, '${id}')"><i class="fas fa-edit"></i> Edit</button>
            <button class="action-btn delete-btn" onclick="deleteHistoryRow(this, '${id}')"><i class="fas fa-trash"></i> Delete</button>
          </td>
          <td>${entry.date || ""}</td>
          <td>${entry.location || ""}</td>
          <td>${entry.projectStartTime || ""}</td>
          <td>${entry.projectEndTime || ""}</td>
          <td>${entry.client || ""}</td>
          <td>${entry.project || ""}</td>
          <td>${entry.projectCode || ""}</td>
          <td>${entry.reportingManagerEntry || ""}</td>
          <td>${entry.activity || ""}</td>
          <td>${entry.projectHours || ""}</td>
          <td>${entry.billable || ""}</td>
          <td>${entry.remarks || ""}</td>
        `;
        tbody.appendChild(tr);
      });

      tableWrapper.appendChild(table);
      weekDiv.appendChild(tableWrapper);

      const fb = weekEntries[0] || {};
      const feedbackHtml = `
        <div class="history-feedback">
          <strong>3 HITS:</strong> ${fb.hits || ""} <br>
          <strong>3 MISSES:</strong> ${fb.misses || ""} <br>
          <strong>Feedback HR:</strong> ${fb.feedback_hr || ""} <br>
          <strong>Feedback IT:</strong> ${fb.feedback_it || ""} <br>
          <strong>Feedback CRM:</strong> ${fb.feedback_crm || ""} <br>
          <strong>Feedback Others:</strong> ${fb.feedback_others || ""}
        </div>
      `;
      weekDiv.insertAdjacentHTML("beforeend", feedbackHtml);

      historyContent.appendChild(weekDiv);
    });

    hideLoading();
  } catch (err) {
    console.error("loadHistory error:", err);
    showPopup("Failed to load history", true);
    hideLoading();
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

/* Save timesheet to backend (collect rows across all sections) */
async function saveDataToMongo() {
  showLoading();
  const employeeId = document.getElementById('employeeId').value.trim();
  if (!employeeId) {
    hideLoading();
    showPopup('Please enter Employee ID', true);
    return;
  }

  const timesheetData = [];
  const employeeDataObj = {
    employeeId: employeeId,
    employeeName: document.getElementById('employeeName').value || '',
    designation: document.getElementById('designation').value || '',
    gender: document.getElementById('gender').value || '',
    partner: document.getElementById('partner').value || '',
    reportingManager: document.getElementById('reportingManager').value || '',
    weekPeriod: '',
    date: '',
    location: '',
    projectStartTime: '',
    projectEndTime: '',
    client: '',
    project: '',
    projectCode: '',
    reportingManagerEntry: '',
    activity: '',
    projectHours: '',
    billable: '',
    remarks: '',
    hits: document.getElementById('hits').value || '',
    misses: document.getElementById('misses').value || '',
    feedback_hr: document.getElementById('feedback_hr').value || '',
    feedback_it: document.getElementById('feedback_it').value || '',
    feedback_crm: document.getElementById('feedback_crm').value || '',
    feedback_others: document.getElementById('feedback_others').value || '',
    totalHours: document.querySelector('.summary-section .total-hours .value').textContent || '0.00',
    totalBillableHours: document.querySelector('.summary-section .billable-hours .value').textContent || '0.00',
    totalNonBillableHours: document.querySelector('.summary-section .non-billable-hours .value').textContent || '0.00'
  };

  const sections = document.querySelectorAll('.timesheet-section');
  let hasInvalidDates = false;
  let hasMissingFields = false;
  let errorMessages = [];

  sections.forEach(section => {
    const weekPeriod = section.querySelector('.week-period select').value || '';
    const rows = section.querySelectorAll('tbody tr');
    rows.forEach(row => {
      const inputs = row.querySelectorAll('input, select');
      if (inputs.length < 12) return;
      const dateInput = inputs[0];

      // Validate mandatory fields (updated indexes after removing punch)
      const mandatoryFields = {
        'Project Start Time': inputs[2].value,
        'Project End Time': inputs[3].value,
        'Client': inputs[4].value,
        'Project': inputs[5].value,
        'Project Code': inputs[6].value,
        'Reporting Manager': inputs[7].value,
        'Activity': inputs[8].value
      };

      for (let [fieldName, value] of Object.entries(mandatoryFields)) {
        if (!value || value.trim() === '') {
          hasMissingFields = true;
          errorMessages.push(`Please fill in the ${fieldName} field for the row dated ${dateInput.value || 'N/A'}.`);
        }
      }

      const selectedWeek = weekOptions.find(opt => opt.value === weekPeriod);
      if (selectedWeek) {
        const inputDateStr = dateInput.value;
        const weekStartStr = `${selectedWeek.start.getFullYear()}-${String(selectedWeek.start.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.start.getDate()).padStart(2, '0')}`;
        const weekEndStr = `${selectedWeek.end.getFullYear()}-${String(selectedWeek.end.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.end.getDate()).padStart(2, '0')}`;
        if (inputDateStr < weekStartStr || inputDateStr > weekEndStr) {
          hasInvalidDates = true;
          return;
        }
      }

      const client = inputs[4].value || inputs[4].querySelector('option:checked')?.value || '';
      const project = inputs[5].value;
      const projectCode = inputs[6].value;
      if (!client || !project || !projectCode) {
        hasMissingFields = true;
        errorMessages.push(`Row missing required fields: Client, Project, or Project Code for the row dated ${dateInput.value || 'N/A'}.`);
        return;
      }

      const rowData = {
        employeeId: employeeId,
        employeeName: document.getElementById('employeeName').value || '',
        designation: document.getElementById('designation').value || '',
        gender: document.getElementById('gender').value || '',
        partner: document.getElementById('partner').value || '',
        reportingManager: document.getElementById('reportingManager').value || '',
        weekPeriod: weekPeriod,
        date: inputs[0].value,
        location: inputs[1].value || inputs[1].querySelector('option:checked')?.value,
        projectStartTime: inputs[2].value,
        projectEndTime: inputs[3].value,
        client: client,
        project: project,
        projectCode: projectCode,
        reportingManagerEntry: inputs[7].value || '',
        activity: inputs[8].value,
        projectHours: inputs[9].value,
        billable: inputs[10].value,
        remarks: inputs[11].value,
        hits: document.getElementById('hits').value || '',
        misses: document.getElementById('misses').value || '',
        feedback_hr: document.getElementById('feedback_hr').value || '',
        feedback_it: document.getElementById('feedback_it').value || '',
        feedback_crm: document.getElementById('feedback_crm').value || '',
        feedback_others: document.getElementById('feedback_others').value || '',
        totalHours: document.querySelector('.summary-section .total-hours .value').textContent || '0.00',
        totalBillableHours: document.querySelector('.summary-section .billable-hours .value').textContent || '0.00',
        totalNonBillableHours: document.querySelector('.summary-section .non-billable-hours .value').textContent || '0.00'
      };
      timesheetData.push(rowData);
    });
  });

  if (hasInvalidDates) {
    hideLoading();
    showPopup('Please correct all dates to be within their respective week periods.', true);
    return;
  }

  if (hasMissingFields) {
    hideLoading();
    showPopup(errorMessages.join('\n'), true);
    return;
  }

  if (timesheetData.length === 0) {
    timesheetData.push(employeeDataObj);
  }

  try {
    const response = await fetch(`${API_URL}/save_timesheets`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify(timesheetData)
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(`Failed to save data: ${errorData.detail || 'Unknown error'}`);
    }

    const result = await response.json();
    hideLoading();
    showPopup('Timesheet saved successfully!');
    setTimeout(() => {
      window.location.reload();
    }, 1500);
  } catch (error) {
    console.error('Error saving data:', error);
    hideLoading();
    showPopup(`Failed to save timesheet: ${error.message}`, true);
  }
}

/* Export functions */
// function exportTimesheetToExcel() {
//   try {
//     const rows = [];
//     document
//       .querySelectorAll(".timesheet-section tbody tr")
//       .forEach((tr, idx) => {
//         rows.push({
//           "S.No": idx + 1,
//           Date: tr.querySelector(".date-field")?.value || "",
//           Location: tr.querySelector(".location-select")?.value || "",
//           "Project Start": tr.querySelector(".project-start")?.value || "",
//           "Project End": tr.querySelector(".project-end")?.value || "",
//           Client: tr.querySelector(".client-field")?.value || "",
//           Project: tr.querySelector(".project-field")?.value || "",
//           "Project Code": tr.querySelector(".project-code")?.value || "",
//           "Reporting Manager":
//             tr.querySelector(".reporting-manager-field")?.value || "",
//           Activity: tr.querySelector(".activity-select")?.value || "",
//           "Project Hours":
//             tr.querySelector(".project-hours-field")?.value || "",
//           Billable: tr.querySelector(".billable-select")?.value || "",
//           Remarks: tr.querySelector(".remarks-field")?.value || "",
//         });
//       });
//     const ws = XLSX.utils.json_to_sheet(rows);
//     const wb = XLSX.utils.book_new();
//     XLSX.utils.book_append_sheet(wb, ws, "Timesheet");
//     const name = `Timesheet_${
//       document.getElementById("employeeId")?.value || "user"
//     }_${new Date().toISOString().split("T")[0]}.xlsx`;
//     XLSX.writeFile(wb, name);
//     showPopup("Exported timesheet to Excel");
//   } catch (err) {
//     console.error("exportTimesheetToExcel error", err);
//     showPopup("Failed to export", true);
//   }
// }

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
//         Activity: tr.querySelector(".activity-select")?.value || "",
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

//     // ✅ 4️⃣ Prepare data for export (single sheet)
//     let rowCursor = 0;
//     const wsData = [];

//     // Section 1: Employee Details
//     wsData[rowCursor++] = ["Employee Details"];
//     Object.entries(empDetails).forEach(([key, val]) => {
//       wsData[rowCursor++] = [key, val];
//     });
//     rowCursor++; // blank line

//     // Section 2: Timesheet Data
//     wsData[rowCursor++] = ["Timesheet Data"];
//     const headers = Object.keys(tableRows[0] || {});
//     wsData[rowCursor++] = headers;

//     tableRows.forEach((row) => {
//       wsData[rowCursor++] = headers.map((h) => row[h]);
//     });

//     rowCursor++; // blank line

//     // Section 3: Employee Feedback
//     wsData[rowCursor++] = ["Employee Feedback"];
//     Object.entries(feedbackDetails).forEach(([key, val]) => {
//       wsData[rowCursor++] = [key, val];
//     });

//     // ✅ 5️⃣ Convert to worksheet
//     const ws = XLSX.utils.aoa_to_sheet(wsData);

//     // ✅ 6️⃣ Basic Styling (bold headings + borders)
//     const range = XLSX.utils.decode_range(ws["!ref"]);

//     for (let R = range.s.r; R <= range.e.r; ++R) {
//       for (let C = range.s.c; C <= range.e.c; ++C) {
//         const cellRef = XLSX.utils.encode_cell({ r: R, c: C });
//         if (!ws[cellRef]) continue;

//         // add borders to all cells
//         ws[cellRef].s = {
//           border: {
//             top: { style: "thin", color: { rgb: "999999" } },
//             bottom: { style: "thin", color: { rgb: "999999" } },
//             left: { style: "thin", color: { rgb: "999999" } },
//             right: { style: "thin", color: { rgb: "999999" } },
//           },
//         };

//         // make section titles bold and larger
//         const cellValue = ws[cellRef].v;
//         if (
//           cellValue === "Employee Details" ||
//           cellValue === "Timesheet Data" ||
//           cellValue === "Employee Feedback"
//         ) {
//           ws[cellRef].s = {
//             font: { bold: true, sz: 14, color: { rgb: "1F4E78" } },
//           };
//         }

//         // make header row bold
//         if (R === 8 || cellValue === "S.No") {
//           ws[cellRef].s = {
//             font: { bold: true, color: { rgb: "000000" } },
//             border: {
//               top: { style: "thin", color: { rgb: "666666" } },
//               bottom: { style: "thin", color: { rgb: "666666" } },
//               left: { style: "thin", color: { rgb: "666666" } },
//               right: { style: "thin", color: { rgb: "666666" } },
//             },
//             fill: { fgColor: { rgb: "E2EFDA" } },
//           };
//         }
//       }
//     }

//     // ✅ 7️⃣ Auto column width
//     const colWidths = [];
//     const dataRows = wsData.filter(Boolean);
//     for (let i = 0; i < (dataRows[0]?.length || 0); i++) {
//       const maxLen = dataRows.reduce(
//         (max, row) => Math.max(max, (row[i] ? String(row[i]).length : 0)),
//         10
//       );
//       colWidths.push({ wch: maxLen + 2 });
//     }
//     ws["!cols"] = colWidths;

//     // ✅ 8️⃣ Save file
//     const wb = XLSX.utils.book_new();
//     XLSX.utils.book_append_sheet(wb, ws, "Timesheet Report");

//     const fileName = `Timesheet_${empDetails["Employee ID"] || "user"}_${new Date()
//       .toISOString()
//       .split("T")[0]}.xlsx`;

//     XLSX.writeFile(wb, fileName);

//     showPopup("✅ Timesheet exported successfully with details & feedback!");
//   } catch (err) {
//     console.error("exportTimesheetToExcel error", err);
//     showPopup("❌ Failed to export Excel", true);
//   }
// }

function exportTimesheetToExcel() {
  try {
    // ✅ 1️⃣ Employee Details
    const empDetails = {
      "Employee ID": document.getElementById("employeeId")?.value || "",
      "Employee Name": document.getElementById("employeeName")?.value || "",
      "Designation": document.getElementById("designation")?.value || "",
      "Gender": document.getElementById("gender")?.value || "",
      "Partner": document.getElementById("partner")?.value || "",
      "Reporting Manager": document.getElementById("reportingManager")?.value || "",
    };

    // ✅ 2️⃣ Timesheet Table Data
    const tableRows = [];
    document.querySelectorAll(".timesheet-section tbody tr").forEach((tr, idx) => {
      tableRows.push({
        "S.No": idx + 1,
        Date: tr.querySelector(".date-field")?.value || "",
        Location: tr.querySelector(".location-select")?.value || "",
        "Project Start": tr.querySelector(".project-start")?.value || "",
        "Project End": tr.querySelector(".project-end")?.value || "",
        Client: tr.querySelector(".client-field")?.value || "",
        Project: tr.querySelector(".project-field")?.value || "",
        "Project Code": tr.querySelector(".project-code")?.value || "",
        "Reporting Manager (Entry)": tr.querySelector(".reporting-manager-field")?.value || "",
        Activity: tr.querySelector(".activity-select")?.value || "",
        "Project Hours": tr.querySelector(".project-hours-field")?.value || "",
        Billable: tr.querySelector(".billable-select")?.value || "",
        Remarks: tr.querySelector(".remarks-field")?.value || "",
      });
    });

    // ✅ 3️⃣ Feedback Section
    const feedbackDetails = {
      "3 HITS": document.getElementById("hits")?.value || "",
      "3 MISSES": document.getElementById("misses")?.value || "",
      "Feedback HR": document.getElementById("feedback_hr")?.value || "",
      "Feedback IT": document.getElementById("feedback_it")?.value || "",
      "Feedback CRM": document.getElementById("feedback_crm")?.value || "",
      "Feedback Others": document.getElementById("feedback_others")?.value || "",
    };

    // ✅ 4️⃣ Combine all data row-wise
    const wsData = [];

    // Title Row
    wsData.push(["JHS Timesheet Report"]);
    wsData.push([]);

    // Employee Details (Row-wise)
    wsData.push(["Employee Details"]);
    wsData.push([
      "Employee ID",
      "Employee Name",
      "Designation",
      "Gender",
      "Partner",
      "Reporting Manager",
    ]);
    wsData.push([
      empDetails["Employee ID"],
      empDetails["Employee Name"],
      empDetails["Designation"],
      empDetails["Gender"],
      empDetails["Partner"],
      empDetails["Reporting Manager"],
    ]);

    wsData.push([]);

    // Timesheet Data (Row-wise)
    wsData.push(["Timesheet Data"]);
    const headers = Object.keys(tableRows[0] || {});
    wsData.push(headers);
    tableRows.forEach((row) => {
      wsData.push(headers.map((h) => row[h]));
    });

    wsData.push([]);

    // Feedback (Row-wise)
    wsData.push(["Employee Feedback"]);
    wsData.push([
      "3 HITS",
      "3 MISSES",
      "Feedback HR",
      "Feedback IT",
      "Feedback CRM",
      "Feedback Others",
    ]);
    wsData.push([
      feedbackDetails["3 HITS"],
      feedbackDetails["3 MISSES"],
      feedbackDetails["Feedback HR"],
      feedbackDetails["Feedback IT"],
      feedbackDetails["Feedback CRM"],
      feedbackDetails["Feedback Others"],
    ]);

    // ✅ 5️⃣ Convert to worksheet
    const ws = XLSX.utils.aoa_to_sheet(wsData);

    // ✅ 6️⃣ Merge title row
    const mergeCols = Math.max(...wsData.map((r) => r.length));
    ws["!merges"] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: mergeCols - 1 } }];

    // ✅ 7️⃣ Basic Styling (borders, bold headings, colors)
    const range = XLSX.utils.decode_range(ws["!ref"]);
    for (let R = range.s.r; R <= range.e.r; ++R) {
      for (let C = range.s.c; C <= range.e.c; ++C) {
        const cellRef = XLSX.utils.encode_cell({ r: R, c: C });
        if (!ws[cellRef]) continue;
        const val = ws[cellRef].v;

        // Borders
        ws[cellRef].s = {
          border: {
            top: { style: "thin", color: { rgb: "999999" } },
            bottom: { style: "thin", color: { rgb: "999999" } },
            left: { style: "thin", color: { rgb: "999999" } },
            right: { style: "thin", color: { rgb: "999999" } },
          },
        };

        // Title
        if (val === "JHS Timesheet Report") {
          ws[cellRef].s = {
            font: { bold: true, sz: 16, color: { rgb: "FFFFFF" } },
            alignment: { horizontal: "center" },
            fill: { fgColor: { rgb: "4472C4" } },
          };
        }

        // Section Headings
        if (
          val === "Employee Details" ||
          val === "Timesheet Data" ||
          val === "Employee Feedback"
        ) {
          ws[cellRef].s = {
            font: { bold: true, sz: 14, color: { rgb: "1F4E78" } },
            fill: { fgColor: { rgb: "DDEBF7" } },
          };
        }

        // Header Rows
        if (
          wsData[R - 1] &&
          (wsData[R - 1][0] === "Employee Details" ||
            wsData[R - 1][0] === "Timesheet Data" ||
            wsData[R - 1][0] === "Employee Feedback")
        ) {
          ws[cellRef].s = {
            font: { bold: true },
            fill: { fgColor: { rgb: "E2EFDA" } },
          };
        }
      }
    }

    // ✅ 8️⃣ Auto column width
    const colWidths = [];
    const dataRows = wsData.filter(Boolean);
    for (let i = 0; i < (dataRows[0]?.length || 0); i++) {
      const maxLen = dataRows.reduce(
        (max, row) => Math.max(max, (row[i] ? String(row[i]).length : 0)),
        10
      );
      colWidths.push({ wch: maxLen + 3 });
    }
    ws["!cols"] = colWidths;

    // ✅ 9️⃣ Save file
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Timesheet Report");

    const fileName = `Timesheet_${empDetails["Employee ID"] || "user"}_${new Date()
      .toISOString()
      .split("T")[0]}.xlsx`;

    XLSX.writeFile(wb, fileName);

    showPopup("✅ Timesheet exported successfully (Row-wise layout)!");
  } catch (err) {
    console.error("exportTimesheetToExcel error", err);
    showPopup("❌ Failed to export Excel", true);
  }
}



// async function exportHistoryToExcel() {
//   try {
//     showLoading("Exporting history...");

//     const res = await fetch(`${API_URL}/timesheets/${loggedInEmployeeId}`, {
//       headers: getHeaders(),
//     });
//     if (!res.ok) throw new Error(`Failed to fetch history (${res.status})`);

//     const data = await res.json();
//     const entries = data.Data || [];

//     if (!entries.length) {
//       showPopup("No timesheet data available to export.", true);
//       hideLoading();
//       return;
//     }

//     const grouped = {};
//     entries.forEach((entry) => {
//       const week = entry.weekPeriod || "No Week";
//       if (!grouped[week]) grouped[week] = [];
//       grouped[week].push(entry);
//     });

//     const rows = [];
//     Object.keys(grouped).forEach((weekKey) => {
//       grouped[weekKey].forEach((entry) => {
//         rows.push({
//           "Week Period": weekKey,
//           Date: entry.date || "",
//           Location: entry.location || "",
//           Client: entry.client || "",
//           Project: entry.project || "",
//           "Project Code": entry.projectCode || "",
//           Activity: entry.activity || "",
//           Hours: entry.projectHours || "",
//           Billable: entry.billable || "",
//           Remarks: entry.remarks || "",
//           "3 HITS": entry.hits || "",
//           "3 MISSES": entry.misses || "",
//           "Feedback HR": entry.feedback_hr || "",
//           "Feedback IT": entry.feedback_it || "",
//           "Feedback CRM": entry.feedback_crm || "",
//           "Feedback Others": entry.feedback_others || "",
//         });
//       });
//     });

//     const ws = XLSX.utils.json_to_sheet(rows);
//     const wb = XLSX.utils.book_new();
//     XLSX.utils.book_append_sheet(wb, ws, "History");

//     const fileName = `History_${loggedInEmployeeId}_${new Date().toISOString().split("T")[0]}.xlsx`;
//     XLSX.writeFile(wb, fileName);

//     showPopup("History exported successfully!");
//   } catch (err) {
//     console.error("exportHistoryToExcel error:", err);
//     showPopup("Failed to export history: " + err.message, true);
//   } finally {
//     hideLoading();
//   }
// }

async function exportHistoryToExcel() {
  try {
    showLoading("Exporting history...");

    const res = await fetch(`${API_URL}/timesheets/${loggedInEmployeeId}`, {
      headers: getHeaders(),
    });
    if (!res.ok) throw new Error(`Failed to fetch history (${res.status})`);

    const data = await res.json();
    const entries = data.Data || [];

    if (!entries.length) {
      showPopup("No timesheet data available to export.", true);
      hideLoading();
      return;
    }

    // ✅ 1️⃣ Employee Details
    const empDetails = {
      "Employee ID": loggedInEmployeeId,
      "Employee Name": entries[0]?.employeeName || "",
      "Designation": entries[0]?.designation || "",
      "Gender": entries[0]?.gender || "",
      "Partner": entries[0]?.partner || "",
      "Reporting Manager": entries[0]?.reportingManager || "",
    };

    // ✅ 2️⃣ Summary
    const summaryDetails = {
      "Total Hours": (data.totalHours || 0).toFixed(2),
      "Billable Hours": (data.totalBillableHours || 0).toFixed(2),
      "Non-Billable Hours": (data.totalNonBillableHours || 0).toFixed(2),
    };

    // ✅ 3️⃣ Timesheet History Data
    const tableRows = entries.map((entry, idx) => ({
      "S.No": idx + 1,
      Date: entry.date || "",
      "Week Period": entry.weekPeriod || "",
      Location: entry.location || "",
      Client: entry.client || "",
      Project: entry.project || "",
      "Project Code": entry.projectCode || "",
      Activity: entry.activity || "",
      Hours: entry.projectHours || "",
      Billable: entry.billable || "",
      Remarks: entry.remarks || "",
    }));

    // ✅ 4️⃣ Feedback Section
    const feedbackDetails = {
      "3 HITS": entries[0]?.hits || "",
      "3 MISSES": entries[0]?.misses || "",
      "Feedback HR": entries[0]?.feedback_hr || "",
      "Feedback IT": entries[0]?.feedback_it || "",
      "Feedback CRM": entries[0]?.feedback_crm || "",
      "Feedback Others": entries[0]?.feedback_others || "",
    };

    // ✅ 5️⃣ Combine all sections (row-wise format)
    const wsData = [];

    // Report Title
    wsData.push(["JHS Timesheet History Report"]);
    wsData.push([]);

    // Employee Details
    wsData.push(["Employee Details"]);
    wsData.push([
      "Employee ID",
      "Employee Name",
      "Designation",
      "Gender",
      "Partner",
      "Reporting Manager",
    ]);
    wsData.push([
      empDetails["Employee ID"],
      empDetails["Employee Name"],
      empDetails["Designation"],
      empDetails["Gender"],
      empDetails["Partner"],
      empDetails["Reporting Manager"],
    ]);

    wsData.push([]);

    // Summary (Row-wise)
    wsData.push(["Summary"]);
    wsData.push(["Total Hours", "Billable Hours", "Non-Billable Hours"]);
    wsData.push([
      summaryDetails["Total Hours"],
      summaryDetails["Billable Hours"],
      summaryDetails["Non-Billable Hours"],
    ]);

    wsData.push([]);

    // Timesheet History (Row-wise)
    wsData.push(["Timesheet History"]);
    const headers = Object.keys(tableRows[0] || {});
    wsData.push(headers);
    tableRows.forEach((row) => wsData.push(headers.map((h) => row[h])));

    wsData.push([]);

    // Feedback (Row-wise)
    wsData.push(["Employee Feedback"]);
    wsData.push([
      "3 HITS",
      "3 MISSES",
      "Feedback HR",
      "Feedback IT",
      "Feedback CRM",
      "Feedback Others",
    ]);
    wsData.push([
      feedbackDetails["3 HITS"],
      feedbackDetails["3 MISSES"],
      feedbackDetails["Feedback HR"],
      feedbackDetails["Feedback IT"],
      feedbackDetails["Feedback CRM"],
      feedbackDetails["Feedback Others"],
    ]);

    // ✅ 6️⃣ Convert to worksheet
    const ws = XLSX.utils.aoa_to_sheet(wsData);

    // ✅ 7️⃣ Merge title row
    const mergeCols = Math.max(...wsData.map((r) => r.length));
    ws["!merges"] = [{ s: { r: 0, c: 0 }, e: { r: 0, c: mergeCols - 1 } }];

    // ✅ 8️⃣ Apply styling (borders, colors, bold)
    const range = XLSX.utils.decode_range(ws["!ref"]);
    for (let R = range.s.r; R <= range.e.r; ++R) {
      for (let C = range.s.c; C <= range.e.c; ++C) {
        const cellRef = XLSX.utils.encode_cell({ r: R, c: C });
        if (!ws[cellRef]) continue;
        const val = ws[cellRef].v;

        // Add borders
        ws[cellRef].s = {
          border: {
            top: { style: "thin", color: { rgb: "999999" } },
            bottom: { style: "thin", color: { rgb: "999999" } },
            left: { style: "thin", color: { rgb: "999999" } },
            right: { style: "thin", color: { rgb: "999999" } },
          },
        };

        // Title
        if (val === "JHS Timesheet History Report") {
          ws[cellRef].s = {
            font: { bold: true, sz: 16, color: { rgb: "FFFFFF" } },
            alignment: { horizontal: "center" },
            fill: { fgColor: { rgb: "4472C4" } },
          };
        }

        // Section Headings
        if (
          val === "Employee Details" ||
          val === "Timesheet History" ||
          val === "Employee Feedback" ||
          val === "Summary"
        ) {
          ws[cellRef].s = {
            font: { bold: true, sz: 14, color: { rgb: "1F4E78" } },
            fill: { fgColor: { rgb: "DDEBF7" } },
          };
        }

        // Header Rows
        if (
          wsData[R - 1] &&
          (wsData[R - 1][0] === "Employee Details" ||
            wsData[R - 1][0] === "Summary" ||
            wsData[R - 1][0] === "Timesheet History" ||
            wsData[R - 1][0] === "Employee Feedback")
        ) {
          ws[cellRef].s = {
            font: { bold: true },
            fill: { fgColor: { rgb: "E2EFDA" } },
          };
        }
      }
    }

    // ✅ 9️⃣ Auto column width
    const colWidths = [];
    const dataRows = wsData.filter(Boolean);
    for (let i = 0; i < (dataRows[0]?.length || 0); i++) {
      const maxLen = dataRows.reduce(
        (max, row) => Math.max(max, (row[i] ? String(row[i]).length : 0)),
        10
      );
      colWidths.push({ wch: maxLen + 3 });
    }
    ws["!cols"] = colWidths;

    // ✅ 🔟 Save Excel file
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "History Report");

    const fileName = `History_${loggedInEmployeeId}_${new Date()
      .toISOString()
      .split("T")[0]}.xlsx`;

    XLSX.writeFile(wb, fileName);

    hideLoading();
    showPopup("✅ History exported successfully (Row-wise format)!");
  } catch (err) {
    console.error("exportHistoryToExcel error:", err);
    hideLoading();
    showPopup("❌ Failed to export history: " + err.message, true);
  }
}



/* Manager panel: role check & lists */
// async function checkUserRole() {
//   try {
//     if (!loggedInEmployeeId) return;
//     const res = await fetch(
//       `${API_URL}/check_reporting_manager/${loggedInEmployeeId}`,
//       { headers: getHeaders() }
//     );
//     if (!res.ok) {
//       console.warn("Role check failed", res.status);
//       return;
//     }
//     const js = await res.json();
//     const managerButtons = document.querySelectorAll(".manager-only");
//     managerButtons.forEach((btn) => {
//       btn.style.display = js.isManager ? "inline-block" : "none";
//     });
//   } catch (err) {
//     console.error("checkUserRole error", err);
//   }
// }

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
async function handleExcelUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  try {
    showPopup("Uploading Excel data...", false);

    const reader = new FileReader();
    reader.onload = async function (e) {
      const data = new Uint8Array(e.target.result);
      const workbook = XLSX.read(data, { type: "array" });

      const firstSheet = workbook.SheetNames[0];
      const worksheet = workbook.Sheets[firstSheet];
      const jsonData = XLSX.utils.sheet_to_json(worksheet, { defval: "" });

      console.log("✅ Parsed Excel Data:", jsonData);

      const response = await fetch(`${API_URL}/upload_excel_timesheet`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getHeaders()
        },
        body: JSON.stringify({ entries: jsonData }),
      });

      if (!response.ok) throw new Error("Upload failed!");

      const result = await response.json();
      console.log("✅ Server response:", result);

      if (typeof loadTimesheetHistory === "function") {
        await loadTimesheetHistory();
      }

      showPopup("Excel uploaded successfully!");
    };

    reader.readAsArrayBuffer(file);
  } catch (error) {
    console.error("❌ Error uploading Excel:", error);
    showPopup("Failed to upload Excel file!", true);
  }
}

// ✅ Payroll se week periods auto generate karne ka code

async function fetchCurrentPayroll() {
  try {
    const res = await fetch("/get-current-payroll");
    const data = await res.json();

    if (data.start_date && data.end_date) {
      generateWeekPeriods(data.start_date, data.end_date);
    } else {
      console.warn("⚠️ Payroll data not found in DB");
    }
  } catch (err) {
    console.error("Error fetching payroll:", err);
  }
}

function generateWeekPeriods(startDateStr, endDateStr) {
  const start = new Date(startDateStr);
  const end = new Date(endDateStr);

  const weekContainer = document.getElementById("timesheetSections");
  if (!weekContainer) return;
  weekContainer.innerHTML = ""; // clear old weeks

  let weekCount = 1;
  let current = new Date(start);

  while (current <= end) {
    const weekStart = new Date(current);
    const weekEnd = new Date(current);
    weekEnd.setDate(weekEnd.getDate() + 6); // 7 days per week

    if (weekEnd > end) weekEnd.setTime(end.getTime());

    const weekHTML = `
      <div class="week-period">
        <h4>Week ${weekCount}: ${formatDate(weekStart)} → ${formatDate(weekEnd)}</h4>
      </div>
    `;
    weekContainer.insertAdjacentHTML("beforeend", weekHTML);

    current.setDate(current.getDate() + 7);
    weekCount++;
  }
}

function formatDate(dateObj) {
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const d = String(dateObj.getDate()).padStart(2, "0");
  return `${d}-${months[dateObj.getMonth()]}-${dateObj.getFullYear()}`;
}

// ✅ Load weeks automatically when timesheet opens
window.addEventListener("load", fetchCurrentPayroll);


/* End of file */
