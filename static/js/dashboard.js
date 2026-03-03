// Dashboard JavaScript

// Global state
let currentView = 'dashboard';
let currentData = [];
let clockInterval = null;
let currentWeekOffset = 0;
let adminWeekOffset = 0;

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    initNavigation();
    initClock();
    initCalendar();
    loadTodayAttendance();

    // Refresh attendance every 30 seconds
    setInterval(loadTodayAttendance, 30000);
});

// Navigation
function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(function(item) {
        item.addEventListener('click', function() {
            var view = this.dataset.view;
            if (view) {
                showView(view);
            }
        });
    });
}

function showView(view) {
    // Update nav
    document.querySelectorAll('.nav-item').forEach(function(item) {
        item.classList.remove('active');
        if (item.dataset.view === view) {
            item.classList.add('active');
        }
    });

    // Update content
    document.querySelectorAll('.view-section').forEach(function(section) {
        section.style.display = 'none';
    });

    var viewSection = document.getElementById(view + '-view');
    if (viewSection) {
        viewSection.style.display = 'block';
    }

    currentView = view;

    // Load view-specific data
    if (view === 'timetrack') {
        loadTimetrackData();
    } else if (view === 'audit') {
        loadAuditLogs();
    } else if (view === 'myshifts') {
        loadMyShifts();
    } else if (view === 'edithours') {
        loadEmployeesList();
    }
}

// Clock
function initClock() {
    updateClock();
    clockInterval = setInterval(updateClock, 1000);
}

function updateClock() {
    var now = new Date();
    var hours = now.getHours();
    var minutes = now.getMinutes();
    var seconds = now.getSeconds();

    var timeStr = padZero(hours) + ':' + padZero(minutes) + ':' + padZero(seconds);

    var clockEl = document.getElementById('current-time');
    if (clockEl) {
        clockEl.textContent = timeStr;
    }
}

function padZero(num) {
    return num < 10 ? '0' + num : num;
}

// Calendar
function initCalendar() {
    renderCalendar(new Date());
}

function renderCalendar(date) {
    var container = document.getElementById('calendar-container');
    if (!container) return;

    var year = date.getFullYear();
    var month = date.getMonth();

    var monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
                      'July', 'August', 'September', 'October', 'November', 'December'];

    var firstDay = new Date(year, month, 1).getDay();
    var daysInMonth = new Date(year, month + 1, 0).getDate();
    var today = new Date();

    var html = '<div class="calendar-nav">' +
        '<span class="calendar-month">' + monthNames[month] + ' ' + year + '</span>' +
        '<div class="calendar-arrows">' +
        '<button class="calendar-arrow" onclick="changeMonth(-1)">&lt;</button>' +
        '<button class="calendar-arrow" onclick="changeMonth(1)">&gt;</button>' +
        '</div></div>';

    html += '<div class="calendar-grid">';

    var dayNames = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];
    for (var i = 0; i < 7; i++) {
        html += '<div class="calendar-day-header">' + dayNames[i] + '</div>';
    }

    // Previous month days
    var prevMonth = new Date(year, month, 0);
    var prevDays = prevMonth.getDate();
    for (var i = firstDay - 1; i >= 0; i--) {
        html += '<div class="calendar-day other-month">' + (prevDays - i) + '</div>';
    }

    // Current month days
    for (var day = 1; day <= daysInMonth; day++) {
        var isToday = (day === today.getDate() && month === today.getMonth() && year === today.getFullYear());
        var classes = 'calendar-day' + (isToday ? ' today' : '');
        html += '<div class="' + classes + '">' + day + '</div>';
    }

    // Next month days
    var totalCells = firstDay + daysInMonth;
    var remaining = 7 - (totalCells % 7);
    if (remaining < 7) {
        for (var i = 1; i <= remaining; i++) {
            html += '<div class="calendar-day other-month">' + i + '</div>';
        }
    }

    html += '</div>';

    container.innerHTML = html;
    container.dataset.year = year;
    container.dataset.month = month;
}

function changeMonth(delta) {
    var container = document.getElementById('calendar-container');
    if (!container) return;

    var year = parseInt(container.dataset.year);
    var month = parseInt(container.dataset.month) + delta;

    renderCalendar(new Date(year, month, 1));
}

// Attendance
function loadTodayAttendance() {
    fetch('/dashboard/today')
        .then(function(response) { return response.json(); })
        .then(function(data) {
            renderAttendance(data);
            updateStats(data);
        })
        .catch(function(error) {
            console.error('Error loading attendance:', error);
        });
}

