let rowCount = 0;
let sectionCount = 0;
let employeeData = [];
let clientData = [];
let currentRow = null;
let weekOptions = [];
let loggedInEmployeeId = localStorage.getItem('loggedInEmployeeId');
let copiedData = null;
const API_URL = '';
let isEditingHistory = false;
let currentEntryId = null;

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

    const uploadInput = document.getElementById("uploadExcelInput");
    if (uploadInput) {
        uploadInput.addEventListener("change", handleExcelUpload);
        console.log("✅ Excel upload handler attached successfully");
    } else {
        console.error("❌ Upload Excel input not found");
    }

    try {
        const response = await fetch('/verify_session', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!response.ok) throw new Error();
    } catch (error) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('loggedInEmployeeId');
        window.location.href = '/login';
        return;
    }

    showLoading("Fetching Employee Data");

    if (loggedInEmployeeId) {
        try {
            employeeData = await fetchData('/employees');
            clientData = await fetchData('/clients');
            const payroll = getPayrollPeriod();
            weekOptions = generateWeekOptions(payroll.start, payroll.end);
            await populateEmployeeInfo();
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
        if (!response.ok) throw new Error();
    } catch (error) {
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

function getPayrollPeriod() {
    let start = new Date(2025, 9, 21); // Oct 21, 2025
    let end = new Date(2025, 10, 20);  // Nov 20, 2025
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
        if (weekEnd > end) weekEnd = new Date(end);

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
        setTimeout(() => errorDiv.style.display = 'none', 5000);
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
    if (loadingBar) loadingBar.style.display = 'none';
}

function fetchEmployeeData(empId) {
    const cleanEmpId = empId.trim();
    const employee = employeeData.find(e => e['EmpID']?.toString().trim() === cleanEmpId);
    print(`Fetching data for Employee ID: ${cleanEmpId}`, employee ? '✅ Found' : '❌ Not Found');
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
    }
}

function getReportingManagers() {
    return [...new Set(employeeData
        .map(e => e['ReportingEmpName'])
        .filter(m => m && typeof m === 'string' && m.trim()))];
}

// REMOVED: calculateHours() — only project hours now
function calculateProjectHours(row) {
    const projectStart = row.querySelector('.project-start')?.value;
    const projectEnd = row.querySelector('.project-end')?.value;

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

    const projectHoursField = row.querySelector('.project-hours-field');
    if (projectHoursField) projectHoursField.value = projectHours > 0 ? projectHours : '';
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
        const defaultDate = `${weekStart.getFullYear()}-${String(weekStart.getMonth() + 1).padStart(2, '0')}-${String(weekStart.getDate()).padStart(2, '0')}`;

        const dateInputs = tbody.querySelectorAll('.date-field');
        dateInputs.forEach(dateInput => {
            const currentDate = new Date(dateInput.value + 'T00:00:00');
            const weekStartDate = new Date(selectedWeek.start);
            const weekEndDate = new Date(selectedWeek.end);

            if (!dateInput.value || currentDate < weekStartDate || currentDate > weekEndDate) {
                dateInput.value = defaultDate;
                validateDate(dateInput);
            }
        });
    }
}

