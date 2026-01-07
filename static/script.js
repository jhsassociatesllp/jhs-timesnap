let rowCount = 0;
let sectionCount = 0;
let employeeData = [];
let clientData = [];
let currentRow = null;
let weekOptions = [];
let loggedInEmployeeId = localStorage.getItem('loggedInEmployeeId');
let copiedData = null; // Store copied row data
const API_URL = '';
// const API_URL = window.location.origin;
let isEditingHistory = false;
let currentEntryId = null;
let historyEntries = [];


const getHeaders = () => ({
    'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
    'Content-Type': 'application/json'
});

document.addEventListener('DOMContentLoaded', async function() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = '/login';
        return;
    }

    // Verify session   
    try {
        const response = await fetch('/verify_session', {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        });
        if (!response.ok) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('loggedInEmployeeId');
            window.location.href = '/login';
            return;
        }
    } catch (error) {
        console.error('Session verification failed:', error);
        localStorage.removeItem('access_token');
        localStorage.removeItem('loggedInEmployeeId');
        window.location.href = '/login';
        return;
    }

    // Show loading indicator for employee data fetch
    showLoading("Fetching Employee Data");

    // Initialize data
    if (loggedInEmployeeId) {
        try {
            employeeData = await fetchData('/employees');
            clientData = await fetchData('/clients');
            const payroll = getPayrollPeriod();
            weekOptions = generateWeekOptions(payroll.start, payroll.end);
            await populateEmployeeInfo();
            
            // ✅ Check if user is a manager
            await checkAndShowManagerButtons();
            
            addWeekSection();
            showSection('timesheet');
        } catch (error) {
            console.error('Error initializing data:', error);
            showError('Failed to load employee data. Please try again.');
        } finally {
            hideLoading();
        }
    }
});

async function loadPendingData() {
    try {
        showLoading("Loading Pending Employees...");
        const response = await fetch(`${API_URL}/get_pending_employees/${loggedInEmployeeId}`, {
            headers: getHeaders()
        });
        
        if (!response.ok) throw new Error('Failed to fetch pending employees');
        
        const data = await response.json();
        const tbody = document.getElementById('pendingTableBody');
        tbody.innerHTML = '';
        
        if (!data.employees || data.employees.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3">No pending approvals</td></tr>';
        } else {
            data.employees.forEach(emp => {
                const row = `
                    <tr>
                        <td>${emp.employeeId}</td>
                        <td>${emp.timesheetData?.employeeName || 'N/A'}</td>
                        <td>
                            <button class="action-btn edit-btn" onclick="viewEmployeeTimesheet('${emp.employeeId}')">
                                <i class="fas fa-eye"></i> View
                            </button>
                            <button class="action-btn approve-btn" onclick="approveEmployee('${loggedInEmployeeId}', '${emp.employeeId}')">
                                <i class="fas fa-check"></i> Approve
                            </button>
                            <button class="action-btn delete-btn" onclick="rejectEmployee('${loggedInEmployeeId}', '${emp.employeeId}')">
                                <i class="fas fa-times"></i> Reject
                            </button>
                        </td>
                    </tr>
                `;
                tbody.innerHTML += row;
            });
        }
        hideLoading();
    } catch (error) {
        console.error('Error loading pending data:', error);
        hideLoading();
        showPopup('Failed to load pending employees', true);
    }
}

async function loadApprovedData() {
    try {
        showLoading("Loading Approved Employees...");
        const response = await fetch(`${API_URL}/get_approved_employees/${loggedInEmployeeId}`, {
            headers: getHeaders()
        });
        
        if (!response.ok) throw new Error('Failed to fetch approved employees');
        
        const data = await response.json();
        const tbody = document.getElementById('approveTableBody');
        tbody.innerHTML = '';
        
        if (!data.employees || data.employees.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3">No approved employees</td></tr>';
        } else {
            data.employees.forEach(emp => {
                const row = `
                    <tr>
                        <td>${emp.employeeId}</td>
                        <td>${emp.timesheetData?.employeeName || 'N/A'}</td>
                        <td>
                            <button class="action-btn edit-btn" onclick="viewEmployeeTimesheet('${emp.employeeId}')">
                                <i class="fas fa-eye"></i> View
                            </button>
                        </td>
                    </tr>
                `;
                tbody.innerHTML += row;
            });
        }
        hideLoading();
    } catch (error) {
        console.error('Error loading approved data:', error);
        hideLoading();
        showPopup('Failed to load approved employees', true);
    }
}

async function loadRejectedData() {
    try {
        showLoading("Loading Rejected Employees...");
        const response = await fetch(`${API_URL}/get_rejected_employees/${loggedInEmployeeId}`, {
            headers: getHeaders()
        });
        
        if (!response.ok) throw new Error('Failed to fetch rejected employees');
        
        const data = await response.json();
        const tbody = document.getElementById('rejectedTableBody');
        tbody.innerHTML = '';
        
        if (!data.employees || data.employees.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3">No rejected employees</td></tr>';
        } else {
            data.employees.forEach(emp => {
                const row = `
                    <tr>
                        <td>${emp.employeeId}</td>
                        <td>${emp.timesheetData?.employeeName || 'N/A'}</td>
                        <td>
                            <button class="action-btn edit-btn" onclick="viewEmployeeTimesheet('${emp.employeeId}')">
                                <i class="fas fa-eye"></i> View
                            </button>
                        </td>
                    </tr>
                `;
                tbody.innerHTML += row;
            });
        }
        hideLoading();
    } catch (error) {
        console.error('Error loading rejected data:', error);
        hideLoading();
        showPopup('Failed to load rejected employees', true);
    }
}

async function approveEmployee(managerCode, employeeCode) {
    try {
        showLoading("Approving...");
        const response = await fetch(`${API_URL}/approve_timesheet`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                reporting_emp_code: managerCode,
                employee_code: employeeCode
            })
        });
        
        const result = await response.json();
        hideLoading();
        
        if (result.success) {
            showPopup('Employee approved successfully!');
            await loadPendingData(); // Refresh the list
        } else {
            showPopup('Failed to approve employee', true);
        }
    } catch (error) {
        console.error('Error approving employee:', error);
        hideLoading();
        showPopup('Failed to approve employee', true);
    }
}

async function rejectEmployee(managerCode, employeeCode) {
    if (!confirm('Are you sure you want to reject this employee?')) return;
    
    try {
        showLoading("Rejecting...");
        const response = await fetch(`${API_URL}/reject_timesheet`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                reporting_emp_code: managerCode,
                employee_code: employeeCode
            })
        });
        
        const result = await response.json();
        hideLoading();
        
        if (result.success) {
            showPopup('Employee rejected successfully!');
            await loadPendingData(); // Refresh the list
        } else {
            showPopup('Failed to reject employee', true);
        }
    } catch (error) {
        console.error('Error rejecting employee:', error);
        hideLoading();
        showPopup('Failed to reject employee', true);
    }
}

function viewEmployeeTimesheet(employeeId) {
    // Open in new tab or modal
    window.open(`/view_timesheet/${employeeId}`, '_blank');
}

async function checkSession() {
    const token = localStorage.getItem('access_token');
    if (!token) {
        window.location.href = '/static/login.html';
        return;
    }
    try {
        const response = await fetch(`${API_URL}/verify_session`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!response.ok) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('loggedInEmployeeId');
            window.location.href = '/static/login.html';
        }
    } catch (error) {
        console.error('Session check failed:', error);
        localStorage.removeItem('access_token');
        localStorage.removeItem('loggedInEmployeeId');
        window.location.href = '/static/login.html';
    }
}