function renderAttendance(data) {
    var container = document.getElementById('attendance-list');
    if (!container) return;

    if (!data.entries || data.entries.length === 0) {
        container.innerHTML = '<div class="empty-state">' +
            '<div class="empty-icon">&#128197;</div>' +
            '<div>No attendance records for today</div></div>';
        return;
    }

    var html = '';
    for (var i = 0; i < data.entries.length; i++) {
        var entry = data.entries[i];
        var initials = getInitials(entry.employee);
        var isWorking = entry.status === 'working';
        var statusClass = isWorking ? 'working' : 'completed';
        var statusText = isWorking ? 'Working' : 'Completed';
        var timeText = entry.clock_in || '-';
        if (entry.clock_out) {
            timeText += ' - ' + entry.clock_out;
        }

        html += '<div class="attendance-item">' +
            '<div class="attendance-avatar">' + initials + '</div>' +
            '<div class="attendance-info">' +
            '<div class="attendance-name">' + entry.employee + '</div>' +
            '<div class="attendance-time">' + timeText + '</div>' +
            '</div>' +
            '<div class="attendance-status ' + statusClass + '">' +
            '<span class="status-dot"></span>' + statusText +
            '</div></div>';
    }

    container.innerHTML = html;
}

function updateStats(data) {
    if (!data.entries) return;

    var working = 0;
    var completed = 0;

    for (var i = 0; i < data.entries.length; i++) {
        if (data.entries[i].status === 'working') {
            working++;
        } else {
            completed++;
        }
    }

    var workingEl = document.getElementById('stat-working');
    var completedEl = document.getElementById('stat-completed');
    var totalEl = document.getElementById('stat-total');

    if (workingEl) workingEl.textContent = working;
    if (completedEl) completedEl.textContent = completed;
    if (totalEl) totalEl.textContent = data.entries.length;
}

function getInitials(name) {
    if (!name) return '?';
    var parts = name.split(' ');
    if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.substring(0, 2).toUpperCase();
}

// Time Track view
function loadTimetrackData() {
    var startDate = document.getElementById('startDate');
    var endDate = document.getElementById('endDate');

    if (!startDate || !endDate) return;

    var start = startDate.value;
    var end = endDate.value;

    if (!start || !end) {
        var today = new Date();
        var twoWeeksAgo = new Date(today);
        twoWeeksAgo.setDate(today.getDate() - 14);

        if (endDate) endDate.value = today.toISOString().split('T')[0];
        if (startDate) startDate.value = twoWeeksAgo.toISOString().split('T')[0];

        start = startDate.value;
        end = endDate.value;
    }

    fetch('/dashboard/data?start=' + start + '&end=' + end)
        .then(function(response) { return response.json(); })
        .then(function(data) {
            renderTimetrackTable(data);
        })
        .catch(function(error) {
            console.error('Error loading timetrack data:', error);
        });
}

function renderTimetrackTable(data) {
    var container = document.getElementById('timetrack-table');
    if (!container) return;

    if (!data.summary || data.summary.length === 0) {
        container.innerHTML = '<div class="empty-state">No data for this period</div>';
        return;
    }

    var html = '<table class="data-table"><thead><tr>' +
        '<th>Employee</th><th>Hours</th><th>Days</th><th>Avg/Day</th>' +
        '</tr></thead><tbody>';

    for (var i = 0; i < data.summary.length; i++) {
        var row = data.summary[i];
        var avg = row.days_worked > 0 ? (row.total_hours / row.days_worked).toFixed(1) : '0';
        html += '<tr>' +
            '<td>' + row.employee + '</td>' +
            '<td>' + row.total_hours.toFixed(1) + ' hrs</td>' +
            '<td>' + row.days_worked + '</td>' +
            '<td>' + avg + ' hrs</td>' +
            '</tr>';
    }

    html += '<tr style="font-weight:600;background:#f0f7e6;">' +
        '<td>Total</td>' +
        '<td>' + data.total_hours.toFixed(1) + ' hrs</td>' +
        '<td>-</td><td>-</td></tr>';

    html += '</tbody></table>';
    container.innerHTML = html;
}

function applyFilters() {
    loadTimetrackData();
}

function downloadCSV() {
    var startDate = document.getElementById('startDate').value;
    var endDate = document.getElementById('endDate').value;
    window.location.href = '/dashboard/download?start=' + startDate + '&end=' + endDate;
}