function validateDate(dateInput) {
    if (!dateInput) return;
    const section = dateInput.closest('.timesheet-section');
    const weekSelect = section.querySelector('.week-period select');
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value);
    if (!selectedWeek) return;

    const inputDateStr = dateInput.value;
    const weekStartStr = `${selectedWeek.start.getFullYear()}-${String(selectedWeek.start.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.start.getDate()).padStart(2, '0')}`;
    const weekEndStr = `${selectedWeek.end.getFullYear()}-${String(selectedWeek.end.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.end.getDate()).padStart(2, '0')}`;

    if (inputDateStr < weekStartStr || inputDateStr > weekEndStr) {
        dateInput.classList.add('validation-error');
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

function validateModalDate(dateInput) {
    if (!dateInput || !currentRow) return;
    const section = currentRow.closest('.timesheet-section');
    const weekSelect = section.querySelector('.week-period select');
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value);
    if (!selectedWeek) return;

    const inputDateStr = dateInput.value;
    const weekStartStr = `${selectedWeek.start.getFullYear()}-${String(selectedWeek.start.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.start.getDate()).padStart(2, '0')}`;
    const weekEndStr = `${selectedWeek.end.getFullYear()}-${String(selectedWeek.end.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.end.getDate()).padStart(2, '0')}`;

    if (inputDateStr < weekStartStr || inputDateStr > weekEndStr) {
        dateInput.classList.add('validation-error');
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
        'Date', 'Location of Work', 'Project Start Time', 'Project End Time',
        'Client', 'Project', 'Project Code', 'Reporting Manager', 'Activity',
        'Project Hours', 'Billable', 'Remarks'
    ];

    for (let i = 0; i < inputs.length; i++) {
        const label = document.getElementById(`modalLabel${i + 1}`);
        const input = document.getElementById(`modalInput${i + 1}`);
        if (label && input) {
            label.textContent = labels[i];
            input.value = inputs[i].value || '';
            if (input.tagName === 'SELECT' && i === 10) {
                input.value = inputs[i].value || 'Yes';
            }
        }
    }
    document.getElementById('modalOverlay').style.display = 'flex';
    // ✅ Auto update hours when time fields change
    document.getElementById('modalInput3').onchange = updateModalProjectHours;
    document.getElementById('modalInput4').onchange = updateModalProjectHours;

    validateModalDate(document.getElementById('modalInput1'));
    updateModalProjectHours();
    const addBtn = document.getElementById('modalAddBtn');
    addBtn.innerHTML = 'Add';
    addBtn.setAttribute('onclick', 'saveModalEntry()');
}

function closeModal() {
    document.getElementById('modalOverlay').style.display = 'none';
    currentRow = null;
    isEditingHistory = false;
    currentEntryId = null;
}

// function updateModalProjectHours() {
//     if (!currentRow) return;
//     const projectStart = document.getElementById('modalInput3').value;
//     const projectEnd = document.getElementById('modalInput4').value;

//     let projectHours = 0;
//     if (projectStart && projectEnd) {
//         const [startH, startM] = projectStart.split(':').map(Number);
//         const [endH, endM] = projectEnd.split(':').map(Number);
//         const startMinutes = startH * 60 + startM;
//         const endMinutes = endH * 60 + endM;
//         projectHours = (endMinutes - startMinutes) / 60;
//         if (projectHours < 0) projectHours += 24;
//         projectHours = projectHours.toFixed(2);
//     }

//     document.getElementById('modalInput10').value = projectHours;
// }

function updateModalProjectHours() {
    const start = document.getElementById('modalInput3').value;
    const end = document.getElementById('modalInput4').value;

    if (!start || !end) {
        document.getElementById('modalInput10').value = '';
        return;
    }

    const [startH, startM] = start.split(':').map(Number);
    const [endH, endM] = end.split(':').map(Number);
    let diff = (endH * 60 + endM) - (startH * 60 + startM);
    if (diff < 0) diff += 24 * 60;

    const hours = (diff / 60).toFixed(2);
    document.getElementById('modalInput10').value = hours;
}


function saveModalEntry() {
    if (!currentRow) return;

    if (isEditingHistory) {
        updateHistoryEntry();
        return;
    }

    const modalInputs = document.querySelectorAll('#modalOverlay input, #modalOverlay select');
    const rowInputs = currentRow.querySelectorAll('input, select');

    for (let i = 0; i < modalInputs.length; i++) {
        if (rowInputs[i]) {
            rowInputs[i].value = modalInputs[i].value;
        }
    }

    calculateProjectHours(currentRow);
    validateDate(currentRow.querySelector('.date-field'));
    closeModal();
    updateSummary();
}

function updateHistoryEntry() {
    if (!currentRow || !currentEntryId) return;
    const modalInputs = document.querySelectorAll('#modalOverlay input, #modalOverlay select');

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

    fetch(`${API_URL}/update_timesheet/${loggedInEmployeeId}/${currentEntryId}`, {
        method: 'PUT',
        headers: getHeaders(),
        body: JSON.stringify(updateData)
    })
    .then(response => response.ok ? response.json() : Promise.reject('Failed'))
    .then(() => {
        showPopup('Entry updated successfully!');
        closeModal();
        showSection('history');
    })
    .catch(error => {
        console.error('Error updating entry:', error);
        showPopup('Failed to update entry.', true);
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
            const billable = row.querySelector('.billable-select').value;
            if (billable === 'Yes') billableHours += hours;
            else if (billable === 'No') nonBillableHours += hours;
        });
    });

    document.querySelector('.summary-section .total-hours .value').textContent = totalHours.toFixed(2);
    document.querySelector('.summary-section .billable-hours .value').textContent = billableHours.toFixed(2);
    document.querySelector('.summary-section .non-billable-hours .value').textContent = nonBillableHours.toFixed(2);
}