async function fetchData(endpoint) {
    try {
        const token = localStorage.getItem('access_token');
        if (!token) {
            window.location.href = '/static/login.html';
            return [];
        }
        const response = await fetch(`${API_URL}${endpoint}`, {
            headers: getHeaders()
        });
        if (!response.ok) {
            if (response.status === 401) {
                localStorage.removeItem('access_token');
                localStorage.removeItem('loggedInEmployeeId');
                window.location.href = '/static/login.html';
            }
            throw new Error(`Failed to fetch ${endpoint}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`Error fetching ${endpoint}:`, error);
        showError(`Error fetching ${endpoint.split('/')[1]} data. Please try again.`);
        return [];
    }
}

function computeWeekOptions() {
    const today = new Date(); // Dynamic current date
    const payroll = getPayrollPeriod(today);
    weekOptions = generateWeekOptions(payroll.start, payroll.end);
}

function getPayrollPeriod(today) {
    let start = new Date(2025, 9, 21); // Sep 21, 2025
    let end = new Date(2025, 10, 20); // Oct 20, 2025
    return { start, end };
}

function generateWeekOptions(start, end) {
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    let weeks = [];
    let current = new Date(start);
    let weekNum = 1;
    while (current <= end) {
        let weekStart = new Date(current);
        let daysToSunday = (7 - weekStart.getDay()) % 7;
        let weekEnd = new Date(weekStart);
        weekEnd.setDate(weekEnd.getDate() + daysToSunday);
        if (weekEnd > end) {
            weekEnd = new Date(end);
        }
        let wsDay = weekStart.getDate().toString().padStart(2, '0');
        let wsMonth = months[weekStart.getMonth()];
        let weDay = weekEnd.getDate().toString().padStart(2, '0');
        let weMonth = months[weekEnd.getMonth()];
        let value = `${wsDay}/${weekStart.getMonth() + 1}/${weekStart.getFullYear()} to ${weDay}/${weekEnd.getMonth() + 1}/${weekEnd.getFullYear()}`;
        let text = `Week ${weekNum} (${wsDay} ${wsMonth} - ${weDay} ${weMonth})`;
        weeks.push({ value, text, start: weekStart, end: weekEnd });
        current = new Date(weekEnd);
        current.setDate(current.getDate() + 1);
        weekNum++;
    }
    return weeks;
}

function showError(message) {
    const errorDiv = document.getElementById('errorMessage');
    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.style.display = 'block';
        setTimeout(() => {
            errorDiv.style.display = 'none';
        }, 5000);
    }
}

function showPopup(message, isError = false) {
    const popup = document.getElementById('successPopup');
    const popupMessage = document.getElementById('popupMessage');
    popupMessage.textContent = message;
    popup.className = 'popup' + (isError ? ' error' : '');
    popup.style.display = 'block';
    setTimeout(closePopup, 3000);
}

function closePopup() {
    document.getElementById('successPopup').style.display = 'none';
}


function showLoading(text = "Saving...") {
    const loadingBar = document.getElementById('loadingBar');
    if (loadingBar) {
        loadingBar.textContent = `${text}...`;
        loadingBar.style.display = 'block';
    }
}

function hideLoading() {
    const loadingBar = document.getElementById('loadingBar');
    if (loadingBar) {
        loadingBar.style.display = 'none';
    }
}

function fetchEmployeeData(empId) {
    const cleanEmpId = empId.trim();
    const employee = employeeData.find(e => e['EmpID']?.toString().trim() === cleanEmpId);
    if (!employee) {
        showError(`No employee found for ID: ${empId}`);
        return null;
    }
    return { ...employee };
}

async function populateEmployeeInfo() {
    const employee = fetchEmployeeData(loggedInEmployeeId);
    if (employee) {
        const fields = {
            employeeId: employee['EmpID'] || '',
            employeeName: employee['Emp Name'] || '',
            designation: employee['Designation Name'] || '',
            partner: employee['Partner'] || '',
            reportingManager: employee['ReportingEmpName'] || '',
            gender: employee['Gender'] === 'F' ? 'Female' : employee['Gender'] === 'M' ? 'Male' : ''
        };
        Object.entries(fields).forEach(([id, value]) => {
            const element = document.getElementById(id);
            if (element) element.value = value;
        });
        // updateAllReportingManagerFields();
    }
}

async function checkAndShowManagerButtons() {
    try {
        const response = await fetch(`${API_URL}/check_reporting_manager/${loggedInEmployeeId}`, {
            headers: getHeaders()
        });
        
        if (!response.ok) {
            throw new Error('Failed to check manager status');
        }
        
        const result = await response.json();
        const isManager = result.isManager;
        
        // Show/Hide manager-only buttons
        const managerButtons = document.querySelectorAll('.manager-only');
        managerButtons.forEach(btn => {
            if (isManager) {
                btn.style.display = 'block';
            } else {
                btn.style.display = 'none';
            }
        });
        
        console.log(`User ${loggedInEmployeeId} is ${isManager ? 'a manager' : 'not a manager'}`);
        
    } catch (error) {
        console.error('Error checking manager status:', error);
        // Default: hide manager buttons if check fails
        const managerButtons = document.querySelectorAll('.manager-only');
        managerButtons.forEach(btn => {
            btn.style.display = 'none';
        });
    }
}

function fetchProjectData(tl, manager) {
    const cleanTL = tl ? tl.trim().toLowerCase() : '';
    const cleanManager = manager ? manager.trim().toLowerCase() : '';
    let projects = clientData.filter(p => 
        p['TLs/Manager']?.toString().trim().toLowerCase() === cleanTL || 
        p['TLs/Manager']?.toString().trim().toLowerCase() === cleanManager
    );
    projects = projects.map(p => {
        const cleaned = { ...p };
        cleaned['CLIENT NAME'] = cleanClientName(p['CLIENT NAME']);
        return cleaned;
    });
    const uniqueProjects = [];
    const seen = new Set();
    projects.forEach(p => {
        const key = `${p['PROJECT ID']}|${p['CLIENT NAME']}`;
        if (!seen.has(key) ) {
            seen.add(key);
            uniqueProjects.push(p);
        }
    });
    return uniqueProjects;
}

function cleanClientName(name) {
    if (!name) return "";
    name = name.replace(/_x000D_|\n|\r/g, '');
    return name.trim().replace(/\s+/g, ' ');
}

function getReportingManagers() {
    const managers = [...new Set(employeeData
        .map(e => e['ReportingEmpName'])
        .filter(m => m && typeof m === 'string' && m.trim()))];
    return managers;
}


function calculateHours(row) {
    if (!row) return;
    const isValid = validateTimes(row);
    if (!isValid) {
        const projectHoursField = row.querySelector('.project-hours-field');
        // REMOVED: const workingHoursField = row.querySelector('.working-hours-field');
        if (projectHoursField) projectHoursField.value = '';
        // REMOVED: if (workingHoursField) workingHoursField.value = '';
        return;
    }

    const projectStart = row.querySelector('.project-start')?.value;
    const projectEnd = row.querySelector('.project-end')?.value;
    // REMOVED: const punchIn = row.querySelector('.punch-in')?.value;
    // REMOVED: const punchOut = row.querySelector('.punch-out')?.value;

    let projectHours = 0;
    if (projectStart && projectEnd) {
        const [startH, startM] = projectStart.split(':').map(Number);
        const [endH, endM] = projectEnd.split(':').map(Number);
        const startMinutes = startH * 60 + startM;
        const endMinutes = endH * 60 + endM;
        projectHours = (endMinutes - startMinutes) / 60;
        if (projectHours < 0) projectHours += 24;
        projectHours = Math.max(0, projectHours).toFixed(2);
    }

    // REMOVED: Working Hours calculation
    // REMOVED: let workingHours = 0;
    // REMOVED: if (punchIn && punchOut) { ... }

    const projectHoursField = row.querySelector('.project-hours-field');
    // REMOVED: const workingHoursField = row.querySelector('.working-hours-field');
    if (projectHoursField) projectHoursField.value = projectHours > 0 ? projectHours : '';
    // REMOVED: if (workingHoursField) workingHoursField.value = workingHours > 0 ? workingHours : '';
    updateSummary();
}


function updateExistingRowDates(sectionId) {
    const tbody = document.getElementById(`timesheetBody_${sectionId.split('_')[1]}`);
    if (!tbody) return;
    
    const weekSelect = document.getElementById(`weekPeriod_${sectionId.split('_')[1]}`);
    const selectedWeekValue = weekSelect.value;
    const selectedWeek = weekOptions.find(opt => opt.value === selectedWeekValue);
    
    if (selectedWeek && selectedWeek.start) {
        const weekStart = new Date(selectedWeek.start);
        const weekEnd = new Date(selectedWeek.end);
        
        const minDate = `${weekStart.getFullYear()}-${String(weekStart.getMonth() + 1).padStart(2, '0')}-${String(weekStart.getDate()).padStart(2, '0')}`;
        const maxDate = `${weekEnd.getFullYear()}-${String(weekEnd.getMonth() + 1).padStart(2, '0')}-${String(weekEnd.getDate()).padStart(2, '0')}`;
        
        const dateInputs = tbody.querySelectorAll('.date-field');
        dateInputs.forEach(dateInput => {
            dateInput.setAttribute('min', minDate);
            dateInput.setAttribute('max', maxDate);
            
            // ✅ CLEAR DATE: If date exists and is outside new week range
            if (dateInput.value) {
                const currentDate = dateInput.value;
                if (currentDate < minDate || currentDate > maxDate) {
                    dateInput.value = '';  // Clear invalid date
                }
            }
            
            // Clear validation styling
            dateInput.classList.remove('validation-error');
            clearValidationMessage(dateInput);
        });
    }
}


function validateHours(hoursInput) {
    if (!hoursInput) return;
    const hours = parseFloat(hoursInput.value);
    if (hours > 16) {
        hoursInput.classList.add('validation-error');
        showValidationMessage(hoursInput, 'Hours cannot exceed 16 per day');
    } else {
        hoursInput.classList.remove('validation-error');
        clearValidationMessage(hoursInput);
    }
}

function formatDateForDisplay(date) {
    const d = new Date(date);
    const day = String(d.getDate()).padStart(2, '0');
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const month = months[d.getMonth()];
    return `${day} ${month}`;
}

function validateDate(dateInput) {
    if (!dateInput || !dateInput.value) {
        // ✅ Clear validation if empty
        dateInput.classList.remove('validation-error');
        clearValidationMessage(dateInput);
        return true;
    }
    
    const section = dateInput.closest('.timesheet-section');
    const weekSelect = section.querySelector('.week-period select');
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value);
    if (!selectedWeek) return true;

    const inputDateStr = dateInput.value;
    const weekStartStr = `${selectedWeek.start.getFullYear()}-${String(selectedWeek.start.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.start.getDate()).padStart(2, '0')}`;
    const weekEndStr = `${selectedWeek.end.getFullYear()}-${String(selectedWeek.end.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.end.getDate()).padStart(2, '0')}`;
    
    // ✅ ALWAYS clear previous validation first
    dateInput.classList.remove('validation-error');
    clearValidationMessage(dateInput);
    
    // ✅ ONLY CHECK: Week range
    if (inputDateStr < weekStartStr || inputDateStr > weekEndStr) {
        dateInput.classList.add('validation-error');
        const weekStartFormatted = formatDateForDisplay(selectedWeek.start);
        const weekEndFormatted = formatDateForDisplay(selectedWeek.end);
        showValidationMessage(dateInput, `Date must be between ${weekStartFormatted} and ${weekEndFormatted}`);
        return false;
    }
    
    return true;
}



function validateModalDate(dateInput) {
    // ✅ Check if dateInput exists
    if (!dateInput) {
        console.warn("⚠️ validateModalDate: dateInput is null");
        return true;
    }
    
    // ✅ If no value, just clear validation
    if (!dateInput.value) {
        dateInput.classList.remove('validation-error');
        clearValidationMessage(dateInput);
        return true;
    }
    
    // ✅ Skip validation in history edit mode
    if (isEditingHistory) {
        console.log("ℹ️ Skipping date validation (editing history)");
        dateInput.classList.remove('validation-error');
        clearValidationMessage(dateInput);
        return true;
    }
    
    // ✅ Only validate for new timesheet entries
    if (!currentRow) {
        console.warn("⚠️ No currentRow found");
        return true;
    }
    
    const section = currentRow.closest('.timesheet-section');
    if (!section) {
        console.warn("⚠️ No timesheet section found");
        return true;
    }
    
    const weekSelect = section.querySelector('.week-period select');
    if (!weekSelect) {
        console.warn("⚠️ No week selector found");
        return true;
    }
    
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value);
    if (!selectedWeek) {
        return true;
    }

    const inputDateStr = dateInput.value;
    const weekStartStr = `${selectedWeek.start.getFullYear()}-${String(selectedWeek.start.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.start.getDate()).padStart(2, '0')}`;
    const weekEndStr = `${selectedWeek.end.getFullYear()}-${String(selectedWeek.end.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.end.getDate()).padStart(2, '0')}`;
    
    // ✅ Clear previous validation
    dateInput.classList.remove('validation-error');
    clearValidationMessage(dateInput);
    
    // ✅ Check week range
    if (inputDateStr < weekStartStr || inputDateStr > weekEndStr) {
        dateInput.classList.add('validation-error');
        const weekStartFormatted = formatDateForDisplay(selectedWeek.start);
        const weekEndFormatted = formatDateForDisplay(selectedWeek.end);
        showValidationMessage(dateInput, `Date must be between ${weekStartFormatted} and ${weekEndFormatted} for this week.`);
        showPopup(`Please select a date within the week range (${weekStartFormatted} - ${weekEndFormatted})`, true);
        return false;
    }
    
    return true;
}

function validate60DaysRule(dateInput) {
    if (!dateInput || !dateInput.value) return true;
    
    const inputDateStr = dateInput.value;
    const today = new Date();
    const sixtyDaysAgo = new Date(today.getTime() - (60 * 24 * 60 * 60 * 1000));
    const yesterday = new Date(today.getTime() - (24 * 60 * 60 * 1000));
    const sixtyDaysAgoStr = sixtyDaysAgo.toISOString().split('T')[0];
    const yesterdayStr = yesterday.toISOString().split('T')[0];
    
    if (inputDateStr < sixtyDaysAgoStr || inputDateStr > yesterdayStr) {
        return false;
    }
    
    return true;
}

function showValidationMessage(element, message) {
    if (!element) return;
    clearValidationMessage(element);
    const msgDiv = document.createElement('div');
    msgDiv.className = 'validation-message';
    msgDiv.textContent = message;
    element.parentNode.appendChild(msgDiv);
}

function clearValidationMessage(element) {
    if (!element) return;
    const existingMsg = element.parentNode.querySelector('.validation-message');
    if (existingMsg) existingMsg.remove();
}

function deleteRow(button) {
    const row = button.closest('tr');
    if (row) {
        const tbody = row.closest('tbody');
        row.remove();
        updateRowNumbers(tbody.id);
        updateSummary();
    }
}

function updateRowNumbers(tbodyId) {
    const tbody = document.getElementById(tbodyId);
    const rows = tbody.querySelectorAll('tr');
    rows.forEach((row, index) => {
        row.cells[0].textContent = index + 1;
    });
}

function deleteWeekSection(sectionId) {
    if (confirm('Are you sure you want to delete this week section?')) {
        const section = document.getElementById(sectionId);
        if (section) {
            section.remove();
            updateSummary();
        }
    }
}

function openModal(button) {
    isEditingHistory = false;
    currentRow = button.closest('tr');
    const inputs = currentRow.querySelectorAll('input, select');
    
    const labels = [
        'Date',
        'Location of Work',
        'Project Start Time',
        'Project End Time',
        'Client',
        'Project',
        'Project Code',
        'Reporting Manager',
        'Activity',
        'Project Hours',
        'Billable',
        'Remarks'
    ];
    
    for (let i = 0; i < 12; i++) {
        const label = document.getElementById(`modalLabel${i + 1}`);
        const input = document.getElementById(`modalInput${i + 1}`);

        if (!label || !input) continue;

        label.textContent = labels[i];
        input.value = inputs[i] ? inputs[i].value : '';
    }
    
    // Set min and max for date input in modal
    const section = currentRow.closest('.timesheet-section');
    const weekSelect = section.querySelector('.week-period select');
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value);
    
    if (selectedWeek) {
        const weekStart = new Date(selectedWeek.start);
        const weekEnd = new Date(selectedWeek.end);
        const minDate = `${weekStart.getFullYear()}-${String(weekStart.getMonth() + 1).padStart(2, '0')}-${String(weekStart.getDate()).padStart(2, '0')}`;
        const maxDate = `${weekEnd.getFullYear()}-${String(weekEnd.getMonth() + 1).padStart(2, '0')}-${String(weekEnd.getDate()).padStart(2, '0')}`;
        
        const modalDateInput = document.getElementById('modalInput1');
        if (modalDateInput) {
            modalDateInput.setAttribute('min', minDate);
            modalDateInput.setAttribute('max', maxDate);
            
            // Clear any validation styling
            modalDateInput.classList.remove('validation-error');
            clearValidationMessage(modalDateInput);
        }
    }

    document.getElementById('modalOverlay').style.display = 'flex';
    updateModalHours();
    
    const addBtn = document.getElementById('modalAddBtn');
    addBtn.innerHTML = '<i class="fas fa-check"></i> Add';
    addBtn.setAttribute('onclick', 'saveModalEntry()');
    const cancelBtn = document.getElementById('modalCancelBtn');
    cancelBtn.innerHTML = '<i class="fas fa-times"></i> Cancel';
}

function closeModal() {
    document.getElementById('modalOverlay').style.display = 'none';
    currentRow = null;
    isEditingHistory = false;
    currentEntryId = null;
    
    // ✅ Reset button to "Add"
    const addBtn = document.getElementById('modalAddBtn');
    if (addBtn) {
        addBtn.innerHTML = '<i class="fas fa-check"></i> Add';
        addBtn.onclick = saveModalEntry;
    }
    
    // ✅ Clear all validation errors
    const modalInputs = document.querySelectorAll('#modalOverlay input, #modalOverlay select');
    modalInputs.forEach(input => {
        if (input.classList) {
            input.classList.remove('validation-error');
        }
    });
    
    console.log("✅ Modal closed and reset");
}

// function updateModalHours() {
//     const punchIn = document.getElementById('modalInput3').value;
//     const punchOut = document.getElementById('modalInput4').value;
//     const projectStart = document.getElementById('modalInput5').value;
//     const projectEnd = document.getElementById('modalInput6').value;

//     // Project Hours
//     let projectHours = "";
//     if (projectStart && projectEnd) {
//         const [sH, sM] = projectStart.split(":").map(Number);
//         const [eH, eM] = projectEnd.split(":").map(Number);

//         let s = sH * 60 + sM;
//         let e = eH * 60 + eM;
//         if (e < s) e += 24 * 60;

//         projectHours = ((e - s) / 60).toFixed(2);
//     }

//     // Working Hours
//     let workingHours = "";
//     if (punchIn && punchOut) {
//         const [inH, inM] = punchIn.split(":").map(Number);
//         const [outH, outM] = punchOut.split(":").map(Number);

//         let s = inH * 60 + inM;
//         let e = outH * 60 + outM;
//         if (e < s) e += 24 * 60;

//         workingHours = ((e - s) / 60).toFixed(2);
//     }

//     document.getElementById('modalInput12').value = projectHours;
//     document.getElementById('modalInput13').value = workingHours;
// }

function updateModalHours() {
    // REMOVED: const punchIn = document.getElementById('modalInput3').value;
    // REMOVED: const punchOut = document.getElementById('modalInput4').value;
    const projectStart = document.getElementById('modalInput3').value;  // Now index 3 (was 5)
    const projectEnd = document.getElementById('modalInput4').value;    // Now index 4 (was 6)

    // Project Hours calculation (UNCHANGED)
    let projectHours = "";
    if (projectStart && projectEnd) {
        const [sH, sM] = projectStart.split(":").map(Number);
        const [eH, eM] = projectEnd.split(":").map(Number);

        let s = sH * 60 + sM;
        let e = eH * 60 + eM;
        if (e < s) e += 24 * 60;

        projectHours = ((e - s) / 60).toFixed(2);
    }

    // REMOVED: Working Hours calculation
    // REMOVED: let workingHours = "";
    // REMOVED: if (punchIn && punchOut) { ... }

    document.getElementById('modalInput10').value = projectHours;  // Now index 10 (was 12)
    // REMOVED: document.getElementById('modalInput13').value = workingHours;
}


function saveModalEntry() {
    console.log("Saving modal entry. isEditingHistory:", isEditingHistory);
    if (!currentRow) return;

    if (isEditingHistory) {
        updateHistoryEntry();
        return;
    }
    
    const modalInputs = document.querySelectorAll('#modalOverlay input, #modalOverlay select');
    const rowInputs = currentRow.querySelectorAll('input, select');
    
    // ✅ FIX: Validate date BEFORE copying to row
    const dateInput = modalInputs[0]; // Date field
    if (dateInput && dateInput.value) {
        const isValid = validateModalDate(dateInput);
        if (!isValid) {
            // Don't close modal, let user fix the date
            return;
        }
    }
    
    // UPDATED LOOP (12 instead of 15)
    for (let i = 0; i < 12; i++) {
        if (!rowInputs[i]) continue;

        // input fields
        if (rowInputs[i].tagName === 'INPUT') {
            rowInputs[i].value = modalInputs[i].value;
        }

        // select fields
        if (rowInputs[i].tagName === 'SELECT') {
            rowInputs[i].value = modalInputs[i].value;
        }
    }

    calculateHours(currentRow);
    // ✅ FIX: Don't validate again, we already did it above
    closeModal();
    updateSummary();
}


function updateHistoryEntry() {
    console.log("📝 Updating history entry. currentEntryId:", currentEntryId);
    
    if (!currentRow || !currentEntryId) {
        console.error("❌ Missing currentRow or currentEntryId");
        showPopup("Error: Cannot update entry", true);
        return;
    }
    
    const modalInputs = document.querySelectorAll('#modalOverlay input, #modalOverlay select');
    
    if (modalInputs.length < 12) {
        console.error("❌ Not enough modal inputs:", modalInputs.length);
        showPopup("Error: Modal inputs missing", true);
        return;
    }
    
    // ✅ Collect data from modal (12 fields)
    const updateData = {
        date: modalInputs[0].value,
        location: modalInputs[1].value,
        projectStartTime: modalInputs[2].value,
        projectEndTime: modalInputs[3].value,
        client: modalInputs[4].value,
        project: modalInputs[5].value,
        projectCode: modalInputs[6].value,
        reportingManagerEntry: modalInputs[7].value,
        activity: modalInputs[8].value,
        projectHours: modalInputs[9].value,
        billable: modalInputs[10].value,
        remarks: modalInputs[11].value
    };

    console.log("📦 Update data:", updateData);
    
    // ✅ Validate required fields
    if (!updateData.date) {
        showPopup("Date is required", true);
        return;
    }

    showLoading("Updating entry...");

    fetch(`${API_URL}/update_timesheet/${loggedInEmployeeId}/${currentEntryId}`, {
        method: 'PUT',
        headers: getHeaders(),
        body: JSON.stringify(updateData)
    })
    .then(response => {
        console.log("API Response:", response.status);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: Failed to update entry`);
        }
        return response.json();
    })
    .then(result => {
        console.log("✅ Update result:", result);
        hideLoading();
        
        if (result.success) {
            showPopup('Entry updated successfully! 🎉');
            closeModal();
            
            // ✅ Reload history to show changes
            setTimeout(() => {
                showSection('history');
            }, 1000);
        } else {
            showPopup('Failed to update entry: ' + (result.message || 'Unknown error'), true);
        }
    })
    .catch(error => {
        console.error('❌ Error updating entry:', error);
        hideLoading();
        showPopup(`Failed to update entry: ${error.message}`, true);
    });
}