// Audit Logs
function loadAuditLogs() {
    var container = document.getElementById('audit-container');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="loading-spinner"></div>Loading audit logs...</div>';

    fetch('/dashboard/audit?limit=100')
        .then(function(response) { return response.json(); })
        .then(function(data) {
            renderAuditLogs(data.logs);
        })
        .catch(function(error) {
            console.error('Error loading audit logs:', error);
            container.innerHTML = '<div class="empty-state">Error loading audit logs</div>';
        });
}

function renderAuditLogs(logs) {
    var container = document.getElementById('audit-container');
    if (!container) return;

    if (!logs || logs.length === 0) {
        container.innerHTML = '<div class="empty-state">' +
            '<div class="empty-icon">&#128203;</div>' +
            '<div>No audit logs recorded yet</div></div>';
        return;
    }

    var html = '<div class="audit-table-wrapper">' +
        '<table class="data-table audit-table"><thead><tr>' +
        '<th>Date/Time</th>' +
        '<th>Employee</th>' +
        '<th>Action</th>' +
        '<th>Change</th>' +
        '<th>Details</th>' +
        '<th></th>' +
        '</tr></thead><tbody>';

    for (var i = 0; i < logs.length; i++) {
        var log = logs[i];
        var actionLabel = formatActionLabel(log.action);
        var actionClass = 'action-' + log.action;
        var changeHtml = '-';

        if (log.old_value && log.new_value) {
            changeHtml = '<span class="old-value">' + log.old_value + '</span>' +
                '<span class="change-arrow">&rarr;</span>' +
                '<span class="new-value">' + log.new_value + '</span>';
        } else if (log.new_value) {
            changeHtml = '<span class="new-value">' + log.new_value + '</span>';
        }

        var details = log.details || '-';
        var detailsEscaped = details.replace(/'/g, "\\'").replace(/"/g, '&quot;');

        html += '<tr>' +
            '<td class="audit-timestamp">' + log.timestamp + '</td>' +
            '<td class="audit-employee">' + log.employee_name + '</td>' +
            '<td><span class="action-badge ' + actionClass + '">' + actionLabel + '</span></td>' +
            '<td class="audit-change">' + changeHtml + '</td>' +
            '<td class="audit-details" onclick="showAuditDetails(\'' + detailsEscaped + '\')" title="Click to view full details">' + details + '</td>' +
            '<td><button class="btn-delete" onclick="deleteAuditLog(' + log.id + ')">Delete</button></td>' +
            '</tr>';
    }

    html += '</tbody></table></div>';
    container.innerHTML = html;
}

function showAuditDetails(details) {
    var modal = document.getElementById('details-modal');
    var content = document.getElementById('details-content');
    if (modal && content) {
        content.textContent = details;
        modal.style.display = 'flex';
    }
}

function closeDetailsModal() {
    var modal = document.getElementById('details-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function formatActionLabel(action) {
    var labels = {
        'adjust_clock_in': 'Adjusted In',
        'adjust_clock_out': 'Adjusted Out',
        'late_clock_out': 'Late Out',
        'dashboard_adjust': 'Dashboard Edit',
        'manual_entry': 'Manual Entry'
    };
    return labels[action] || action;
}

function deleteAuditLog(id) {
    if (!confirm('Are you sure you want to delete this audit log entry?')) {
        return;
    }

    fetch('/dashboard/audit/' + id, {
        method: 'DELETE'
    })
    .then(function(response) { return response.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            loadAuditLogs();
        } else {
            alert('Error: ' + (data.error || 'Failed to delete'));
        }
    })
    .catch(function(error) {
        console.error('Error deleting audit log:', error);
        alert('Error deleting audit log');
    });
}

// My Hours / Shifts
function getWeekDates(offset) {
    var today = new Date();
    var dayOfWeek = today.getDay();
    var startOfWeek = new Date(today);
    startOfWeek.setDate(today.getDate() - dayOfWeek + (offset * 7));
    startOfWeek.setHours(0, 0, 0, 0);

    var endOfWeek = new Date(startOfWeek);
    endOfWeek.setDate(startOfWeek.getDate() + 6);
    endOfWeek.setHours(23, 59, 59, 999);

    return {
        start: startOfWeek,
        end: endOfWeek
    };
}