function exportTimesheetToExcel() {
    const wb = XLSX.utils.book_new();
    const employeeInfo = getEmployeeInfoForExport();
    let allData = [employeeInfo];

    document.querySelectorAll('.timesheet-section').forEach(section => {
        const weekPeriod = section.querySelector('.week-period select').value || '';
        const rows = section.querySelectorAll('tbody tr');
        rows.forEach(row => {
            const inputs = row.querySelectorAll('input, select');
            const rowData = {
                'Employee ID': employeeInfo['Employee ID'],
                'Employee Name': employeeInfo['Employee Name'],
                'Designation': employeeInfo['Designation'],
                'Gender': employeeInfo['Gender'],
                'Partner': employeeInfo['Partner'],
                'Reporting Manager': employeeInfo['Reporting Manager'],
                'Week Period': weekPeriod,
                'S.No': row.cells[0].textContent,
                'Date': inputs[0]?.value || '',
                'Location of Work': inputs[1]?.value || '',
                'Project Start Time': inputs[2]?.value || '',
                'Project End Time': inputs[3]?.value || '',
                'Client': inputs[4]?.value || '',
                'Project': inputs[5]?.value || '',
                'Project Code': inputs[6]?.value || '',
                'Reporting Manager Entry': inputs[7]?.value || '',
                'Activity': inputs[8]?.value || '',
                'Project Hours': inputs[9]?.value || '',
                'Billable': inputs[10]?.value || '',
                'Remarks': inputs[11]?.value || '',
                '3 HITS': document.getElementById('hits').value || '',
                '3 MISSES': document.getElementById('misses').value || '',
                'FEEDBACK FOR HR': document.getElementById('feedback_hr').value || '',
                'FEEDBACK FOR IT': document.getElementById('feedback_it').value || '',
                'FEEDBACK FOR CRM': document.getElementById('feedback_crm').value || '',
                'FEEDBACK FOR OTHERS': document.getElementById('feedback_others').value || ''
            };
            allData.push(rowData);
        });
    });

    const ws = XLSX.utils.json_to_sheet(allData);
    XLSX.utils.book_append_sheet(wb, ws, 'Timesheet');
    XLSX.writeFile(wb, `Timesheet_${document.getElementById('employeeId').value || 'User'}_${new Date().toISOString().split('T')[0]}.xlsx`);
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

async function saveDataToMongo() {
    showLoading();
    const employeeId = document.getElementById('employeeId').value.trim();
    if (!employeeId) {
        hideLoading();
        showPopup('Please enter Employee ID', true);
        return;
    }

    const timesheetData = [];
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
                }
            }

            const rowData = {
                employeeId,
                employeeName: document.getElementById('employeeName').value || '',
                designation: document.getElementById('designation').value || '',
                gender: document.getElementById('gender').value || '',
                partner: document.getElementById('partner').value || '',
                reportingManager: document.getElementById('reportingManager').value || '',
                weekPeriod,
                date: inputs[0].value,
                location: inputs[1].value,
                projectStartTime: inputs[2].value,
                projectEndTime: inputs[3].value,
                client: inputs[4].value,
                project: inputs[5].value,
                projectCode: inputs[6].value,
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

    try {
        const response = await fetch(`${API_URL}/save_timesheets`, {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify(timesheetData)
        });

        if (!response.ok) throw new Error('Failed to submit');
        // hideLoading();
        // showPopup('Timesheet Submitted successfully!');
        // setTimeout(() => window.location.reload(), 2000);
        hideLoading();
        showPopup('Timesheet Submitted successfully!');

        // Temporarily disable beforeunload warning
        isExiting = true;
        window.removeEventListener('beforeunload', beforeUnloadHandler);

        // Reload after popup delay
        setTimeout(() => {
            window.location.reload();
        }, 2000);


    } catch (error) {
        hideLoading();
        showPopup(`Failed to submit: ${error.message}`, true);
    }
}

function clearTimesheet() {
    showPopup('Timesheet cleared!');
    ['hits', 'misses', 'feedback_hr', 'feedback_it', 'feedback_crm', 'feedback_others'].forEach(id => {
        document.getElementById(id).value = '';
    });
    setTimeout(() => window.location.reload(), 3000);
}

function toggleNavMenu() {
    document.getElementById('navMenu').classList.toggle('active');
}

