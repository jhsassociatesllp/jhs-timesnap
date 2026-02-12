
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
// 1. ADD THIS GLOBAL VARIABLE (after line with historyEntries)
let employeeProjects = {
  clients: [],
  projects: [],
  project_codes: []
};

// Ye variable bana de top me
let weekOptionsReady = false;
window.weekOptions = [];

async function loadEmployeeProjects() {
  if (!loggedInEmployeeId) return;
  
  try {
    const res = await fetch(`${API_URL}/get_employee_projects/${loggedInEmployeeId}`, {
      headers: getHeaders()
    });
    
    if (res.ok) {
      employeeProjects = await res.json();
      console.log("✅ Employee projects loaded:", employeeProjects);
       console.log("📊 Clients:", employeeProjects.clients);
  console.log("📊 Projects by client:", employeeProjects.projects_by_client);
    } else {
      console.warn("Failed to load employee projects");
    }
  } catch (err) {
    console.error("Error loading employee projects:", err);
  }
}

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
  // setTimeout(() => {
  //   dv.style.display = "none";
  // }, 5000);
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
    console.log(`API URL: ${API_URL}`)
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

    // ✅ NEW: Load employee projects
    await loadEmployeeProjects();

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


function createSmartDropdown(type, container, currentValue = "", currentClient = "") {
  // type = "client", "project", or "project_code"
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
  
  const select = document.createElement("select");
  select.className = `${type}-field form-input smart-dropdown`;
  select.style.width = "100%";
  
  // Add default option
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = `Select ${type.replace('_', ' ')}`;
  select.appendChild(defaultOpt);
  
  // Add filtered options
  options.forEach(opt => {
    const option = document.createElement("option");
    option.value = opt;
    option.textContent = opt;
    if (opt === currentValue) option.selected = true;
    select.appendChild(option);
  });
  
  // Add "Type here" option only for client and project
  if (type !== "project_code") {
    const typeOption = document.createElement("option");
    typeOption.value = "__TYPE_HERE__";
    typeOption.textContent = "✏️ Type here (custom entry)";
    typeOption.style.fontStyle = "italic";
    typeOption.style.color = "#666";
    select.appendChild(typeOption);
  }
  
  // Handle selection changes
  // select.addEventListener("change", function() {
  //   const row = this.closest("tr");
    
  //   if (this.value === "__TYPE_HERE__") {
  //     // Replace with input field
  //     const input = document.createElement("input");
  //     input.type = "text";
  //     input.className = `${type}-field form-input`;
  //     input.placeholder = `Enter ${type.replace('_', ' ')}`;
  //     input.value = currentValue;
  //     input.style.width = "calc(100% - 35px)";
      
  //     // Add button to go back to dropdown
  //     const backBtn = document.createElement("button");
  //     backBtn.className = "back-to-dropdown-btn";
  //     backBtn.innerHTML = '<i class="fas fa-list"></i>';
  //     backBtn.title = "Back to dropdown";
  //     backBtn.type = "button";
  //     backBtn.style.marginLeft = "5px";
  //     backBtn.style.padding = "6px 10px";
  //     backBtn.style.cursor = "pointer";
  //     // backBtn.onclick = () => {
  //     //   const clientValue = type === "project" ? getFieldValue(row, '.col-client') : "";
  //     //   const newDropdown = createSmartDropdown(type, container, input.value, clientValue);
  //     //   container.innerHTML = "";
  //     //   container.appendChild(newDropdown);
  //     // };

  //    backBtn.onclick = () => {
  //     const isModal = container.closest("#modalOverlay") !== null;
  //     let clientValue = "";

  //     if (type === "project") {
  //         if (isModal) {
  //             const clientSelect = document.querySelector("#modalClientContainer select");
  //             clientValue = clientSelect?.value || "";
  //         } else {
  //             const row = container.closest("tr");
  //             clientValue = row ? getFieldValue(row, '.col-client') : "";
  //         }
  //     }

  //     const newDropdown = createSmartDropdown(type, container, input.value || "", clientValue);
  //     container.innerHTML = "";
  //     container.appendChild(newDropdown);

  //     // ────────────────────────────────────────────────
  //     // Reset project code field (table OR modal)
  //     // ────────────────────────────────────────────────
  //     let codeContainer, codeElement;

  //     if (isModal) {
  //         codeContainer = document.getElementById("modalProjectCodeContainer");
  //         codeElement = document.getElementById("modalProjectCodeInput");
  //     } else {
  //         const row = container.closest("tr");
  //         if (row) {
  //             codeContainer = row.querySelector(".col-project-code");
  //             codeElement = codeContainer?.querySelector("input");
  //         }
  //     }

  //     if (codeContainer) {
  //         codeContainer.innerHTML = "";

  //         const currentProjectVal = newDropdown.value;

  //         const inputElem = document.createElement("input");
  //         inputElem.type = "text";
  //         inputElem.className = "form-input project-code";

  //         if (currentProjectVal === "" || currentProjectVal === "__TYPE_HERE__") {
  //             inputElem.placeholder = currentProjectVal === "__TYPE_HERE__" ? "Enter Project Code" : "Auto-filled";
  //             inputElem.readOnly = false;
  //             if (currentProjectVal !== "__TYPE_HERE__") {
  //                 inputElem.style.backgroundColor = "#f0f0f0";
  //             }
  //         } else {
  //             let projectCode = "";
  //             if (clientValue && employeeProjects.projects_by_client?.[clientValue]) {
  //                 const match = employeeProjects.projects_by_client[clientValue]
  //                     .find(p => p.project_name === currentProjectVal);
  //                 projectCode = match?.project_code || "";
  //             }
  //             inputElem.value = projectCode;
  //             inputElem.readOnly = true;
  //             inputElem.style.backgroundColor = "#f0f0f0";
  //         }

  //         if (isModal) {
  //             inputElem.id = "modalProjectCodeInput";
  //         }

  //         codeContainer.appendChild(inputElem);
  //     }
  // };
      
  //     container.innerHTML = "";
  //     const wrapper = document.createElement("div");
  //     wrapper.style.display = "flex";
  //     wrapper.style.alignItems = "center";
  //     wrapper.style.gap = "5px";
  //     wrapper.appendChild(input);
  //     wrapper.appendChild(backBtn);
  //     container.appendChild(wrapper);
      
  //     input.focus();
  //     input.addEventListener("input", updateSummary);
  //   } 
  //   // CLIENT CHANGE: Update project dropdown
  //   else if (type === "client" && row) {
  //     const selectedClient = this.value;
  //     const projectCell = row.querySelector(".col-project");
  //     const projectCodeCell = row.querySelector(".col-project-code");
      
  //     // Clear project and project code
  //     if (projectCell) {
  //       // projectCell.innerHTML = "";
  //       // projectCell.appendChild(createSmartDropdown("project", projectCell, "", selectedClient));
  //       const currentProjectInput = projectCell.querySelector("input");

  //       projectCell.innerHTML = "";

  //       if (currentProjectInput) {
  //         // Preserve input mode
  //         const input = document.createElement("input");
  //         input.type = "text";
  //         input.className = "project form-input";
  //         input.placeholder = "Enter project";
  //         projectCell.appendChild(input);
  //       } else {
  //         // Normal dropdown mode
  //         projectCell.appendChild(createSmartDropdown("project", projectCell, "", selectedClient));
  //       }

  //     }
      
  //     if (projectCodeCell) {
  //       projectCodeCell.innerHTML = "";
  //       const codeInput = document.createElement("input");
  //       codeInput.type = "text";
  //       codeInput.className = "project-code form-input";
  //       codeInput.placeholder = "Auto-filled";
  //       codeInput.readOnly = true;
  //       codeInput.style.backgroundColor = "#f0f0f0";
  //       projectCodeCell.appendChild(codeInput);
  //     }
  //   }
  //   // PROJECT CHANGE: Auto-fill project code
  //   // else if (type === "project" && row) {
  //   //   const selectedProject = this.value;
  //   //   const clientValue = getFieldValue(row, '.col-client');
      
  //   //   if (clientValue && employeeProjects.projects_by_client && employeeProjects.projects_by_client[clientValue]) {
  //   //     const projectData = employeeProjects.projects_by_client[clientValue].find(
  //   //       p => p.project_name === selectedProject
  //   //     );
        
  //   //     if (projectData) {
  //   //       const projectCodeCell = row.querySelector(".col-project-code");
  //   //       if (projectCodeCell) {
  //   //         projectCodeCell.innerHTML = "";
  //   //         const codeInput = document.createElement("input");
  //   //         codeInput.type = "text";
  //   //         codeInput.className = "project-code form-input";
  //   //         codeInput.value = projectData.project_code;
  //   //         codeInput.readOnly = true;
  //   //         codeInput.style.backgroundColor = "#f0f0f0";
  //   //         projectCodeCell.appendChild(codeInput);
  //   //       }
  //   //     }
  //   //   }
  //   // }
  //   else if (type === "project" && row) {
  //     const selectedProject = this.value;
  //     const clientValue = getFieldValue(row, '.col-client');
  //     const projectCodeCell = row.querySelector(".col-project-code");

  //     if (!projectCodeCell) return;

  //     projectCodeCell.innerHTML = "";

  //     // 🟢 If project is custom
  //     if (selectedProject === "__TYPE_HERE__") {
  //       const codeInput = document.createElement("input");
  //       codeInput.type = "text";
  //       codeInput.className = "project-code form-input";
  //       codeInput.placeholder = "Enter Project Code";
  //       codeInput.readOnly = false;
  //       projectCodeCell.appendChild(codeInput);
  //       return;
  //     }

  //     // 🟢 If project is normal (from dropdown)
  //     if (
  //       clientValue &&
  //       employeeProjects.projects_by_client &&
  //       employeeProjects.projects_by_client[clientValue]
  //     ) {
  //       const projectData =
  //         employeeProjects.projects_by_client[clientValue].find(
  //           p => p.project_name === selectedProject
  //         );

  //       if (projectData) {
  //         const codeInput = document.createElement("input");
  //         codeInput.type = "text";
  //         codeInput.className = "project-code form-input";
  //         codeInput.value = projectData.project_code;
  //         codeInput.readOnly = true;
  //         codeInput.style.backgroundColor = "#f0f0f0";
  //         projectCodeCell.appendChild(codeInput);
  //       }
  //     }
  //   }

  // });

  select.addEventListener("change", function() {
    const row = this.closest("tr");
    
    if (this.value === "__TYPE_HERE__") {
        // Replace with input field
        const input = document.createElement("input");
        input.type = "text";
        input.className = `${type}-field form-input`;
        input.placeholder = `Enter ${type.replace('_', ' ')}`;
        input.value = currentValue;
        input.style.width = "calc(100% - 35px)";
        
        // Add button to go back to dropdown
        const backBtn = document.createElement("button");
        backBtn.className = "back-to-dropdown-btn";
        backBtn.innerHTML = '<i class="fas fa-list"></i>';
        backBtn.title = "Back to dropdown";
        backBtn.type = "button";
        backBtn.style.marginLeft = "5px";
        backBtn.style.padding = "6px 10px";
        backBtn.style.cursor = "pointer";
        backBtn.onclick = () => {
            const isModal = container.closest("#modalOverlay") !== null;
            let clientValue = "";
            if (type === "project") {
                if (isModal) {
                    const clientSelect = document.querySelector("#modalClientContainer select");
                    clientValue = clientSelect?.value || "";
                } else {
                    const row = container.closest("tr");
                    clientValue = row ? getFieldValue(row, '.col-client') : "";
                }
            }
            const newDropdown = createSmartDropdown(type, container, input.value || "", clientValue);
            container.innerHTML = "";
            container.appendChild(newDropdown);
            
            // If typed value not in options → auto-trigger type here mode to preserve it
            const hasOption = Array.from(newDropdown.options).some(opt => opt.value === input.value && opt.value !== "" && opt.value !== "__TYPE_HERE__");
            if (input.value && !hasOption) {
                newDropdown.value = "__TYPE_HERE__";
                const changeEvent = new Event("change");
                newDropdown.dispatchEvent(changeEvent);
            }
            // ────────────────────────────────────────────────
            // Reset project code field (table OR modal)
            // ────────────────────────────────────────────────
            let codeContainer, codeElement;
            if (isModal) {
                codeContainer = document.getElementById("modalProjectCodeContainer");
                codeElement = document.getElementById("modalProjectCodeInput");
            } else {
                const row = container.closest("tr");
                if (row) {
                    codeContainer = row.querySelector(".col-project-code");
                    codeElement = codeContainer?.querySelector("input");
                }
            }
            if (codeContainer) {
                codeContainer.innerHTML = "";
                const currentProjectVal = newDropdown.value;
                const inputElem = document.createElement("input");
                inputElem.type = "text";
                inputElem.className = "form-input project-code";
                if (currentProjectVal === "" || currentProjectVal === "__TYPE_HERE__") {
                    inputElem.placeholder = currentProjectVal === "__TYPE_HERE__" ? "Enter Project Code" : "Auto-filled";
                    inputElem.readOnly = false;
                    if (currentProjectVal !== "__TYPE_HERE__") {
                        inputElem.style.backgroundColor = "#f0f0f0";
                    }
                } else {
                    let projectCode = "";
                    if (clientValue && employeeProjects.projects_by_client?.[clientValue]) {
                        const match = employeeProjects.projects_by_client[clientValue]
                            .find(p => p.project_name === currentProjectVal);
                        projectCode = match?.project_code || "";
                    }
                    inputElem.value = projectCode;
                    inputElem.readOnly = true;
                    inputElem.style.backgroundColor = "#f0f0f0";
                }
                if (isModal) {
                    inputElem.id = "modalProjectCodeInput";
                }
                codeContainer.appendChild(inputElem);
            }
        };
        
        container.innerHTML = "";
        const wrapper = document.createElement("div");
        wrapper.style.display = "flex";
        wrapper.style.alignItems = "center";
        wrapper.style.gap = "5px";
        wrapper.appendChild(input);
        wrapper.appendChild(backBtn);
        container.appendChild(wrapper);
        
        input.focus();
        input.addEventListener("input", updateSummary);

        // ────────────────────────────────────────────────
        // NEW: Handle project code editable for custom (table OR modal)
        // ────────────────────────────────────────────────
        if (type === "project") {
            const isModal = container.closest("#modalOverlay") !== null;
            let projectCodeContainer;
            if (isModal) {
                projectCodeContainer = document.getElementById("modalProjectCodeContainer");
            } else if (row) {
                projectCodeContainer = row.querySelector(".col-project-code");
            }
            if (projectCodeContainer) {
                projectCodeContainer.innerHTML = "";
                const codeInput = document.createElement("input");
                codeInput.type = "text";
                codeInput.className = "project-code form-input";
                codeInput.placeholder = "Enter Project Code";
                codeInput.readOnly = false;
                codeInput.style.backgroundColor = "";
                if (isModal) codeInput.id = "modalProjectCodeInput";
                projectCodeContainer.appendChild(codeInput);
            }
        }
    }
    // CLIENT CHANGE: Update project dropdown
    else if (type === "client" && row) {
        const selectedClient = this.value;
        const projectCell = row.querySelector(".col-project");
        const projectCodeCell = row.querySelector(".col-project-code");
        
        // Clear project and project code
        if (projectCell) {
            const currentProjectInput = projectCell.querySelector("input");
            projectCell.innerHTML = "";
            if (currentProjectInput) {
                // Preserve input mode
                const input = document.createElement("input");
                input.type = "text";
                input.className = "project form-input";
                input.placeholder = "Enter project";
                projectCell.appendChild(input);
            } else {
                // Normal dropdown mode
                projectCell.appendChild(createSmartDropdown("project", projectCell, "", selectedClient));
            }
        }
        
        if (projectCodeCell) {
            // projectCodeCell.innerHTML = "";
            // const codeInput = document.createElement("input");
            // codeInput.type = "text";
            // codeInput.className = "project-code form-input";
            // codeInput.placeholder = "Auto-filled";
            // codeInput.readOnly = true;
            // codeInput.style.backgroundColor = "#f0f0f0";
            // projectCodeCell.appendChild(codeInput);
            // In places where you create auto-filled code field:
            projectCodeCell.innerHTML = "";
            projectCodeCell.appendChild(createReadonlyProjectCode("", "Auto-filled"));
            // if (projectData) {
            //     projectCodeCell.appendChild(createReadonlyProjectCode(projectData.project_code || ""));
            // } else {
            //     projectCodeCell.appendChild(createReadonlyProjectCode("", "Auto-filled"));
            // }        
          }
    }
    // PROJECT CHANGE: Auto-fill project code (only for non-custom selections)
    else if (type === "project" && row) {
        const selectedProject = this.value;
        const clientValue = getFieldValue(row, '.col-client');
        const projectCodeCell = row.querySelector(".col-project-code");
        if (!projectCodeCell) return;
        projectCodeCell.innerHTML = "";
        // 🟢 If project is normal (from dropdown)
        if (
            clientValue &&
            employeeProjects.projects_by_client &&
            employeeProjects.projects_by_client[clientValue]
        ) {
            const projectData =
                employeeProjects.projects_by_client[clientValue].find(
                    p => p.project_name === selectedProject
                );
            if (projectData) {
                // const codeInput = document.createElement("input");
                // codeInput.type = "text";
                // codeInput.className = "project-code form-input";
                // codeInput.value = projectData.project_code;
                // codeInput.readOnly = true;
                // codeInput.style.backgroundColor = "#f0f0f0";
                // projectCodeCell.appendChild(codeInput);

                // In places where you create auto-filled code field:
                projectCodeCell.innerHTML = "";
                if (projectData) {
                    projectCodeCell.appendChild(createReadonlyProjectCode(projectData.project_code || ""));
                } else {
                    projectCodeCell.appendChild(createReadonlyProjectCode("", "Auto-filled"));
                }            }
        }
    }
}); 
  
  // Trigger summary update on dropdown change
  select.addEventListener("change", updateSummary);
  
  return select;
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
    const secNum = sectionId.split("_")[1];
    const tbody = document.getElementById(`timesheetBody_${secNum}`);
    if (!tbody) return;

    const weekSel = document.getElementById(`weekPeriod_${secNum}`);
    if (!weekSel || !weekSel.value) return;

    const selectedWeek = window.weekOptions.find(w => w.value === weekSel.value);
    if (!selectedWeek) return;

    const weekStartISO = new Date(selectedWeek.start).toISOString().split("T")[0];
    const weekEndISO = new Date(selectedWeek.end).toISOString().split("T")[0];

    // Sabhi date inputs ko update karo
    tbody.querySelectorAll(".date-field").forEach(input => {
        // min/max set karo
        input.min = weekStartISO;
        input.max = weekEndISO;

        // Agar khali hai ya invalid date hai → week ki starting date daal do
        if (!input.value || input.value < weekStartISO || input.value > weekEndISO) {
            input.value = weekStartISO;
        }

        // Validation trigger karo
        validateDate(input);
    });

    // Agar modal open hai to uska date bhi sync karo
    const modalDate = document.getElementById("modalInput1");
    if (modalDate && document.getElementById("modalOverlay")?.style.display === "flex") {
        modalDate.min = weekStartISO;
        modalDate.max = weekEndISO;
        if (!modalDate.value || modalDate.value < weekStartISO || modalDate.value > weekEndISO) {
            modalDate.value = weekStartISO;
        }
        validateDate(modalDate);
    }
}