function formatDateRange(start, end) {
    var options = { month: 'short', day: 'numeric' };
    var startStr = start.toLocaleDateString('en-US', options);
    var endStr = end.toLocaleDateString('en-US', options);
    var year = end.getFullYear();
    return startStr + ' - ' + endStr + ', ' + year;
}

function changeWeek(delta) {
    currentWeekOffset += delta;
    loadMyShifts();
}

function loadMyShifts() {
    var container = document.getElementById('myshifts-list');
    var weekLabel = document.getElementById('week-label');
    if (!container) return;

    container.innerHTML = '<div class="loading"><div class="loading-spinner"></div>Loading shifts...</div>';

    var dates = getWeekDates(currentWeekOffset);
    var startStr = dates.start.toISOString().split('T')[0];
    var endStr = dates.end.toISOString().split('T')[0];

    // Update week label
    if (weekLabel) {
        if (currentWeekOffset === 0) {
            weekLabel.textContent = 'This Week (' + formatDateRange(dates.start, dates.end) + ')';
        } else if (currentWeekOffset === -1) {
            weekLabel.textContent = 'Last Week (' + formatDateRange(dates.start, dates.end) + ')';
        } else {
            weekLabel.textContent = formatDateRange(dates.start, dates.end);
        }
    }

    fetch('/dashboard/myshifts?start=' + startStr + '&end=' + endStr)
        .then(function(response) { return response.json(); })
        .then(function(data) {
            renderMyShifts(data);
        })
        .catch(function(error) {
            console.error('Error loading shifts:', error);
            container.innerHTML = '<div class="empty-state">Error loading shifts</div>';
        });
}