function updateSummary() {
    const sections = document.querySelectorAll('.timesheet-section');
    let totalHours = 0;
    let billableHours = 0;
    let nonBillableHours = 0;

    sections.forEach(section => {
        const rows = section.querySelectorAll('tbody tr');
        rows.forEach(row => {
            const hours = parseFloat(row.querySelector('.project-hours-field').value) || 0;
            totalHours += hours;
            if (row.querySelector('.billable-select').value === 'Yes') {
                billableHours += hours;
            } else if (row.querySelector('.billable-select').value === 'No') {
                nonBillableHours += hours;
            }
        });
    });

    const totalHoursElement = document.querySelector('.summary-section .total-hours .value');
    const billableHoursElement = document.querySelector('.summary-section .billable-hours .value');
    const nonBillableHoursElement = document.querySelector('.summary-section .non-billable-hours .value');
    if (totalHoursElement) totalHoursElement.textContent = totalHours.toFixed(2);
    if (billableHoursElement) billableHoursElement.textContent = billableHours.toFixed(2);
    if (nonBillableHoursElement) nonBillableHoursElement.textContent = nonBillableHours.toFixed(2);
}

function exportTimesheetToExcel() {
    const employeeInfo = getEmployeeInfoForExport();
    const wb = XLSX.utils.book_new();
  
    // UPDATED Columns (removed punchIn, punchOut, workingHours)
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
        // REMOVED: "punchIn",
        // REMOVED: "punchOut",
        "projectStartTime",
        "projectEndTime",
        "client",
        "project",
        "projectCode",
        "reportingManagerEntry",
        "activity",
        "projectHours",
        // REMOVED: "workingHours",
        "billable",
        "remarks",
        "hits",
        "misses",
        "feedback_hr",
        "feedback_it",
        "feedback_crm",
        "feedback_others"
    ];

    // UPDATED Pretty Headers (removed corresponding entries)
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
        // REMOVED: "Punch In",
        // REMOVED: "Punch Out",
        "Project Start Time",
        "Project End Time",
        "Client",
        "Project",
        "Project Code",
        "Reporting Manager Entry",
        "Activity",
        "Project Hours",
        // REMOVED: "Working Hours",
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

            // Detect empty row
            const date = inputs[0]?.value?.trim() || "";
            const project = inputs[5]?.value?.trim() || "";  // UPDATED INDEX (was 7)
            const client =
                inputs[4]?.value ||                          // UPDATED INDEX (was 6)
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
                // REMOVED: punchIn: inputs[4]?.value || "",
                // REMOVED: punchOut: inputs[5]?.value || "",
                projectStartTime: inputs[2]?.value || "",  // UPDATED INDEX (was 2, no change but context matters)
                projectEndTime: inputs[3]?.value || "",    // UPDATED INDEX (was 3)
                client: client,
                project: project,
                projectCode: inputs[6]?.value || "",       // UPDATED INDEX (was 8)
                reportingManagerEntry: inputs[7]?.value || "", // UPDATED INDEX (was 9)
                activity: inputs[8]?.value || "",          // UPDATED INDEX (was 10)
                projectHours: inputs[9]?.value || "",      // UPDATED INDEX (was 11)
                // REMOVED: workingHours: inputs[12]?.value || "",
                billable: inputs[10]?.value || "",         // UPDATED INDEX (was 13)
                remarks: inputs[11]?.value || "",          // UPDATED INDEX (was 14)
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