function addRow(sectionId, specificDate = null) {
  const sectionNum = sectionId.split("_")[1];
  const tbody = document.getElementById(`timesheetBody_${sectionNum}`);
  if (!tbody) {
    console.error("Table body not found for", sectionId);
    return;
  }    

  const weekSelect = document.getElementById(`weekPeriod_${sectionNum}`);
  if (!weekSelect || !weekSelect.value) {
    showPopup("Please select a week period first!", true);
    return;
  }

  const selectedWeek = window.weekOptions.find(w => w.value === weekSelect.value);
  if (!selectedWeek) {
    showPopup("Invalid week selected", true);
    return;
  }

  const weekStart = new Date(selectedWeek.start);
  const weekEnd = new Date(selectedWeek.end);

  // Step 1: Find the last used date in THIS section only
  const dateInputs = tbody.querySelectorAll(".date-field");
  let nextDate;

  if (dateInputs.length === 0) {
    // First row → use week start
    nextDate = new Date(weekStart);
  } else {
    // Get last row's date
    const lastInput = dateInputs[dateInputs.length - 1];
    const lastDate = new Date(lastInput.value || weekStart);
    nextDate = new Date(lastDate);
    nextDate.setDate(lastDate.getDate() + 1); // +1 day
  }

  // Step 2: If nextDate is beyond week end → set to week end
  if (nextDate > weekEnd) {
    nextDate = new Date(weekEnd);
  }

  // Step 3: Format as YYYY-MM-DD
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
    <td class="col-date form-input">
      <input type="date" class="date-field form-input" value="${defaultDate}" onchange="validateDate(this); updateSummary()">
    </td>
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
    <td class="col-remarks"><input type="text" class="remarks-field form-input" placeholder="Additional notes"></td>
    <td class="col-delete"><button class="delete-btn" onclick="deleteRow(this)">Delete</button></td>
  `;

  tbody.appendChild(tr);

  // ✅ Setup smart dropdowns for client, project, project code
  setupSmartDropdowns(tr);

  // Auto focus first input
  setTimeout(() => tr.querySelector("input, select")?.focus(), 100);

  updateRowNumbers(tbody.id);
  updateSummary();
}

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

function setupSmartDropdowns(row) {
  const clientCell = row.querySelector(".col-client");
  const projectCell = row.querySelector(".col-project");
  const projectCodeCell = row.querySelector(".col-project-code");
  
  // Setup client dropdown
  if (clientCell) {
    clientCell.innerHTML = "";
    clientCell.appendChild(createSmartDropdown("client", clientCell));
  }
  
  // Setup project dropdown (empty initially)
  if (projectCell) {
    projectCell.innerHTML = "";
    const emptyProjectDropdown = createSmartDropdown("project", projectCell, "", "");
    projectCell.appendChild(emptyProjectDropdown);
  }
  
  // Setup project code field (readonly input)
  if (projectCodeCell) {
    // projectCodeCell.innerHTML = "";
    // const codeInput = document.createElement("input");
    // codeInput.type = "text";
    // codeInput.className = "project-code form-input";
    // codeInput.placeholder = "Auto-filled";
    // codeInput.readOnly = true;
    // codeInput.style.backgroundColor = "#f0f0f0";
    // projectCodeCell.appendChild(codeInput);
    // In places where you create auto-filled code field:
    projectCodeCell.innerHTML = "";
    projectCodeCell.appendChild(createReadonlyProjectCode("", "Auto-filled"));
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

    const inputDateStr = input.value;

    // Agar weekOptions abhi load nahi hua → validation skip kar do
    if (!window.weekOptions || window.weekOptions.length === 0) {
        input.classList.remove("validation-error");
        return; // Ab koi popup nahi aayega
    }

    const section = input.closest('.timesheet-section');
    if (!section) return;

    const weekSelect = section.querySelector('select[id^="weekPeriod_"]');
    if (!weekSelect || !weekSelect.value) {
        input.classList.remove("validation-error");
        return;
    }

    const selectedWeek = window.weekOptions.find(w => w.value === weekSelect.value);
    if (!selectedWeek || !selectedWeek.start || !selectedWeek.end) {
        input.classList.remove("validation-error");
        return;
    }

    const inputDate = new Date(inputDateStr);
    const weekStart = new Date(selectedWeek.start);
    const weekEnd = new Date(selectedWeek.end);

    inputDate.setHours(0, 0, 0, 0);
    weekStart.setHours(0, 0, 0, 0);
    weekEnd.setHours(0, 0, 0, 0);

    if (inputDate < weekStart || inputDate > weekEnd) {
        input.classList.add("validation-error");
        const startStr = weekStart.toLocaleDateString('en-GB');
        const endStr = weekEnd.toLocaleDateString('en-GB');
        showPopup(`Invalid Date! Only dates from <strong>${startStr}</strong> to <strong>${endStr}</strong> are allowed.`, true);
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
  
  if (select && select.value !== "__TYPE_HERE__") {
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

    if (optionExists) {
      select.value = value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    } else if (value) {
      select.value = "__TYPE_HERE__";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      setTimeout(() => {
        const newInput = cell.querySelector("input");
        if (newInput) newInput.value = value;
      }, 0);
    }
  } else if (input) {
    input.value = value;
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
    
    // Add change listener to update project dropdown
    clientDropdown.addEventListener("change", function() {
      const selectedClient = this.value;
      updateModalProjectDropdown(selectedClient, "");
    });
  }
  
  // Clear and create project dropdown
  const projectContainer = document.getElementById("modalProjectContainer");
  if (projectContainer) {
    projectContainer.innerHTML = "";
    const projectDropdown = createSmartDropdown("project", projectContainer, projectValue, clientValue);
    projectContainer.appendChild(projectDropdown);
    
    // Add change listener to auto-fill project code
    // projectDropdown.addEventListener("change", function() {
    //   updateModalProjectCode(clientValue, this.value);
    // });
    projectDropdown.addEventListener("change", function() {
      const currentClient = clientContainer?.querySelector("select")?.value;
      updateModalProjectCode(currentClient, this.value);
  }); 

  }
  
  // Clear and create project code field (readonly)
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
  
  // Set other fields
  document.getElementById("modalInput8").value = currentRow.querySelector(".reporting-manager-field")?.value || "";
  document.getElementById("modalInput9").value = currentRow.querySelector(".activity-field")?.value || "";
  document.getElementById("modalInput10").value = currentRow.querySelector(".project-hours-field")?.value || "";
  document.getElementById("modalInput11").value = currentRow.querySelector(".billable-select")?.value || "";
  document.getElementById("modalInput12").value = currentRow.querySelector(".remarks-field")?.value || "";

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

// Update project dropdown when client changes in modal
function updateModalProjectDropdown(selectedClient, selectedProject = "") {
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
  
  // Clear project code when client changes
  // const projectCodeInput = document.getElementById("modalProjectCodeInput");
  // if (projectCodeInput) projectCodeInput.value = "";
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
  const projectCodeInput = document.getElementById("modalProjectCodeInput");
  if (!projectCodeInput) return;

  // 🟢 Custom project
  if (projectValue === "__TYPE_HERE__") {
    projectCodeInput.value = "";
    projectCodeInput.readOnly = false;
    projectCodeInput.placeholder = "Enter Project Code";
    projectCodeInput.style.backgroundColor = "";
    return;
  }

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
    }
  }
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

  // ✅ Get values from smart dropdown containers
  const clientContainer = document.getElementById("modalClientContainer");
  const clientValue = clientContainer?.querySelector("select")?.value || 
                       clientContainer?.querySelector("input")?.value || "";
  
  const projectContainer = document.getElementById("modalProjectContainer");
  const projectValue = projectContainer?.querySelector("select")?.value || 
                        projectContainer?.querySelector("input")?.value || "";

  
  const projectCodeInput = document.getElementById("modalProjectCodeInput");
  const projectCodeValue = projectCodeInput?.value || "";
  
  // Set values using helper function
  setFieldValue(currentRow, ".col-client", clientValue);
  setFieldValue(currentRow, ".col-project", projectValue);
  setFieldValue(currentRow, ".col-project-code", projectCodeValue);

  // Other fields
  const reportingManager = currentRow.querySelector(".reporting-manager-field");
  if (reportingManager) reportingManager.value = document.getElementById("modalInput8").value;

  const activity = currentRow.querySelector(".activity-field");
  if (activity) activity.value = document.getElementById("modalInput9").value;

  const projectHours = currentRow.querySelector(".project-hours-field");
  if (projectHours) projectHours.value = document.getElementById("modalInput10").value;

  const billable = currentRow.querySelector(".billable-select");
  if (billable) billable.value = document.getElementById("modalInput11").value;

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
                            <th class="col-medium col-project-start">Project Start Time</th>
                            <th class="col-medium col-project-end">Project End Time</th>
                            <th class="col-wide col-client">Client</th>
                            <th class="col-wide col-project">Project</th>
                            <th class="col-project col-project-code">Project Code</th>
                            <th class="col-wide col-reporting-manager">Reporting Manager</th>
                            <th class="col-wide col-activity">Activity</th>
                            <th class="col-narrow col-project-hours">Project Hours</th>
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
                    <td class="col-project-start">${entry.projectStartTime || ''}</td>
                    <td class="col-project-end">${entry.projectEndTime || ''}</td>
                    <td class="col-client">${entry.client || ''}</td>
                    <td class="col-project">${entry.project || ''}</td>
                    <td class="col-project-code">${entry.projectCode || ''}</td>
                    <td class="col-reporting-manager">${entry.reportingManagerEntry || ''}</td>
                    <td class="col-activity">${entry.activity || ''}</td>
                    <td class="col-project-hours">${entry.projectHours || ''}</td>
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
            // showPopup('Failed to load history: ' + error.message, true);
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

      clientDropdown.addEventListener("change", function () {
          const selectedClient = this.value;
          updateModalProjectDropdown(selectedClient, "");
      });

      const projectContainer = document.getElementById("modalProjectContainer");
      projectContainer.innerHTML = "";
      const projectDropdown = createSmartDropdown(
          "project",
          projectContainer,
          projectValue,
          clientValue
      );
      projectContainer.appendChild(projectDropdown);

      projectDropdown.addEventListener("change", function () {
          const currentClient = clientContainer?.querySelector("select")?.value;
          updateModalProjectCode(currentClient, this.value);
      });

      const projectCodeContainer = document.getElementById("modalProjectCodeContainer");
      projectCodeContainer.innerHTML = "";
      const codeInput = document.createElement("input");
      codeInput.type = "text";
      codeInput.id = "modalProjectCodeInput";
      codeInput.className = "form-input";
      codeInput.value = projectCodeValue;
      codeInput.readOnly = true;
      codeInput.style.backgroundColor = "#f0f0f0";
      projectCodeContainer.appendChild(codeInput);
      
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
  const clientValue =
    clientContainer?.querySelector("select")?.value ||
    clientContainer?.querySelector("input")?.value || "";

  const projectContainer = document.getElementById("modalProjectContainer");
  const projectValue =
    projectContainer?.querySelector("select")?.value ||
    projectContainer?.querySelector("input")?.value || "";

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
        'Week Period': '',
        'S.No': '',
        'Date': '',
        'Location of Work': '',
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
        "projectStartTime",
        "projectEndTime",
        "client",
        "project",
        "projectCode",
        "reportingManagerEntry",
        "activity",
        "projectHours",
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
        "Project Start Time",
        "Project End Time",
        "Client",
        "Project",
        "Project Code",
        "Reporting Manager Entry",
        "Activity",
        "Project Hours",
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
            const project = inputs[5]?.value?.trim() || "";
            const client =
                inputs[4]?.value ||
                inputs[4]?.querySelector("option:checked")?.value ||
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
                projectStartTime: inputs[2]?.value || "",
                projectEndTime: inputs[3]?.value || "",
                client: client,
                project: project,
                projectCode: inputs[6]?.value || "",
                reportingManagerEntry: inputs[7]?.value || "",
                activity: inputs[8]?.value || "",
                projectHours: inputs[9]?.value || "",
                billable: inputs[10]?.value || "",
                remarks: inputs[11]?.value || "",
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
        "projectStartTime",
        "projectEndTime",
        "client",
        "project",
        "projectCode",
        "reportingManagerEntry",
        "activity",
        "projectHours",
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
        "Project Start Time",
        "Project End Time",
        "Client",
        "Project",
        "Project Code",
        "Reporting Manager Entry",
        "Activity",
        "Project Hours",
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
        projectStartTime: row.projectStartTime || "",
        projectEndTime: row.projectEndTime || "",
        client: row.client || "",
        project: row.project || "",
        projectCode: row.projectCode || "",
        reportingManagerEntry: row.reportingManagerEntry || "",
        activity: row.activity || "",
        projectHours: row.projectHours || "",
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
              weekPeriod: toStr(row['Week Period']) || '',
              date: toStr(row['Date']) || '',
              location: toStr(row['Location of Work']) || '',

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
              remarks: toStr(row['Remarks']) || '',
              hits: toStr(row['3 Hits']) || '',
              misses: toStr(row['3 Misses']) || '',
              feedback_hr: toStr(row['Feedback for HR']) || '',
              feedback_it: toStr(row['Feedback for IT']) || '',
              feedback_crm: toStr(row['Feedback for CRM']) || '',
              feedback_others: toStr(row['Feedback for Others']) || ''
            };
          });


            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_URL}/save_timesheets`, {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify(timesheetData)
            });

            hideLoading();

            if (!response.ok) {
                const errorData = await response.json();
                // throw new Error(errorData.detail || 'Failed to upload Excel data.');
                const message = Array.isArray(errorData.detail)
                  ? errorData.detail.map(e => `${e.loc.join('.')} → ${e.msg}`).join('\n')
                  : errorData.detail;

                throw new Error(message);

            }

            const result = await response.json();
            showPopup('Excel uploaded and saved successfully!');
            // setTimeout(() => window.location.reload(), 2000);

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


/* End of file */