async function logout() {
    showLoading("Logging out...");
    try {
        await fetch(`${API_URL}/logout`, { method: 'POST', headers: getHeaders() });
    } catch (e) { }
    localStorage.removeItem('access_token');
    localStorage.removeItem('loggedInEmployeeId');
    hideLoading();
    window.location.href = '/static/login.html';
}

async function showSection(section) {
    document.getElementById('timesheetSection').style.display = section === 'timesheet' ? 'block' : 'none';
    document.getElementById('historySection').style.display = section === 'history' ? 'block' : 'none';
    document.querySelectorAll('.nav-menu a').forEach(a => a.classList.remove('active'));
    document.querySelector(`.nav-menu a[onclick*="${section}"]`).classList.add('active');

    if (section === 'history') {
        showLoading("Fetching History...");
        try {
            const response = await fetch(`${API_URL}/timesheets/${loggedInEmployeeId}`, { headers: getHeaders() });
            const data = await response.json();
            const historyContent = document.getElementById('historyContent');
            historyContent.innerHTML = '';

            document.querySelector('.history-summary .total-hours .value').textContent = (data.totalHours || 0).toFixed(2);
            document.querySelector('.history-summary .billable-hours .value').textContent = (data.totalBillableHours || 0).toFixed(2);
            document.querySelector('.history-summary .non-billable-hours .value').textContent = (data.totalNonBillableHours || 0).toFixed(2);

            if (!data.Data || data.Data.length === 0) {
                historyContent.innerHTML = '<p>No timesheet entries found.</p>';
                hideLoading();
                return;
            }

            const groupedByWeek = {};
            data.Data.forEach(entry => {
                const week = entry.weekPeriod || 'No Week';
                if (!groupedByWeek[week]) groupedByWeek[week] = [];
                groupedByWeek[week].push(entry);
            });

            Object.keys(groupedByWeek).forEach(week => {
                const weekDiv = document.createElement('div');
                weekDiv.className = 'history-week';
                weekDiv.innerHTML = `<h3>Week Period: ${week}</h3>`;

                const table = document.createElement('table');
                table.className = 'timesheet-table history-table';
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
                            <th>Project Code</th>
                            <th>Reporting Manager</th>
                            <th>Activity</th>
                            <th>Project Hours</th>
                            <th>Billable</th>
                            <th>Remarks</th>
                        </tr>
                    </thead>
                    <tbody></tbody>
                `;
                const tbody = table.querySelector('tbody');
                groupedByWeek[week].forEach((entry, i) => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td>${i + 1}</td>
                        <td style="min-width:120px;">
                            <button class="action-btn edit-btn" onclick="editHistoryRow(this, '${entry.id}')">Edit</button>
                            <button class="action-btn delete-btn" onclick="deleteHistoryRow(this, '${entry.id}')">Delete</button>
                        </td>
                        <td>${entry.date || ''}</td>
                        <td>${entry.location || ''}</td>
                        <td>${entry.projectStartTime || ''}</td>
                        <td>${entry.projectEndTime || ''}</td>
                        <td>${entry.client || ''}</td>
                        <td>${entry.project || ''}</td>
                        <td>${entry.projectCode || ''}</td>
                        <td>${entry.reportingManagerEntry || ''}</td>
                        <td>${entry.activity || ''}</td>
                        <td>${entry.projectHours || ''}</td>
                        <td>${entry.billable || ''}</td>
                        <td>${entry.remarks || ''}</td>
                    `;
                    tbody.appendChild(row);
                });

                // weekDiv.appendChild(document.createElement('div').appendChild(table).parentNode);
                const tableWrapper = document.createElement('div');
                tableWrapper.className = 'table-responsive';
                tableWrapper.appendChild(table);
                weekDiv.appendChild(tableWrapper);

                historyContent.appendChild(weekDiv);

                const feedback = document.createElement('div');
                feedback.className = 'history-feedback';
                feedback.innerHTML = `
                    <h4>Feedback for Week: ${week}</h4>
                    <div><strong>3 HITS:</strong> ${groupedByWeek[week][0].hits || ''}</div>
                    <div><strong>3 MISSES:</strong> ${groupedByWeek[week][0].misses || ''}</div>
                    <div><strong>FEEDBACK FOR HR:</strong> ${groupedByWeek[week][0].feedback_hr || ''}</div>
                    <div><strong>FEEDBACK FOR IT:</strong> ${groupedByWeek[week][0].feedback_it || ''}</div>
                    <div><strong>FEEDBACK FOR CRM:</strong> ${groupedByWeek[week][0].feedback_crm || ''}</div>
                    <div><strong>FEEDBACK FOR OTHERS:</strong> ${groupedByWeek[week][0].feedback_others || ''}</div>
                `;
                historyContent.appendChild(feedback);
            });
            hideLoading();
        } catch (error) {
            hideLoading();
            showPopup('Failed to load history.', true);
        }
    }
}