function exportHistoryToExcel() {
    if (!historyEntries || historyEntries.length === 0) {
        showPopup("No history available!");
        return;
    }

    // UPDATED Columns (removed punchIn, punchOut, workingHours)
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
        // REMOVED: "punchIn",
        // REMOVED: "punchOut",
        "projectStartTime",
        "projectEndTime",
        "client",
        "project",
        "projectCode",
        "reportingManagerEntry",
        "activity",
        "projectHours",
        // REMOVED: "workingHours",
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

    // UPDATED Header labels (removed corresponding entries)
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
        // REMOVED: "Punch In",
        // REMOVED: "Punch Out",
        "Project Start Time",
        "Project End Time",
        "Client",
        "Project",
        "Project Code",
        "Reporting Manager Entry",
        "Activity",
        "Project Hours",
        // REMOVED: "Working Hours",
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

    // UPDATED Prepare cleaned rows (removed corresponding entries)
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
        // REMOVED: punchIn: row.punchIn || "",
        // REMOVED: punchOut: row.punchOut || "",
        projectStartTime: row.projectStartTime || "",
        projectEndTime: row.projectEndTime || "",
        client: row.client || "",
        project: row.project || "",
        projectCode: row.projectCode || "",
        reportingManagerEntry: row.reportingManagerEntry || "",
        activity: row.activity || "",
        projectHours: row.projectHours || "",
        // REMOVED: workingHours: row.workingHours || "",
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

    const worksheet = XLSX.utils.json_to_sheet(cleanedRows, { header: columns });
    XLSX.utils.sheet_add_aoa(worksheet, [headersPretty], { origin: "A1" });

    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "History");

    const fileName = `History_${loggedInEmployeeId}_${new Date()
        .toISOString()
        .split("T")[0]}.xlsx`;

    XLSX.writeFile(workbook, fileName);

    showPopup("History exported successfully!");
}


// async function saveDataToMongo() {
//     showLoading();
//     const employeeId = document.getElementById('employeeId').value.trim();
//     if (!employeeId) {
//         hideLoading();
//         showPopup('Please enter Employee ID', true);
//         return;
//     }

//     // ✅ IMPROVED: Check for empty dates AND skip completely empty rows
//     const allDateInputs = document.querySelectorAll('.date-field');
//     let hasEmptyDates = false;
    
//     allDateInputs.forEach(dateInput => {
//         const row = dateInput.closest('tr');
        
//         // Get all inputs except the date field itself and action buttons
//         const otherInputs = Array.from(row.querySelectorAll('input, select'))
//             .filter(input => 
//                 !input.classList.contains('date-field') && 
//                 !input.classList.contains('copy-btn') && 
//                 !input.classList.contains('paste-btn') &&
//                 !input.classList.contains('delete-btn') &&
//                 input.type !== 'button'
//             );
        
//         // Check if any other field has data
//         const hasAnyData = otherInputs.some(input => {
//             if (input.tagName === 'SELECT') {
//                 return input.value && input.value.trim() !== '';
//             }
//             return input.value && input.value.trim() !== '';
//         });
        
//         // Only validate if the row has other data
//         if (hasAnyData && !dateInput.value) {
//             hasEmptyDates = true;
//             dateInput.classList.add('validation-error');
//             showValidationMessage(dateInput, 'Date is required');
//         }
//     });
    
//     if (hasEmptyDates) {
//         hideLoading();
//         showPopup('Please fill all date fields before submitting!', true);
//         return;
//     }

//     // ✅ Check for validation errors
//     let hasWeekRangeErrors = false;
//     let has60DaysErrors = false;
//     let errorMessages = [];
    
//     allDateInputs.forEach(dateInput => {
//         if (dateInput.value) {
//             // Check week range
//             const isWeekValid = validateDate(dateInput);
//             if (!isWeekValid) {
//                 hasWeekRangeErrors = true;
//             }
            
//             // Check 60 days rule
//             const is60DaysValid = validate60DaysRule(dateInput);
//             if (!is60DaysValid) {
//                 has60DaysErrors = true;
//                 errorMessages.push(`Date ${dateInput.value} is not within last 60 days up to yesterday`);
//             }
//         }
//     });
    
//     if (hasWeekRangeErrors) {
//         hideLoading();
//         showPopup('Please fix all date validation errors (dates must be within selected week range)!', true);
//         return;
//     }
    
//     if (has60DaysErrors) {
//         hideLoading();
//         showPopup('Some dates are not within last 60 days up to yesterday. Please correct them before submitting.', true);
//         return;
//     }

//     const timesheetData = [];
//     const employeeDataObj = {
//         employeeId: employeeId,
//         employeeName: document.getElementById('employeeName').value || '',
//         designation: document.getElementById('designation').value || '',
//         gender: document.getElementById('gender').value || '',
//         partner: document.getElementById('partner').value || '',
//         reportingManager: document.getElementById('reportingManager').value || '',
//         weekPeriod: '',
//         date: '',
//         location: '',
//         projectStartTime: '',
//         projectEndTime: '',
//         client: '',
//         project: '',
//         projectCode: '',
//         reportingManagerEntry: '',
//         activity: '',
//         projectHours: '',
//         billable: '',
//         remarks: '',
//         hits: document.getElementById('hits').value || '',
//         misses: document.getElementById('misses').value || '',
//         feedback_hr: document.getElementById('feedback_hr').value || '',
//         feedback_it: document.getElementById('feedback_it').value || '',
//         feedback_crm: document.getElementById('feedback_crm').value || '',
//         feedback_others: document.getElementById('feedback_others').value || '',
//         totalHours: document.querySelector('.summary-section .total-hours .value').textContent || '0.00',
//         totalBillableHours: document.querySelector('.summary-section .billable-hours .value').textContent || '0.00',
//         totalNonBillableHours: document.querySelector('.summary-section .non-billable-hours .value').textContent || '0.00'
//     };

//     const sections = document.querySelectorAll('.timesheet-section');
//     let hasMissingFields = false;
//     let errorMessagesForFields = [];
    
//     sections.forEach(section => {
//         const weekPeriod = section.querySelector('.week-period select').value || '';
//         const rows = section.querySelectorAll('tbody tr');
        
//         rows.forEach(row => {
//             const inputs = row.querySelectorAll('input, select');
//             if (inputs.length < 12) return;
            
//             const dateInput = inputs[0];

