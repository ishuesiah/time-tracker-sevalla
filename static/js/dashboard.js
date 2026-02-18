// Dashboard JavaScript

// Global state
let currentView = 'dashboard';
let currentData = [];
let clockInterval = null;

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