function editHistoryRow(button, entryId) {
    const row = button.closest('tr');
    currentRow = row;
    const cells = row.querySelectorAll('td');
    const modalInputs = document.querySelectorAll('#modalOverlay input, #modalOverlay select');

    modalInputs[0].value = cells[2].textContent;
    modalInputs[1].value = cells[3].textContent;
    modalInputs[2].value = cells[4].textContent;
    modalInputs[3].value = cells[5].textContent;
    modalInputs[4].value = cells[6].textContent;
    modalInputs[5].value = cells[7].textContent;
    modalInputs[6].value = cells[8].textContent;
    modalInputs[7].value = cells[9].textContent;
    modalInputs[8].value = cells[10].textContent;
    modalInputs[9].value = cells[11].textContent;
    modalInputs[10].value = cells[12].textContent;
    modalInputs[11].value = cells[13].textContent;

    isEditingHistory = true;
    currentEntryId = entryId;
    document.getElementById('modalOverlay').style.display = 'flex';
    validateModalDate(modalInputs[0]);
    updateModalProjectHours();
    document.getElementById('modalAddBtn').innerHTML = 'Update';
    document.getElementById('modalAddBtn').onclick = updateHistoryEntry;
}

function deleteHistoryRow(button, entryId) {
    if (confirm('Delete this entry?')) {
        fetch(`${API_URL}/delete_timesheet/${loggedInEmployeeId}/${entryId}`, {
            method: 'DELETE',
            headers: getHeaders()
        })
        .then(r => r.ok ? showSection('history') : showPopup('Failed to delete.', true))
        .catch(() => showPopup('Error.', true));
    }
}

function copyRow(button) {
    const row = button.closest('tr');
    copiedData = {};
    const inputs = row.querySelectorAll('input, select');
    inputs.forEach((input, i) => {
        if (!input.classList.contains('copy-btn') && !input.classList.contains('paste-btn') && input.type !== 'button') {
            copiedData[`f${i}`] = input.value;
        }
    });
    showPopup('Row copied!');
}

function pasteRow(button) {
    if (!copiedData) return showPopup('Nothing to paste!', true);
    const row = button.closest('tr');
    const inputs = row.querySelectorAll('input, select');
    inputs.forEach((input, i) => {
        const key = `f${i}`;
        if (copiedData[key] !== undefined && !input.classList.contains('copy-btn') && !input.classList.contains('paste-btn')) {
            input.value = copiedData[key];
            if (input.classList.contains('date-field')) validateDate(input);
            if (input.classList.contains('project-start') || input.classList.contains('project-end')) {
                calculateProjectHours(row);
            }
        }
    });
    updateSummary();
    showPopup('Pasted!');
}

function pasteAboveCell(sectionId) {
    const tbody = document.getElementById(`timesheetBody_${sectionId.split('_')[1]}`);
    if (!tbody || tbody.rows.length === 0) return addRow(sectionId);

    const lastRow = tbody.rows[tbody.rows.length - 1];
    const newRow = lastRow.cloneNode(true);
    tbody.insertBefore(newRow, lastRow.nextSibling);

    const newInputs = newRow.querySelectorAll('input, select');
    const lastInputs = lastRow.querySelectorAll('input, select');

    newInputs.forEach((input, i) => {
        if (input.type === 'button' || input.classList.contains('copy-btn') || input.classList.contains('paste-btn') || input.classList.contains('delete-btn')) return;
        input.value = lastInputs[i]?.value || '';
        if (input.classList.contains('date-field')) {
            const date = new Date(input.value);
            if (date < new Date(weekOptions[0].end)) {
                date.setDate(date.getDate() + 1);
                input.value = date.toISOString().split('T')[0];
            }
            validateDate(input);
        }
        if (input.classList.contains('project-start') || input.classList.contains('project-end')) {
            calculateProjectHours(newRow);
        }
    });

    updateRowNumbers(tbody.id);
    updateSummary();
    showPopup('Duplicated above!');
}