//             // ✅ SKIP COMPLETELY EMPTY ROWS
//             const rowHasAnyData = Array.from(inputs).some(input => {
//                 if (input.type === 'button') return false;
//                 if (input.classList.contains('copy-btn') || 
//                     input.classList.contains('paste-btn') || 
//                     input.classList.contains('delete-btn')) return false;
//                 return input.value && input.value.trim() !== '';
//             });
            
//             if (!rowHasAnyData) {
//                 console.log('Skipping completely empty row');
//                 return; // Skip this empty row
//             }

//             // Skip if no date
//             if (!dateInput.value || dateInput.value.trim() === '') {
//                 console.log('Skipping row with no date');
//                 return;
//             }

//             // ✅ ONLY validate mandatory fields if date exists (row has data)
//             const mandatoryFields = {
//                 'Project Start Time': inputs[2].value,
//                 'Project End Time': inputs[3].value,
//                 'Client': inputs[4].value,
//                 'Project': inputs[5].value,
//                 'Project Code': inputs[6].value,
//                 'Reporting Manager': inputs[7].value,
//                 'Activity': inputs[8].value
//             };

//             for (let [fieldName, value] of Object.entries(mandatoryFields)) {
//                 if (!value || value.trim() === '') {
//                     hasMissingFields = true;
//                     errorMessagesForFields.push(`Please fill in the ${fieldName} field for the row dated ${dateInput.value || 'N/A'}.`);
//                 }
//             }

//             const client = inputs[4].value || inputs[4].querySelector('option:checked')?.value || '';
//             const project = inputs[5].value;
//             const projectCode = inputs[6].value;
            
//             console.log(`Collecting row: date=${dateInput.value}, client=${client}, project=${project}`);
            
//             const rowData = {
//                 employeeId: employeeId,
//                 employeeName: document.getElementById('employeeName').value || '',
//                 designation: document.getElementById('designation').value || '',
//                 gender: document.getElementById('gender').value || '',
//                 partner: document.getElementById('partner').value || '',
//                 reportingManager: document.getElementById('reportingManager').value || '',
//                 weekPeriod: weekPeriod,
//                 date: inputs[0].value,
//                 location: inputs[1].value || inputs[1].querySelector('option:checked')?.value,
//                 projectStartTime: inputs[2].value,
//                 projectEndTime: inputs[3].value,
//                 client: client,
//                 project: project,
//                 projectCode: projectCode,
//                 reportingManagerEntry: inputs[7].value || '',
//                 activity: inputs[8].value,
//                 projectHours: inputs[9].value,
//                 billable: inputs[10].value,
//                 remarks: inputs[11].value,
//                 hits: document.getElementById('hits').value || '',
//                 misses: document.getElementById('misses').value || '',
//                 feedback_hr: document.getElementById('feedback_hr').value || '',
//                 feedback_it: document.getElementById('feedback_it').value || '',
//                 feedback_crm: document.getElementById('feedback_crm').value || '',
//                 feedback_others: document.getElementById('feedback_others').value || '',
//                 totalHours: document.querySelector('.summary-section .total-hours .value').textContent || '0.00',
//                 totalBillableHours: document.querySelector('.summary-section .billable-hours .value').textContent || '0.00',
//                 totalNonBillableHours: document.querySelector('.summary-section .non-billable-hours .value').textContent || '0.00'
//             };
            
//             console.log('Pushing row data:', rowData);
//             timesheetData.push(rowData);
//         });
//     });

//     if (hasMissingFields) {
//         hideLoading();
//         showPopup(errorMessagesForFields.join('\n'), true);
//         return;
//     }

//     if (timesheetData.length === 0) {
//         console.log('No data collected, using employee data object');
//         timesheetData.push(employeeDataObj);
//     }

//     console.log('=== PRE-SAVE VALIDATION ===');
//     console.log('Total entries to save:', timesheetData.length);
//     console.log('Timesheet data:', timesheetData);

//     try {
//         const token = localStorage.getItem('access_token');
        
//         console.log('=== SAVING TIMESHEET ===');
//         console.log('Employee ID:', employeeId);
//         console.log('API URL:', `${API_URL}/save_timesheets`);
//         console.log('Headers:', getHeaders());
        
//         const response = await fetch(`${API_URL}/save_timesheets`, {
//             method: 'POST',
//             headers: getHeaders(),
//             body: JSON.stringify(timesheetData)
//         });

//         console.log('Response Status:', response.status);
//         console.log('Response OK:', response.ok);

//         if (!response.ok) {
//             const errorText = await response.text();
//             console.error('=== API ERROR ===');
//             console.error('Status:', response.status);
//             console.error('Response:', errorText);
            
//             let errorData;
//             try {
//                 errorData = JSON.parse(errorText);
//             } catch (e) {
//                 errorData = { detail: errorText };
//             }
            
//             hideLoading();
//             showPopup(`Failed to save: ${errorData.detail || 'Unknown error'}`, true);
//             throw new Error(`Failed to save data: ${errorData.detail || 'Unknown error'}`);
//         }

//         const result = await response.json();
//         console.log('=== SAVE SUCCESS ===');
//         console.log('Result:', result);
        
//         hideLoading();
//         showPopup('Timesheet saved successfully!');
//         setTimeout(() => {
//             window.location.reload();
//         }, 2000);
//     } catch (error) {
//         console.error('=== CATCH ERROR ===');
//         console.error('Error saving data:', error);
//         hideLoading();
//         showPopup(`Failed to save timesheet: ${error.message}`, true);
//     }
// }

async function saveDataToMongo() {
    console.log("🚀 saveDataToMongo() called");
    showLoading("Saving timesheet...");
    
    const employeeId = document.getElementById('employeeId').value.trim();
    console.log("📌 Employee ID:", employeeId);
    
    if (!employeeId) {
        hideLoading();
        showPopup('Please enter Employee ID', true);
        return;
    }

    // ✅ Check for empty dates AND skip completely empty rows
    const allDateInputs = document.querySelectorAll('.date-field');
    let hasEmptyDates = false;
    
    allDateInputs.forEach(dateInput => {
        const row = dateInput.closest('tr');
        
        // Get all inputs except the date field itself and action buttons
        const otherInputs = Array.from(row.querySelectorAll('input, select'))
            .filter(input => 
                !input.classList.contains('date-field') && 
                !input.classList.contains('copy-btn') && 
                !input.classList.contains('paste-btn') &&
                !input.classList.contains('delete-btn') &&
                input.type !== 'button'
            );
        
        // Check if any other field has data
        const hasAnyData = otherInputs.some(input => {
            if (input.tagName === 'SELECT') {
                return input.value && input.value.trim() !== '';
            }
            return input.value && input.value.trim() !== '';
        });
        
        // Only validate if the row has other data
        if (hasAnyData && !dateInput.value) {
            hasEmptyDates = true;
            dateInput.classList.add('validation-error');
            showValidationMessage(dateInput, 'Date is required');
        }
    });
    
    if (hasEmptyDates) {
        hideLoading();
        showPopup('Please fill all date fields before submitting!', true);
        return;
    }

    // ✅ Check for validation errors
    let hasWeekRangeErrors = false;
    let errorMessages = [];
    
    allDateInputs.forEach(dateInput => {
        if (dateInput.value) {
            // Check week range
            const isWeekValid = validateDate(dateInput);
            if (!isWeekValid) {
                hasWeekRangeErrors = true;
            }
        }
    });
    
    if (hasWeekRangeErrors) {
        hideLoading();
        showPopup('Please fix all date validation errors (dates must be within selected week range)!', true);
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
    let hasMissingFields = false;
    let errorMessagesForFields = [];
    
    sections.forEach(section => {
        const weekPeriod = section.querySelector('.week-period select').value || '';
        console.log("📅 Processing week period:", weekPeriod);
        
        const rows = section.querySelectorAll('tbody tr');
        
        rows.forEach(row => {
            const inputs = row.querySelectorAll('input, select');
            if (inputs.length < 12) return;
            
            const dateInput = inputs[0];

            // ✅ SKIP COMPLETELY EMPTY ROWS
            const rowHasAnyData = Array.from(inputs).some(input => {
                if (input.type === 'button') return false;
                if (input.classList.contains('copy-btn') || 
                    input.classList.contains('paste-btn') || 
                    input.classList.contains('delete-btn')) return false;
                return input.value && input.value.trim() !== '';
            });
            
            if (!rowHasAnyData) {
                console.log('⏭️ Skipping completely empty row');
                return; // Skip this empty row
            }

            // Skip if no date
            if (!dateInput.value || dateInput.value.trim() === '') {
                console.log('⏭️ Skipping row with no date');
                return;
            }

            // ✅ ONLY validate mandatory fields if date exists (row has data)
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
                    errorMessagesForFields.push(`Please fill in the ${fieldName} field for the row dated ${dateInput.value || 'N/A'}.`);
                }
            }

            const client = inputs[4].value || inputs[4].querySelector('option:checked')?.value || '';
            const project = inputs[5].value;
            const projectCode = inputs[6].value;
            
            console.log(`✅ Collecting row: date=${dateInput.value}, client=${client}, project=${project}`);
            
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
            
            console.log('📦 Pushing row data:', rowData);
            timesheetData.push(rowData);
        });
    });

    if (hasMissingFields) {
        hideLoading();
        showPopup(errorMessagesForFields.join('\n'), true);
        return;
    }

    if (timesheetData.length === 0) {
        console.log('⚠️ No data collected, using employee data object');
        timesheetData.push(employeeDataObj);
    }

    console.log('=== PRE-SAVE VALIDATION ===');
    console.log('Total entries to save:', timesheetData.length);
    console.log('Timesheet data:', JSON.stringify(timesheetData, null, 2));

    try {
        const token = localStorage.getItem('access_token');
        
        console.log('=== SAVING TIMESHEET ===');
        console.log('Employee ID:', employeeId);
        console.log('API URL:', `${API_URL}/save_timesheets`);
        console.log('Token:', token ? 'Present' : 'Missing');
        
        const response = await fetch(`${API_URL}/save_timesheets`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(timesheetData)
        });

        console.log('Response Status:', response.status);
        console.log('Response OK:', response.ok);

        if (!response.ok) {
            const errorText = await response.text();
            console.error('=== API ERROR ===');
            console.error('Status:', response.status);
            console.error('Response:', errorText);
            
            let errorData;
            try {
                errorData = JSON.parse(errorText);
            } catch (e) {
                errorData = { detail: errorText };
            }
            
            hideLoading();
            showPopup(`Failed to save: ${errorData.detail || 'Unknown error'}`, true);
            throw new Error(`Failed to save data: ${errorData.detail || 'Unknown error'}`);
        }

        const result = await response.json();
        console.log('=== SAVE SUCCESS ===');
        console.log('Result:', result);
        
        hideLoading();
        showPopup('Timesheet saved successfully!');
        isExiting = true;
        formModified = false;

        setTimeout(() => {
           window.location.replace('/dashboard');
        }, 2000);
    } catch (error) {
        console.error('=== CATCH ERROR ===');
        console.error('Error saving data:', error);
        hideLoading();
        showPopup(`Failed to save timesheet: ${error.message}`, true);
    }
}