function renderMyShifts(data) {
    var container = document.getElementById('myshifts-list');
    var totalEl = document.getElementById('week-total-hours');
    if (!container) return;

    // Store employee name for edit modal
    if (data.employee_name) {
        window.currentEmployeeName = data.employee_name;
    }

    // Update total hours
    if (totalEl && data.total_hours !== undefined) {
        totalEl.textContent = data.total_hours.toFixed(1) + ' hrs';
    }

    if (!data.shifts || data.shifts.length === 0) {
        container.innerHTML = '<div class="empty-state">' +
            '<div class="empty-icon">&#128197;</div>' +
            '<div>No shifts recorded for this week</div></div>';
        return;
    }

    var html = '<div class="shifts-list">';

    for (var i = 0; i < data.shifts.length; i++) {
        var shift = data.shifts[i];
        var hoursDisplay = shift.hours ? shift.hours.toFixed(1) + ' hrs' : '-';
        var statusClass = shift.clock_out ? 'completed' : 'working';

        // Escape shift data for onclick
        var shiftData = JSON.stringify({
            date: shift.date,
            date_display: shift.date_display,
            day_name: shift.day_name,
            clock_in: shift.clock_in,
            clock_out: shift.clock_out
        }).replace(/'/g, "\\'");

        html += '<div class="shift-card ' + statusClass + '">' +
            '<div class="shift-date">' +
            '<div class="shift-day">' + shift.day_name + '</div>' +
            '<div class="shift-date-num">' + shift.date_display + '</div>' +
            '</div>' +
            '<div class="shift-times">' +
            '<div class="shift-time">' +
            '<span class="shift-time-label">In</span>' +
            '<span class="shift-time-value">' + (shift.clock_in || '-') + '</span>' +
            '</div>' +
            '<div class="shift-time">' +
            '<span class="shift-time-label">Out</span>' +
            '<span class="shift-time-value">' + (shift.clock_out || '-') + '</span>' +
            '</div>' +
            '</div>' +
            '<div class="shift-hours">' + hoursDisplay + '</div>' +
            '<button class="shift-edit-btn" onclick=\'openEditModal(' + shiftData + ')\'>' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
            '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>' +
            '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>' +
            '</svg>Edit</button>' +
            '</div>';
    }

    html += '</div>';
    container.innerHTML = html;
}

// Admin Edit Hours Functions
function loadEmployeesList() {
    var select = document.getElementById('employeeSelect');
    if (!select) return;

    fetch('/dashboard/employees')
        .then(function(response) { return response.json(); })
        .then(function(data) {
            if (data.employees) {
                var html = '<option value="">Select an employee...</option>';
                for (var i = 0; i < data.employees.length; i++) {
                    html += '<option value="' + data.employees[i] + '">' + data.employees[i] + '</option>';
                }
                select.innerHTML = html;
            }
        })
        .catch(function(error) {
            console.error('Error loading employees:', error);
        });

    updateAdminWeekLabel();
}

function changeAdminWeek(delta) {
    adminWeekOffset += delta;
    updateAdminWeekLabel();
    loadEmployeeShifts();
}

function updateAdminWeekLabel() {
    var labelEl = document.getElementById('admin-week-label');
    if (!labelEl) return;

    var dates = getWeekDates(adminWeekOffset);
    if (adminWeekOffset === 0) {
        labelEl.textContent = 'This Week (' + formatDateRange(dates.start, dates.end) + ')';
    } else if (adminWeekOffset === -1) {
        labelEl.textContent = 'Last Week (' + formatDateRange(dates.start, dates.end) + ')';
    } else {
        labelEl.textContent = formatDateRange(dates.start, dates.end);
    }
}

function loadEmployeeShifts() {
    var select = document.getElementById('employeeSelect');
    var container = document.getElementById('admin-shifts-list');
    var summaryEl = document.getElementById('admin-week-summary');

    if (!select || !container) return;

    var employee = select.value;
    if (!employee) {
        container.innerHTML = '<div class="empty-state">' +
            '<div class="empty-icon">&#128100;</div>' +
            '<div>Select an employee to view and edit their hours</div></div>';
        if (summaryEl) summaryEl.style.display = 'none';
        return;
    }

    container.innerHTML = '<div class="loading"><div class="loading-spinner"></div>Loading shifts...</div>';

    var dates = getWeekDates(adminWeekOffset);
    var startStr = dates.start.toISOString().split('T')[0];
    var endStr = dates.end.toISOString().split('T')[0];

    fetch('/dashboard/employee-shifts?employee=' + encodeURIComponent(employee) + '&start=' + startStr + '&end=' + endStr)
        .then(function(response) { return response.json(); })
        .then(function(data) {
            renderAdminShifts(data);
        })
        .catch(function(error) {
            console.error('Error loading employee shifts:', error);
            container.innerHTML = '<div class="empty-state">Error loading shifts</div>';
        });
}

function renderAdminShifts(data) {
    var container = document.getElementById('admin-shifts-list');
    var totalEl = document.getElementById('admin-week-total-hours');
    var summaryEl = document.getElementById('admin-week-summary');
    if (!container) return;

    // Update total hours
    if (totalEl && data.total_hours !== undefined) {
        totalEl.textContent = data.total_hours.toFixed(1) + ' hrs';
    }
    if (summaryEl) {
        summaryEl.style.display = 'block';
    }

    if (!data.shifts || data.shifts.length === 0) {
        container.innerHTML = '<div class="empty-state">' +
            '<div class="empty-icon">&#128197;</div>' +
            '<div>No shifts recorded for this week</div></div>';
        return;
    }

    var html = '<div class="shifts-list">';

    for (var i = 0; i < data.shifts.length; i++) {
        var shift = data.shifts[i];
        var hoursDisplay = shift.hours ? shift.hours.toFixed(1) + ' hrs' : '-';
        var statusClass = shift.clock_out ? 'completed' : 'working';

        var shiftData = JSON.stringify({
            date: shift.date,
            date_display: shift.date_display,
            day_name: shift.day_name,
            clock_in: shift.clock_in,
            clock_out: shift.clock_out,
            employee_name: data.employee_name
        }).replace(/'/g, "\\'");

        html += '<div class="shift-card ' + statusClass + '">' +
            '<div class="shift-date">' +
            '<div class="shift-day">' + shift.day_name + '</div>' +
            '<div class="shift-date-num">' + shift.date_display + '</div>' +
            '</div>' +
            '<div class="shift-times">' +
            '<div class="shift-time">' +
            '<span class="shift-time-label">In</span>' +
            '<span class="shift-time-value">' + (shift.clock_in || '-') + '</span>' +
            '</div>' +
            '<div class="shift-time">' +
            '<span class="shift-time-label">Out</span>' +
            '<span class="shift-time-value">' + (shift.clock_out || '-') + '</span>' +
            '</div>' +
            '</div>' +
            '<div class="shift-hours">' + hoursDisplay + '</div>' +
            '<button class="shift-edit-btn" onclick=\'openEditModal(' + shiftData + ')\'>' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
            '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>' +
            '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>' +
            '</svg>Edit</button>' +
            '</div>';
    }

    html += '</div>';
    container.innerHTML = html;
}

// Edit Time Modal Functions
function convertTo24Hour(time12h) {
    if (!time12h || time12h === '-') return '';

    // Handle already 24-hour format
    if (!time12h.includes('AM') && !time12h.includes('PM')) {
        return time12h;
    }

    var match = time12h.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
    if (!match) return '';

    var hours = parseInt(match[1], 10);
    var minutes = match[2];
    var period = match[3].toUpperCase();

    if (period === 'PM' && hours !== 12) {
        hours += 12;
    } else if (period === 'AM' && hours === 12) {
        hours = 0;
    }

    return padZero(hours) + ':' + minutes;
}

function openEditModal(shift) {
    var modal = document.getElementById('edit-modal');
    var dateInput = document.getElementById('edit-date');
    var employeeInput = document.getElementById('edit-employee');
    var employeeDisplay = document.getElementById('edit-employee-display');
    var dateDisplay = document.getElementById('edit-date-display');
    var clockInInput = document.getElementById('edit-clock-in');
    var clockOutInput = document.getElementById('edit-clock-out');
    var reasonInput = document.getElementById('edit-reason');
    var statusEl = document.getElementById('edit-status');

    if (!modal) return;

    // Set values
    dateInput.value = shift.date;
    dateDisplay.textContent = shift.day_name + ', ' + shift.date_display;
    clockInInput.value = convertTo24Hour(shift.clock_in);
    clockOutInput.value = convertTo24Hour(shift.clock_out);
    reasonInput.value = '';

    // Handle employee name for admin edits
    if (shift.employee_name) {
        employeeInput.value = shift.employee_name;
        employeeDisplay.textContent = 'Editing: ' + shift.employee_name;
        employeeDisplay.style.display = 'block';
    } else {
        employeeInput.value = '';
        employeeDisplay.style.display = 'none';
    }

    // Clear status
    statusEl.className = 'modal-status';
    statusEl.textContent = '';

    // Show modal
    modal.style.display = 'flex';
}

function closeEditModal() {
    var modal = document.getElementById('edit-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}

function saveTimeEdit() {
    var dateInput = document.getElementById('edit-date');
    var employeeInput = document.getElementById('edit-employee');
    var clockInInput = document.getElementById('edit-clock-in');
    var clockOutInput = document.getElementById('edit-clock-out');
    var reasonInput = document.getElementById('edit-reason');
    var statusEl = document.getElementById('edit-status');

    var date = dateInput.value;
    var clockIn = clockInInput.value;
    var clockOut = clockOutInput.value;
    var reason = reasonInput.value.trim();

    if (!clockIn && !clockOut) {
        statusEl.className = 'modal-status error';
        statusEl.textContent = 'Please enter at least one time';
        return;
    }

    if (!reason) {
        statusEl.className = 'modal-status error';
        statusEl.textContent = 'Please provide a reason for this edit';
        return;
    }

    // Get employee name - from hidden field (admin edit) or stored value (own edit)
    var employeeName = employeeInput.value || window.currentEmployeeName;
    var isAdminEdit = !!employeeInput.value;

    if (!employeeName) {
        statusEl.className = 'modal-status error';
        statusEl.textContent = 'Could not determine employee name';
        return;
    }

    statusEl.className = 'modal-status info';
    statusEl.textContent = 'Saving...';

    fetch('/dashboard/adjust', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            employee: employeeName,
            date: date,
            clock_in: clockIn,
            clock_out: clockOut,
            reason: reason
        })
    })
    .then(function(response) { return response.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            statusEl.className = 'modal-status success';
            statusEl.textContent = 'Saved successfully!';

            // Reload appropriate view after a brief delay
            setTimeout(function() {
                closeEditModal();
                if (isAdminEdit) {
                    loadEmployeeShifts();
                } else {
                    loadMyShifts();
                }
            }, 1000);
        } else {
            statusEl.className = 'modal-status error';
            statusEl.textContent = 'Error: ' + (data.error || 'Failed to save');
        }
    })
    .catch(function(error) {
        console.error('Error saving time edit:', error);
        statusEl.className = 'modal-status error';
        statusEl.textContent = 'Error saving changes';
    });
}

// Close modals when clicking outside
document.addEventListener('click', function(event) {
    var editModal = document.getElementById('edit-modal');
    var detailsModal = document.getElementById('details-modal');
    if (event.target === editModal) {
        closeEditModal();
    }
    if (event.target === detailsModal) {
        closeDetailsModal();
    }
});