function addWeekSection() {
    sectionCount++;
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
    weekOptions.forEach(opt => {
        const option = document.createElement('option');
        option.value = opt.value;
        option.textContent = opt.text;
        select.appendChild(option);
    });
    if (weekOptions.length > 0) select.value = weekOptions[0].value;
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
    setTimeout(() => select.dispatchEvent(new Event('change')), 50);
}

function addRow(sectionId) {
    const tbody = document.getElementById(`timesheetBody_${sectionId.split('_')[1]}`);
    const rowCount = tbody.querySelectorAll('tr').length + 1;
    const weekSelect = document.getElementById(`weekPeriod_${sectionId.split('_')[1]}`);
    const selectedWeek = weekOptions.find(opt => opt.value === weekSelect.value) || weekOptions[0];
    const defaultDate = selectedWeek ? 
        `${selectedWeek.start.getFullYear()}-${String(selectedWeek.start.getMonth() + 1).padStart(2, '0')}-${String(selectedWeek.start.getDate()).padStart(2, '0')}` :
        new Date().toISOString().split('T')[0];

    const row = document.createElement('tr');
    row.innerHTML = `
        <td class="col-sno">${rowCount}</td>
        <td class="col-add"><button class="eye-btn" onclick="openModal(this)"><i class="fas fa-eye"></button></td>
        <td class="col-action">
            <button class="copy-btn" onclick="copyRow(this)">Copy</button>
            <button class="paste-btn" onclick="pasteRow(this)">Paste</button>
        </td>
        <td class="col-date"><input type="date" value="${defaultDate}" class="date-field form-input" onchange="validateDate(this); updateSummary()"></td>
        <td class="col-location"><select class="location-select form-input" onchange="updateSummary()">
            <option>Office</option>
            <option>Client Site</option>
            <option>Work From Home</option>
            <option>Field Work</option>
        </select></td>
        <td class="col-project-start"><input type="time" class="project-start form-input" onchange="calculateProjectHours(this.closest('tr'))"></td>
        <td class="col-project-end"><input type="time" class="project-end form-input" onchange="calculateProjectHours(this.closest('tr'))"></td>
        <td class="col-client"><input type="text" class="client-field form-input" placeholder="Enter Client" oninput="updateSummary()"></td>
        <td class="col-project"><input type="text" class="project-field form-input" placeholder="Enter Project" oninput="updateSummary()"></td>
        <td class="col-project-code"><input type="text" class="project-code form-input" placeholder="Enter Project Code" oninput="updateSummary()"></td>
        <td class="col-reporting-manager"><input type="text" class="reporting-manager-field form-input" placeholder="Enter Reporting Manager" onchange="updateSummary()"></td>
        <td class="col-activity"><input type="text" class="activity-field form-input" placeholder="Enter Activity" oninput="updateSummary()"></td>
        <td class="col-project-hours"><input type="number" class="project-hours-field form-input" readonly></td>
        <td class="col-billable"><select class="billable-select form-input" onchange="updateSummary()">
            <option>Yes</option>
            <option>No</option>
        </select></td>
        <td class="col-remarks"><input type="text" class="remarks-field form-input" placeholder="Additional notes"></td>
        <td class="col-delete"><button class="delete-btn" onclick="deleteRow(this)">Delete</button></td>
    `;
    tbody.appendChild(row);
    validateDate(row.querySelector('.date-field'));
    updateSummary();
}

function updateDateValidations(sectionId) {
    document.querySelectorAll(`#${sectionId} .date-field`).forEach(validateDate);
}

let isExiting = false;
// window.addEventListener('beforeunload', e => {
//     if (!isExiting) {
//         e.preventDefault();
//         e.returnValue = '';
//         showExitConfirmation();
//     }
// });

function beforeUnloadHandler(e) {
    if (!isExiting) {
        e.preventDefault();
        e.returnValue = '';
        showExitConfirmation();
    }
}
window.addEventListener('beforeunload', beforeUnloadHandler);


document.addEventListener('keydown', e => {
    if (e.key === 'Backspace' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) {
        e.preventDefault();
        showExitConfirmation();
    }
});
function showExitConfirmation() {
    document.getElementById('exitConfirmation').style.display = 'block';
}
function cancelExit() {
    document.getElementById('exitConfirmation').style.display = 'none';
}
function confirmExit() {
    isExiting = true;
    logout();
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