function clearTimesheet() {
    showPopup('Timesheet cleared!');
    document.getElementById('hits').value = '';
    document.getElementById('misses').value = '';
    document.getElementById('feedback_hr').value = '';
    document.getElementById('feedback_it').value = '';
    document.getElementById('feedback_crm').value = '';
    document.getElementById('feedback_others').value = '';
    setTimeout(() => {
        window.location.replace('/dashboard');
    }, 3000);
}

function toggleNavMenu() {
    const navMenu = document.getElementById('navMenu');
    navMenu.classList.toggle('active');
}

async function logout() {
    showLoading("Logging out...");
    try {
        const token = localStorage.getItem('access_token');
        await fetch(`${API_URL}/logout`, {
            method: 'POST',
            headers: getHeaders()
        });
    } catch (error) {
        console.error('Error during logout:', error);
    } finally {
        hideLoading();
        localStorage.removeItem('access_token');
        localStorage.removeItem('loggedInEmployeeId');
        window.location.href = '/static/login.html';
    }
}

async function showSection(section) {
    // Hide all sections first
    document.getElementById('timesheetSection').style.display = 'none';
    document.getElementById('historySection').style.display = 'none';
    document.getElementById('pendingSection').style.display = 'none';
    document.getElementById('approveSection').style.display = 'none';
    document.getElementById('rejectedSection').style.display = 'none';
    
    // Remove active class from all nav links
    document.querySelectorAll('.nav-menu a').forEach(a => a.classList.remove('active'));
    
    // Add active class to clicked section
    const activeLink = document.querySelector(`.nav-menu a[onclick*="${section}"]`);
    if (activeLink) {
        activeLink.classList.add('active');
    }

    // Show the selected section
    if (section === 'timesheet') {
        document.getElementById('timesheetSection').style.display = 'block';
    } 
    else if (section === 'history') {
        document.getElementById('historySection').style.display = 'block';
        await loadHistoryData();
    }
    else if (section === 'pending') {
        document.getElementById('pendingSection').style.display = 'block';
        await loadPendingData();
    }
    else if (section === 'approve') {
        document.getElementById('approveSection').style.display = 'block';
        await loadApprovedData();
    }
    else if (section === 'rejected') {
        document.getElementById('rejectedSection').style.display = 'block';
        await loadRejectedData();
    }
}

// Separate function for loading history
async function loadHistoryData() {
    try {
        showLoading("Fetching History...");
        const response = await fetch(`${API_URL}/timesheets/${loggedInEmployeeId}`, {
            headers: getHeaders()
        });

        if (!response.ok) {
            throw new Error('Failed to fetch history');
        }

        const data = await response.json();
        historyEntries = Array.isArray(data.Data) ? data.Data : [];
        console.log('API Response:', data);
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
                        <!-- REMOVED: <th class="col-narrow col-working-hours">Working Hours</th> -->
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
                    <!-- REMOVED: <td class="col-working-hours">${entry.workingHours || ''}</td> -->
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

// Manager section data loaders
async function loadPendingData() {
    try {
        showLoading("Loading Pending Employees...");
        const response = await fetch(`${API_URL}/get_pending_employees/${loggedInEmployeeId}`, {
            headers: getHeaders()
        });
        
        if (!response.ok) throw new Error('Failed to fetch pending employees');
        
        const data = await response.json();
        const tbody = document.getElementById('pendingTableBody');
        tbody.innerHTML = '';
        
        if (!data.employees || data.employees.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3">No pending approvals</td></tr>';
        } else {
            data.employees.forEach(emp => {
                const row = `
                    <tr>
                        <td>${emp.employeeId}</td>
                        <td>${emp.timesheetData?.employeeName || 'N/A'}</td>
                        <td>
                            <button class="action-btn edit-btn" onclick="viewEmployeeTimesheet('${emp.employeeId}')">
                                <i class="fas fa-eye"></i> View
                            </button>
                            <button class="action-btn approve-btn" onclick="approveEmployee('${loggedInEmployeeId}', '${emp.employeeId}')">
                                <i class="fas fa-check"></i> Approve
                            </button>
                            <button class="action-btn delete-btn" onclick="rejectEmployee('${loggedInEmployeeId}', '${emp.employeeId}')">
                                <i class="fas fa-times"></i> Reject
                            </button>
                        </td>
                    </tr>
                `;
                tbody.innerHTML += row;
            });
        }
        hideLoading();
    } catch (error) {
        console.error('Error loading pending data:', error);
        hideLoading();
        showPopup('Failed to load pending employees', true);
    }
}

async function loadApprovedData() {
    try {
        showLoading("Loading Approved Employees...");
        const response = await fetch(`${API_URL}/get_approved_employees/${loggedInEmployeeId}`, {
            headers: getHeaders()
        });
        
        if (!response.ok) throw new Error('Failed to fetch approved employees');
        
        const data = await response.json();
        const tbody = document.getElementById('approveTableBody');
        tbody.innerHTML = '';
        
        if (!data.employees || data.employees.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3">No approved employees</td></tr>';
        } else {
            data.employees.forEach(emp => {
                const row = `
                    <tr>
                        <td>${emp.employeeId}</td>
                        <td>${emp.timesheetData?.employeeName || 'N/A'}</td>
                        <td>
                            <button class="action-btn edit-btn" onclick="viewEmployeeTimesheet('${emp.employeeId}')">
                                <i class="fas fa-eye"></i> View
                            </button>
                        </td>
                    </tr>
                `;
                tbody.innerHTML += row;
            });
        }
        hideLoading();
    } catch (error) {
        console.error('Error loading approved data:', error);
        hideLoading();
        showPopup('Failed to load approved employees', true);
    }
}

async function loadRejectedData() {
    try {
        showLoading("Loading Rejected Employees...");
        const response = await fetch(`${API_URL}/get_rejected_employees/${loggedInEmployeeId}`, {
            headers: getHeaders()
        });
        
        if (!response.ok) throw new Error('Failed to fetch rejected employees');
        
        const data = await response.json();
        const tbody = document.getElementById('rejectedTableBody');
        tbody.innerHTML = '';
        
        if (!data.employees || data.employees.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3">No rejected employees</td></tr>';
        } else {
            data.employees.forEach(emp => {
                const row = `
                    <tr>
                        <td>${emp.employeeId}</td>
                        <td>${emp.timesheetData?.employeeName || 'N/A'}</td>
                        <td>
                            <button class="action-btn edit-btn" onclick="viewEmployeeTimesheet('${emp.employeeId}')">
                                <i class="fas fa-eye"></i> View
                            </button>
                        </td>
                    </tr>
                `;
                tbody.innerHTML += row;
            });
        }
        hideLoading();
    } catch (error) {
        console.error('Error loading rejected data:', error);
        hideLoading();
        showPopup('Failed to load rejected employees', true);
    }
}

async function approveEmployee(managerCode, employeeCode) {
    try {
        showLoading("Approving...");
        const response = await fetch(`${API_URL}/approve_timesheet`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                reporting_emp_code: managerCode,
                employee_code: employeeCode
            })
        });
        
        const result = await response.json();
        hideLoading();
        
        if (result.success) {
            showPopup('Employee approved successfully!');
            await loadPendingData();
        } else {
            showPopup('Failed to approve employee', true);
        }
    } catch (error) {
        console.error('Error approving employee:', error);
        hideLoading();
        showPopup('Failed to approve employee', true);
    }
}

async function rejectEmployee(managerCode, employeeCode) {
    if (!confirm('Are you sure you want to reject this employee?')) return;
    
    try {
        showLoading("Rejecting...");
        const response = await fetch(`${API_URL}/reject_timesheet`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({
                reporting_emp_code: managerCode,
                employee_code: employeeCode
            })
        });
        
        const result = await response.json();
        hideLoading();
        
        if (result.success) {
            showPopup('Employee rejected successfully!');
            await loadPendingData(); 
        } else {
            showPopup('Failed to reject employee', true);
        }
    } catch (error) {
        console.error('Error rejecting employee:', error);
        hideLoading();
        showPopup('Failed to reject employee', true);
    }
}

function viewEmployeeTimesheet(employeeId) {
    // Open in new tab
    window.open(`${API_URL}/view_timesheet/${employeeId}`, '_blank');
}


function editHistoryRow(button, entryId) {
    console.log("✏️ Editing entry ID:", entryId);
    
    const row = button.closest('tr');
    if (!row) {
        console.error("❌ Row not found");
        showPopup("Error: Row not found", true);
        return;
    }
    
    currentRow = row;
    isEditingHistory = true;
    currentEntryId = entryId;
    
    const cells = row.querySelectorAll('td');
    console.log("📊 Cells found:", cells.length);
    
    // ✅ First show the modal
    document.getElementById('modalOverlay').style.display = 'flex';
    
    // ✅ Wait for modal to be visible, then populate
    setTimeout(() => {
        const modalInputs = document.querySelectorAll('#modalOverlay input, #modalOverlay select');
        console.log("📝 Modal inputs found:", modalInputs.length);
        
        if (modalInputs.length < 12) {
            console.error("❌ Not enough modal inputs");
            showPopup("Error: Modal not initialized properly", true);
            closeModal();
            return;
        }
        
        try {
            // ✅ Map table cells to modal inputs (12 fields)
            // History table structure:
            // cells[0] = S.No
            // cells[1] = Action buttons
            // cells[2] = Date
            // cells[3] = Location
            // cells[4] = Project Start Time
            // cells[5] = Project End Time
            // cells[6] = Client
            // cells[7] = Project
            // cells[8] = Project Code
            // cells[9] = Reporting Manager
            // cells[10] = Activity
            // cells[11] = Project Hours
            // cells[12] = Billable
            // cells[13] = Remarks
            
            modalInputs[0].value = cells[2].textContent.trim();   // Date
            modalInputs[1].value = cells[3].textContent.trim();   // Location
            modalInputs[2].value = cells[4].textContent.trim();   // Project Start
            modalInputs[3].value = cells[5].textContent.trim();   // Project End
            modalInputs[4].value = cells[6].textContent.trim();   // Client
            modalInputs[5].value = cells[7].textContent.trim();   // Project
            modalInputs[6].value = cells[8].textContent.trim();   // Project Code
            modalInputs[7].value = cells[9].textContent.trim();   // Reporting Manager
            modalInputs[8].value = cells[10].textContent.trim();  // Activity
            modalInputs[9].value = cells[11].textContent.trim();  // Project Hours
            modalInputs[10].value = cells[12].textContent.trim(); // Billable
            modalInputs[11].value = cells[13].textContent.trim(); // Remarks
            
            console.log("✅ Modal populated with values");
            
            // ✅ Now validate date (after values are set)
            const dateInput = document.getElementById('modalInput1');
            if (dateInput) {
                // Clear any validation first
                dateInput.classList.remove('validation-error');
                clearValidationMessage(dateInput);
                console.log("✅ Date validation cleared");
            }
            
            // ✅ Update hours calculation
            updateModalHours();
            
            // ✅ Change button to "Update"
            const addBtn = document.getElementById('modalAddBtn');
            if (addBtn) {
                addBtn.innerHTML = '<i class="fas fa-check"></i> Update';
                addBtn.onclick = updateHistoryEntry;
            }
            
            console.log("✅ Edit mode ready");
            
        } catch (error) {
            console.error("❌ Error populating modal:", error);
            showPopup("Error loading entry data: " + error.message, true);
            closeModal();
        }
    }, 100); // Small delay to ensure modal is rendered
}

// 11. UPDATE validateTimes function (around line 1400)
// function validateTimes(row, isModal = false) {
//     let isValid = true;
//     let errorMessage = '';

//     if (isModal) {
//         const projectStart = document.getElementById('modalInput3').value;  
//         const projectEnd = document.getElementById('modalInput4').value;    

//         if (projectStart && projectEnd) {
//             const [startH, startM] = projectStart.split(':').map(Number);
//             const [endH, endM] = projectEnd.split(':').map(Number);
//             let startMinutes = startH * 60 + startM;
//             let endMinutes = endH * 60 + endM;
//             if (endMinutes < startMinutes) endMinutes += 24 * 60;
//             if (endMinutes <= startMinutes) {
//                 isValid = false;
//                 errorMessage = 'Project End Time must be later than Project Start Time.';
//                 document.getElementById('modalInput4').classList.add('validation-error');  
//                 showValidationMessage(document.getElementById('modalInput4'), errorMessage);
//             } else {
//                 document.getElementById('modalInput4').classList.remove('validation-error');
//                 clearValidationMessage(document.getElementById('modalInput4'));
//             }
//         }

//     } else {
//         const projectStart = row.querySelector('.project-start')?.value;
//         const projectEnd = row.querySelector('.project-end')?.value;

//         if (projectStart && projectEnd) {
//             const [startH, startM] = projectStart.split(':').map(Number);
//             const [endH, endM] = projectEnd.split(':').map(Number);
//             let startMinutes = startH * 60 + startM;
//             let endMinutes = endH * 60 + endM;
//             if (endMinutes < startMinutes) endMinutes += 24 * 60;
//             if (endMinutes <= startMinutes) {
//                 isValid = false;
//                 errorMessage = 'Project End Time must be later than Project Start Time.';
//                 row.querySelector('.project-end').classList.add('validation-error');
//                 showValidationMessage(row.querySelector('.project-end'), errorMessage);
//             } else {
//                 row.querySelector('.project-end').classList.remove('validation-error');
//                 clearValidationMessage(row.querySelector('.project-end'));
//             }
//         }
//     }

//     if (!isValid && errorMessage) {
//         showPopup(errorMessage, true);
//     }

//     return isValid;
// }


function deleteHistoryRow(button, entryId) {
    if (confirm('Are you sure you want to delete this entry?')) {
        fetch(`${API_URL}/delete_timesheet/${loggedInEmployeeId}/${entryId}`, {
            method: 'DELETE',
            headers: getHeaders()
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to delete entry');
            }
            return response.json();
        })
        .then(result => {
            if (result.success) {
                showPopup('Entry deleted successfully!');
                showSection('history'); // Reload history
            } else {
                showPopup('Failed to delete entry.', true);
            }
        })
        .catch(error => {
            console.error('Error deleting entry:', error);
            showPopup(`Failed to delete entry: ${error.message}`, true);
        });
    }
}

function validateTimes(row, isModal = false) {
    let isValid = true;
    let errorMessage = '';

    if (isModal) {
        const projectStart = document.getElementById('modalInput5').value;
        const projectEnd = document.getElementById('modalInput6').value;
        const punchIn = document.getElementById('modalInput3').value;
        const punchOut = document.getElementById('modalInput4').value;

        if (projectStart && projectEnd) {
            const [startH, startM] = projectStart.split(':').map(Number);
            const [endH, endM] = projectEnd.split(':').map(Number);
            let startMinutes = startH * 60 + startM;
            let endMinutes = endH * 60 + endM;
            if (endMinutes < startMinutes) endMinutes += 24 * 60; 
            if (endMinutes <= startMinutes) {
                isValid = false;
                errorMessage = 'Project End Time must be later than Project Start Time.';
                document.getElementById('modalInput6').classList.add('validation-error');
                showValidationMessage(document.getElementById('modalInput6'), errorMessage);
            } else {
                document.getElementById('modalInput6').classList.remove('validation-error');
                clearValidationMessage(document.getElementById('modalInput6'));
            }
        }

        if (punchIn && punchOut) {
            const [inH, inM] = punchIn.split(':').map(Number);
            const [outH, outM] = punchOut.split(':').map(Number);
            let inMinutes = inH * 60 + inM;
            let outMinutes = outH * 60 + outM;
            if (outMinutes < inMinutes) outMinutes += 24 * 60;
            if (outMinutes <= inMinutes) {
                isValid = false;
                errorMessage = errorMessage || 'Punch Out must be later than Punch In.';
                document.getElementById('modalInput4').classList.add('validation-error');
                showValidationMessage(document.getElementById('modalInput4'), errorMessage);
            } else {
                document.getElementById('modalInput4').classList.remove('validation-error');
                clearValidationMessage(document.getElementById('modalInput4'));
            }
        }
    } else {
        const projectStart = row.querySelector('.project-start')?.value;
        const projectEnd = row.querySelector('.project-end')?.value;
        const punchIn = row.querySelector('.punch-in')?.value;
        const punchOut = row.querySelector('.punch-out')?.value;

        if (projectStart && projectEnd) {
            const [startH, startM] = projectStart.split(':').map(Number);
            const [endH, endM] = projectEnd.split(':').map(Number);
            let startMinutes = startH * 60 + startM;
            let endMinutes = endH * 60 + endM;
            if (endMinutes < startMinutes) endMinutes += 24 * 60; // Handle next day
            if (endMinutes <= startMinutes) {
                isValid = false;
                errorMessage = 'Project End Time must be later than Project Start Time.';
                row.querySelector('.project-end').classList.add('validation-error');
                showValidationMessage(row.querySelector('.project-end'), errorMessage);
            } else {
                row.querySelector('.project-end').classList.remove('validation-error');
                clearValidationMessage(row.querySelector('.project-end'));
            }
        }

        if (punchIn && punchOut) {
            const [inH, inM] = punchIn.split(':').map(Number);
            const [outH, outM] = punchOut.split(':').map(Number);
            let inMinutes = inH * 60 + inM;
            let outMinutes = outH * 60 + outM;
            if (outMinutes < inMinutes) outMinutes += 24 * 60; // Handle next day
            if (outMinutes <= inMinutes) {
                isValid = false;
                errorMessage = errorMessage || 'Punch Out must be later than Punch In.';
                row.querySelector('.punch-out').classList.add('validation-error');
                showValidationMessage(row.querySelector('.punch-out'), errorMessage);
            } else {
                row.querySelector('.punch-out').classList.remove('validation-error');
                clearValidationMessage(row.querySelector('.punch-out'));
            }
        }
    }

    if (!isValid && errorMessage) {
        showPopup(errorMessage, true);
    }

    return isValid;
}

let isExiting = false;
window.addEventListener('beforeunload', function(e) {
    if (!isExiting) {
        e.preventDefault();
        e.returnValue = '';
        showExitConfirmation();
        return 'Are you sure you want to leave?';
    }
});

document.addEventListener('keydown', function(e) {
    if (e.key === 'Backspace' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
        e.preventDefault();
        showExitConfirmation();
    }
});
function showExitConfirmation() {
    const exitPopup = document.getElementById('exitConfirmation');
    if (exitPopup) {
        exitPopup.style.display = 'block';
    }
}
function cancelExit() {
    const exitPopup = document.getElementById('exitConfirmation');
    if (exitPopup) {
        exitPopup.style.display = 'none';
    }
}
function confirmExit() {
    isExiting = true;
    logout();
}

// New function to copy row data

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
    const tbody = document.getElementById(`timesheetBody_${sectionId.split('_')[1]}`);
    if (!tbody) {
        showPopup('Table body not found!', true);
        return;
    }
    
    const rows = tbody.querySelectorAll('tr');
    if (rows.length === 0) {
        showPopup('No rows to duplicate! Adding a new row.', true);
        addRow(sectionId);
        return;
    }
    
    const lastRow = rows[rows.length - 1];
    const newRow = document.createElement('tr');
    newRow.innerHTML = lastRow.innerHTML; 
    
    // Insert the new row into the DOM before validations
    tbody.insertBefore(newRow, lastRow.nextSibling);
    
    // Get inputs from the new row and last row
    const newInputs = newRow.querySelectorAll('input, select');
    const lastInputs = lastRow.querySelectorAll('input, select');
    
    // Get week info for date validation
    const weekSelect = document.getElementById(`weekPeriod_${sectionId.split('_')[1]}`);
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect?.value);
    
    // Copy values and handle validations
    newInputs.forEach((input, index) => {
        if (input.type === 'button' || input.classList.contains('copy-btn') || 
            input.classList.contains('paste-btn') || input.classList.contains('delete-btn')) {
            return; // Skip buttons
        }
        if (lastInputs[index]) {
            input.value = lastInputs[index].value; // Copy value from last row
            
            if (input.classList.contains('date-field')) {
                if (selectedWeek) {
                    const currentDate = new Date(input.value);
                    const weekEnd = new Date(selectedWeek.end);
                    
                    // Set min and max dates
                    const weekStart = new Date(selectedWeek.start);
                    const minDate = `${weekStart.getFullYear()}-${String(weekStart.getMonth() + 1).padStart(2, '0')}-${String(weekStart.getDate()).padStart(2, '0')}`;
                    const maxDate = `${weekEnd.getFullYear()}-${String(weekEnd.getMonth() + 1).padStart(2, '0')}-${String(weekEnd.getDate()).padStart(2, '0')}`;
                    
                    input.setAttribute('min', minDate);
                    input.setAttribute('max', maxDate);
                    
                    // If current date is within week and not at end, increment by 1 day
                    if (currentDate < weekEnd) {
                        currentDate.setDate(currentDate.getDate() + 1);
                        
                        // Check if new date is still within week
                        if (currentDate <= weekEnd) {
                            input.value = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, '0')}-${String(currentDate.getDate()).padStart(2, '0')}`;
                        }
                    }
                    
                    // ❌ REMOVED: No validation on paste
                    // Clear any validation styling
                    input.classList.remove('validation-error');
                    clearValidationMessage(input);
                }
            }
            if (input.classList.contains('project-start') || input.classList.contains('project-end')) {
                validateTimes(newRow);
                calculateHours(newRow);
            }
        }
    });
    
    updateRowNumbers(tbody.id);
    updateSummary();
    showPopup('Row duplicated above last row!');
}



function addWeekSection() {
    sectionCount++;

    // RECOMPUTE WEEK OPTIONS EVERY TIME
    const payroll = getPayrollPeriod();
    weekOptions = generateWeekOptions(payroll.start, payroll.end);

    const sectionsDiv = document.getElementById('timesheetSections');
    const sectionId = `section_${sectionCount}`;

    const section = document.createElement('div');
    section.className = 'timesheet-section';
    section.id = sectionId;

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'delete-week-btn';
    deleteBtn.textContent = 'Delete Week';
    deleteBtn.onclick = () => deleteWeekSection(sectionId);
    section.appendChild(deleteBtn);

    const weekPeriod = document.createElement('div');
    weekPeriod.className = 'week-period form-group';
    weekPeriod.innerHTML = `<label>Week Period ${sectionCount}</label>`;

    const select = document.createElement('select');
    select.id = `weekPeriod_${sectionCount}`;
    select.onchange = () => {
        updateSummary();
        updateDateValidations(sectionId);
        updateExistingRowDates(sectionId);
    };

    // Populate with FRESH weekOptions
    weekOptions.forEach(opt => {
        const option = document.createElement('option');
        option.value = opt.value;
        option.textContent = opt.text;
        select.appendChild(option);
    });

    if (weekOptions.length > 0) {
        select.value = weekOptions[0].value;
    }
    weekPeriod.appendChild(select);
    section.appendChild(weekPeriod);

    const tableWrapper = document.createElement('div');
    tableWrapper.className = 'table-responsive';
    const table = document.createElement('table');
    table.className = 'timesheet-table';
    table.innerHTML = `
        <thead>
            <tr>
                <th class="col-narrow col-sno">S.No</th>
                <th class="col-narrow col-add">Add</th>
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
                <th class="col-narrow col-delete">Action</th>
            </tr>
        </thead>
        <tbody id="timesheetBody_${sectionCount}"></tbody>
    `;
    tableWrapper.appendChild(table);
    section.appendChild(tableWrapper);

    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'button-container';

    const addRowBtn = document.createElement('button');
    addRowBtn.className = 'add-row-btn';
    addRowBtn.textContent = '+ Add New Entry';
    addRowBtn.onclick = () => addRow(sectionId);
    buttonContainer.appendChild(addRowBtn);

    const pasteAboveBtn = document.createElement('button');
    pasteAboveBtn.className = 'paste-above-btn';
    pasteAboveBtn.textContent = 'Paste Above Cell';
    pasteAboveBtn.onclick = () => pasteAboveCell(sectionId);
    buttonContainer.appendChild(pasteAboveBtn);

    section.appendChild(buttonContainer);
    sectionsDiv.appendChild(section);

    addRow(sectionId);
    updateDateValidations(sectionId);

    // Trigger change to validate dates
    setTimeout(() => select.dispatchEvent(new Event('change')), 50);
}

function addRow(sectionId) {
    const tbody = document.getElementById(`timesheetBody_${sectionId.split('_')[1]}`);
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    const rowCount = rows.length + 1;
    
    const weekSelect = document.getElementById(`weekPeriod_${sectionId.split('_')[1]}`);
    const selectedWeekValue = weekSelect.value;
    const selectedWeek = weekOptions.find(opt => opt.value === selectedWeekValue);
    
    let defaultDate = '';  // ✅ CHANGE: Start with empty date
    let minDate = '';
    let maxDate = '';
    
    if (selectedWeek && selectedWeek.start) {
        const weekStart = new Date(selectedWeek.start);
        const weekEnd = new Date(selectedWeek.end);
        
        minDate = `${weekStart.getFullYear()}-${String(weekStart.getMonth() + 1).padStart(2, '0')}-${String(weekStart.getDate()).padStart(2, '0')}`;
        maxDate = `${weekEnd.getFullYear()}-${String(weekEnd.getMonth() + 1).padStart(2, '0')}-${String(weekEnd.getDate()).padStart(2, '0')}`;
    }
    
    const row = document.createElement('tr');
    row.innerHTML = `
        <td class="col-sno" style="min-width: 60px;">${rowCount}</td>
        <td class="col-add" style="min-width: 60px;"><button class="eye-btn" onclick="openModal(this)"><i class="fas fa-eye"></i></button></td>
        <td class="col-action" style="min-width: 120px;">
            <button class="copy-btn" onclick="copyRow(this)"><i class="fas fa-copy"></i> Copy</button>
            <button class="paste-btn" onclick="pasteRow(this)"><i class="fas fa-paste"></i> Paste</button>
        </td>
        <td class="col-date" style="min-width: 120px;">
            <input type="date" 
                   value="${defaultDate}" 
                   min="${minDate}" 
                   max="${maxDate}" 
                   class="date-field form-input" 
                   onchange="validateDate(this); updateSummary()">
        </td>
        <td class="clo-location" style="min-width: 200px;"><select class="location-select form-input" onchange="updateSummary()">
            <option value="Office">Office</option>
            <option value="Client Site">Client Site</option>
            <option value="Work From Home">Work From Home</option>
            <option value="Field Work">Field Work</option>
        </select></td>
        <td class="col-project-start" style="min-width: 120px;"><input type="time" class="project-start form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
        <td class="col-project-end" style="min-width: 120px;"><input type="time" class="project-end form-input" onchange="validateTimes(this.closest('tr')); calculateHours(this.closest('tr'))"></td>
        <td class="col-client" style="min-width: 250px;"><input type="text" class="client-field form-input" placeholder="Enter Client" oninput="updateSummary()"></td>
        <td class="col-project" style="min-width: 200px;"><input type="text" class="project-field form-input" placeholder="Enter Project" oninput="updateSummary()"></td>
        <td class="col-project-code" style="min-width: 200px;"><input type="text" class="project-code form-input" placeholder="Enter Project Code" oninput="updateSummary()"></td>
        <td class="col-reporting-manager"><input type="text" class="reporting-manager-field form-input" placeholder="Enter Reporting Manager" onchange="updateSummary()"></td>
        <td class="col-activity" style="min-width: 200px;"><input type="text" class="activity-field form-input" placeholder="Enter Activity" oninput="updateSummary()"></td>
        <td class="col-project-hours" style="min-width: 80px;"><input type="number" class="project-hours-field form-input" readonly></td>
        <td class="col-billable" style="min-width: 120px;"><select class="billable-select form-input" onchange="updateSummary()">
            <option value="Yes">Billable</option>
            <option value="No">Non-Billable</option>
        </select></td>
        <td class="col-remarks" style="min-width: 200px;"><input type="text" class="remarks-field form-input" placeholder="Additional notes"></td>
        <td class="col-delete" style="min-width: 80px;"><button class="delete-btn" onclick="deleteRow(this)">Delete</button></td>
    `;

    tbody.appendChild(row);
    updateSummary();
    // ❌ REMOVED: No validation on row add
}


function updateDateValidations(sectionId) {
    const section = document.getElementById(sectionId);
    const dateInputs = section.querySelectorAll('.date-field');
    dateInputs.forEach(input => validateDate(input));
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

            // UPDATED Required columns (removed Punch In, Punch Out, Working Hours)
            const requiredColumns = [
                'Employee ID', 'Employee Name', 'Designation', 'Gender', 'Partner',
                'Reporting Manager', 'Week Period', 'Date', 'Location of Work',
                'Project Start Time', 'Project End Time', 
                // REMOVED: 'Punch In', 'Punch Out',
                'Client', 'Project', 'Project Code',
                'Reporting Manager Entry', 'Activity', 'Project Hours', 
                // REMOVED: 'Working Hours',
                'Billable', 'Remarks'
            ];

            const fileColumns = Object.keys(jsonData[0]);
            const missingColumns = requiredColumns.filter(col => !fileColumns.includes(col));

            if (missingColumns.length > 0) {
                showPopup(`Invalid Excel format. Missing columns: ${missingColumns.join(', ')}`, true);
                return;
            }

            showLoading("Uploading Excel data");

            // UPDATED Convert Excel data into API format (removed corresponding fields)
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
                // REMOVED: punchIn: row['Punch In'] || '',
                // REMOVED: punchOut: row['Punch Out'] || '',
                client: row['Client'] || '',
                project: row['Project'] || '',
                projectCode: row['Project Code'] || '',
                reportingManagerEntry: row['Reporting Manager Entry'] || '',
                activity: row['Activity'] || '',
                projectHours: row['Project Hours'] || '',
                // REMOVED: workingHours: row['Working Hours'] || '',
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
            setTimeout(() => window.location.replace('/dashboard'), 2000);

        } catch (error) {
            console.error('Error reading Excel:', error);
            hideLoading();
            showPopup(`Failed to upload Excel: ${error.message}`, true);
        }
    };

    reader.readAsArrayBuffer(file);
}

window.handleExcelUpload = handleExcelUpload;



