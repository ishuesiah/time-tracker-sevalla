#!/usr/bin/env python3
"""
Time Tracker Dashboard

Web dashboard for viewing employee hours.
Imported by api_server.py as a Flask Blueprint.
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify, Response, session, redirect

import psycopg2

# Create Blueprint
dashboard_bp = Blueprint('dashboard', __name__)

# Configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
TIMEZONE = ZoneInfo(os.environ.get('TIMEZONE', 'America/Vancouver'))
ADMIN_EMAILS = [e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()]


def get_db_connection():
    """Get a PostgreSQL database connection."""
    return psycopg2.connect(DATABASE_URL)


def now_local():
    """Get current time in configured timezone."""
    return datetime.now(TIMEZONE)


def get_current_user():
    """Get current user from session."""
    return session.get('user')


def is_admin_user(user):
    """Check if user is an admin."""
    if not user:
        return False
    return user.get('is_admin', False)


def get_employee_name_from_email(email: str) -> str:
    """Extract employee name from email for matching."""
    name_part = email.split('@')[0]
    return name_part.replace('.', ' ').replace('_', ' ')


def format_time(dt):
    """Format datetime for display."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(TIMEZONE)
    else:
        dt = dt.astimezone(TIMEZONE)
    return dt.strftime("%I:%M %p").lstrip('0')


def log_audit(employee_name: str, action: str, details: str = None,
              old_value: str = None, new_value: str = None, adjusted_by: str = None):
    """Log an audit event."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            full_details = details or ''
            if adjusted_by:
                full_details += f" (by {adjusted_by})"
            cursor.execute('''
                INSERT INTO audit_log (timestamp, employee_name, action, details, old_value, new_value)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (now_local(), employee_name, action, full_details.strip(), old_value, new_value))
            conn.commit()


# =============================================================================
# LOGIN PAGE HTML
# =============================================================================

LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Time Tracker - Login</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-card {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 2px 20px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 400px;
        }
        h1 {
            color: #2d5016;
            margin-bottom: 10px;
        }
        p {
            color: #666;
            margin-bottom: 30px;
        }
        .login-btn {
            display: inline-flex;
            align-items: center;
            gap: 10px;
            background: #4285f4;
            color: white;
            padding: 12px 24px;
            border-radius: 5px;
            text-decoration: none;
            font-size: 16px;
            transition: background 0.2s;
        }
        .login-btn:hover { background: #3367d6; }
        .google-icon {
            width: 20px;
            height: 20px;
            background: white;
            border-radius: 2px;
            padding: 2px;
        }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>Time Tracker</h1>
        <p>Sign in to view your hours</p>
        <a href="/login" class="login-btn">
            <svg class="google-icon" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Sign in with Google
        </a>
    </div>
</body>
</html>
'''


# =============================================================================
# DASHBOARD HTML (with authentication)
# =============================================================================

def get_dashboard_html(user):
    """Generate dashboard HTML based on user role."""
    is_admin = is_admin_user(user)
    user_email = user.get('email', '') if user else ''
    user_name = user.get('name', '') if user else ''

    # Determine employee filter hint for non-admins
    employee_name_hint = get_employee_name_from_email(user_email) if not is_admin else ''

    audit_section = '''
            <div class="audit-section" id="auditSection">
                <h2>Audit Log (Time Adjustments)</h2>
                <div id="auditContainer" class="audit-container">
                    <div class="loading">Loading audit log...</div>
                </div>
            </div>
    ''' if is_admin else ''

    # Edit section - different for admin vs employee
    if is_admin:
        edit_section = '''
            <div class="edit-section">
                <h3>Edit Time Entry</h3>
                <div class="edit-form">
                    <div class="edit-row">
                        <div>
                            <label>Employee:</label>
                            <select id="editEmployee" onchange="loadDayData()">
                                <option value="">Select employee...</option>
                            </select>
                        </div>
                        <div>
                            <label>Date:</label>
                            <input type="date" id="editDate" onchange="loadDayData()">
                        </div>
                    </div>
                    <div id="editFields" style="display: none;">
                        <div class="edit-row">
                            <div>
                                <label>Clock In:</label>
                                <input type="time" id="editClockIn">
                            </div>
                            <div>
                                <label>Clock Out:</label>
                                <input type="time" id="editClockOut">
                            </div>
                            <div>
                                <button onclick="saveTimeEntry()">Save Changes</button>
                            </div>
                        </div>
                        <div id="editStatus" class="edit-status"></div>
                    </div>
                </div>
            </div>
        '''
    else:
        edit_section = '''
            <div class="edit-section">
                <h3>Edit My Time</h3>
                <div class="edit-form">
                    <div class="edit-row">
                        <div>
                            <label>Date:</label>
                            <input type="date" id="editDate" onchange="loadDayData()">
                        </div>
                    </div>
                    <div id="editFields" style="display: none;">
                        <div class="edit-row">
                            <div>
                                <label>Clock In:</label>
                                <input type="time" id="editClockIn">
                            </div>
                            <div>
                                <label>Clock Out:</label>
                                <input type="time" id="editClockOut">
                            </div>
                            <div>
                                <button onclick="saveTimeEntry()">Save Changes</button>
                            </div>
                        </div>
                        <div id="editStatus" class="edit-status"></div>
                    </div>
                </div>
            </div>
        '''

    employee_filter_html = '''
                <div>
                    <label>Employee:</label>
                    <select id="employeeFilter">
                        <option value="">All Employees</option>
                    </select>
                </div>
    ''' if is_admin else '<input type="hidden" id="employeeFilter" value="">'

    download_btn_html = '<button class="btn-download" onclick="downloadCSV()">Download CSV</button>' if is_admin else ''

    summary_cards_html = '''
            <div class="summary-cards">
                <div class="summary-card">
                    <div class="number" id="totalEmployees">-</div>
                    <div class="label">Employees</div>
                </div>
                <div class="summary-card">
                    <div class="number" id="totalHours">-</div>
                    <div class="label">Total Hours</div>
                </div>
            </div>
    ''' if is_admin else ''

    return f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Time Tracker Dashboard</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
            color: #333;
        }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        .header {{
            background: linear-gradient(135deg, #2d5016 0%, #4a7c23 100%);
            color: white;
            padding: 20px 30px;
            border-radius: 10px 10px 0 0;
            margin-bottom: 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .header h1 {{ margin: 0; }}
        .user-info {{
            display: flex;
            align-items: center;
            gap: 15px;
            font-size: 14px;
        }}
        .user-info span {{ opacity: 0.9; }}
        .logout-btn {{
            background: rgba(255,255,255,0.2);
            color: white;
            padding: 8px 16px;
            border-radius: 5px;
            text-decoration: none;
            font-size: 13px;
        }}
        .logout-btn:hover {{ background: rgba(255,255,255,0.3); }}
        .admin-badge {{
            background: #ffd700;
            color: #333;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
        }}
        .card {{
            background: white;
            border-radius: 0 0 10px 10px;
            padding: 20px 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .filters {{
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            margin-bottom: 20px;
            align-items: center;
        }}
        .filters label {{
            font-weight: 500;
            margin-right: 5px;
        }}
        select, button, input[type="date"], input[type="time"] {{
            padding: 10px 15px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
        }}
        input[type="date"] {{ min-width: 140px; }}
        input[type="time"] {{ min-width: 120px; }}
        button {{
            background: #4a7c23;
            color: white;
            border: none;
            cursor: pointer;
            transition: background 0.2s;
        }}
        button:hover {{ background: #2d5016; }}
        .btn-download {{ background: #2196F3; }}
        .btn-download:hover {{ background: #1976D2; }}
        .btn-edit {{
            background: #ff9800;
            padding: 5px 10px;
            font-size: 12px;
        }}
        .btn-edit:hover {{ background: #f57c00; }}
        .btn-cancel {{ background: #9e9e9e; }}
        .btn-cancel:hover {{ background: #757575; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th, td {{
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{ background: #f9f9f9; font-weight: 600; }}
        tr:hover {{ background: #f5f5f5; }}
        .total-row {{ background: #e8f5e9 !important; font-weight: 600; }}
        .loading {{ text-align: center; padding: 40px; color: #666; }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .summary-card {{
            background: #f9f9f9;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }}
        .summary-card .number {{ font-size: 24px; font-weight: 600; color: #4a7c23; }}
        .summary-card .label {{ font-size: 12px; color: #666; margin-top: 5px; }}
        .employee-name {{ font-weight: 500; }}
        .audit-section {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 2px solid #eee;
        }}
        .audit-section h2 {{ font-size: 18px; margin-bottom: 15px; color: #333; }}
        .audit-container {{
            max-height: 300px;
            overflow-y: auto;
            border: 1px solid #eee;
            border-radius: 8px;
        }}
        .audit-table {{ font-size: 13px; width: 100%; }}
        .audit-table th, .audit-table td {{ padding: 8px 12px; }}
        .action-badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .action-adjust_clock_in {{ background: #fff3e0; color: #e65100; }}
        .action-adjust_clock_out {{ background: #e3f2fd; color: #1565c0; }}
        .action-late_clock_out {{ background: #fce4ec; color: #c2185b; }}
        .action-dashboard_adjust {{ background: #e8f5e9; color: #2e7d32; }}
        .change-arrow {{ color: #999; margin: 0 5px; }}

        /* Edit section styles */
        .edit-section {{
            margin-top: 30px;
            padding: 20px;
            background: #f9f9f9;
            border-radius: 8px;
        }}
        .edit-section h3 {{
            margin-bottom: 15px;
            color: #333;
        }}
        .edit-form {{
            display: flex;
            flex-direction: column;
            gap: 15px;
        }}
        .edit-row {{
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: flex-end;
        }}
        .edit-row > div {{
            display: flex;
            flex-direction: column;
            gap: 5px;
        }}
        .edit-status {{
            padding: 10px;
            border-radius: 5px;
            font-size: 14px;
        }}
        .edit-status.success {{ background: #e8f5e9; color: #2e7d32; }}
        .edit-status.error {{ background: #ffebee; color: #c62828; }}
        .edit-status.info {{ background: #e3f2fd; color: #1565c0; }}

        /* Delete button for audit */
        .btn-delete {{
            background: #f44336;
            padding: 4px 8px;
            font-size: 11px;
        }}
        .btn-delete:hover {{ background: #d32f2f; }}

        /* View tabs */
        .view-tabs {{
            display: flex;
            gap: 5px;
            margin-bottom: 15px;
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
        }}
        .tab-btn {{
            background: #f5f5f5;
            color: #666;
            border: 1px solid #ddd;
            padding: 8px 20px;
            cursor: pointer;
            border-radius: 5px 5px 0 0;
        }}
        .tab-btn:hover {{ background: #eee; }}
        .tab-btn.active {{
            background: #4a7c23;
            color: white;
            border-color: #4a7c23;
        }}
        .view-container {{ display: none; }}
        .view-container.active {{ display: block; }}
        .days-table {{ font-size: 14px; }}
        .days-table th {{ background: #f0f7e6; }}
        .day-date {{ font-weight: 500; }}

        /* Today view styles */
        .today-table {{ font-size: 14px; }}
        .today-table th {{ background: #e3f2fd; }}
        .status-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .status-working {{
            background: #c8e6c9;
            color: #2e7d32;
        }}
        .status-completed {{
            background: #e0e0e0;
            color: #616161;
        }}
        .today-summary {{
            display: flex;
            gap: 20px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }}
        .today-stat {{
            background: #f5f5f5;
            padding: 12px 20px;
            border-radius: 8px;
            text-align: center;
        }}
        .today-stat .number {{
            font-size: 24px;
            font-weight: 600;
            color: #4a7c23;
        }}
        .today-stat .label {{
            font-size: 12px;
            color: #666;
        }}
        .today-stat.working .number {{ color: #2e7d32; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Time Tracker Dashboard</h1>
            <div class="user-info">
                <span>{user_name}</span>
                {'<span class="admin-badge">ADMIN</span>' if is_admin else ''}
                <a href="/logout" class="logout-btn">Logout</a>
            </div>
        </div>
        <div class="card">
            <div class="filters">
                {employee_filter_html}
                <div>
                    <label>From:</label>
                    <input type="date" id="startDate">
                </div>
                <div>
                    <label>To:</label>
                    <input type="date" id="endDate">
                </div>
                <div>
                    <label>Quick:</label>
                    <select id="periodFilter" onchange="applyQuickPeriod()">
                        <option value="">Custom</option>
                        <option value="1">Past 1 Week</option>
                        <option value="2" selected>Past 2 Weeks</option>
                        <option value="3">Past 3 Weeks</option>
                        <option value="4">Past 4 Weeks</option>
                    </select>
                </div>
                <button onclick="loadData()">Apply Filters</button>
                {download_btn_html}
            </div>

            {summary_cards_html}

            <div class="view-tabs">
                <button class="tab-btn" onclick="showView('today')">Today</button>
                <button class="tab-btn active" onclick="showView('summary')">Summary</button>
                <button class="tab-btn" onclick="showView('days')">View Days</button>
            </div>

            <div id="todayView" class="view-container">
                <div id="todayContainer">
                    <div class="loading">Loading...</div>
                </div>
            </div>

            <div id="summaryView" class="view-container active">
                <div id="tableContainer">
                    <div class="loading">Loading...</div>
                </div>
            </div>

            <div id="daysView" class="view-container">
                <div id="daysContainer">
                    <div class="loading">Select filters and click Apply to view days</div>
                </div>
            </div>

            {edit_section}

            {audit_section}
        </div>
    </div>

    <script>
        const isAdmin = {'true' if is_admin else 'false'};
        const userEmployeeName = "{employee_name_hint}";
        let currentData = [];
        let allEmployees = [];

        function initDates() {{
            const today = new Date();
            const twoWeeksAgo = new Date(today);
            twoWeeksAgo.setDate(today.getDate() - 14);
            document.getElementById('endDate').value = today.toISOString().split('T')[0];
            document.getElementById('startDate').value = twoWeeksAgo.toISOString().split('T')[0];

            // Set edit date to today
            const editDate = document.getElementById('editDate');
            if (editDate) editDate.value = today.toISOString().split('T')[0];
        }}

        function applyQuickPeriod() {{
            const weeks = document.getElementById('periodFilter').value;
            if (!weeks) return;
            const today = new Date();
            const startDate = new Date(today);
            startDate.setDate(today.getDate() - (weeks * 7));
            document.getElementById('endDate').value = today.toISOString().split('T')[0];
            document.getElementById('startDate').value = startDate.toISOString().split('T')[0];
        }}

        async function loadData() {{
            const employee = document.getElementById('employeeFilter').value;
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;

            if (!startDate || !endDate) {{
                alert('Please select both start and end dates');
                return;
            }}

            document.getElementById('tableContainer').innerHTML = '<div class="loading">Loading...</div>';

            try {{
                const response = await fetch(`/dashboard/data?start=${{startDate}}&end=${{endDate}}&employee=${{encodeURIComponent(employee)}}`);
                const data = await response.json();
                currentData = data;
                allEmployees = data.all_employees || [];
                renderTable(data);
                if (isAdmin) {{
                    updateSummary(data);
                    updateEmployeeFilter(data.all_employees);
                    updateEditEmployeeSelect(data.all_employees);
                }}
                // Reload days view if it's currently active
                if (document.getElementById('daysView').classList.contains('active')) {{
                    loadDays();
                }}
            }} catch (error) {{
                document.getElementById('tableContainer').innerHTML = '<div class="loading">Error loading data</div>';
            }}
        }}

        function updateSummary(data) {{
            const empEl = document.getElementById('totalEmployees');
            const hoursEl = document.getElementById('totalHours');
            if (empEl) empEl.textContent = data.summary.length;
            if (hoursEl) hoursEl.textContent = data.total_hours.toFixed(1);
        }}

        function updateEmployeeFilter(employees) {{
            const select = document.getElementById('employeeFilter');
            if (!select || select.type === 'hidden') return;
            const currentValue = select.value;
            select.innerHTML = '<option value="">All Employees</option>';
            employees.forEach(emp => {{
                const option = document.createElement('option');
                option.value = emp;
                option.textContent = emp;
                if (emp === currentValue) option.selected = true;
                select.appendChild(option);
            }});
        }}

        function updateEditEmployeeSelect(employees) {{
            const select = document.getElementById('editEmployee');
            if (!select || select.tagName !== 'SELECT') return;
            select.innerHTML = '<option value="">Select employee...</option>';
            employees.forEach(emp => {{
                const option = document.createElement('option');
                option.value = emp;
                option.textContent = emp;
                select.appendChild(option);
            }});
        }}

        function renderTable(data) {{
            if (data.summary.length === 0) {{
                document.getElementById('tableContainer').innerHTML = '<div class="loading">No data found for this period</div>';
                return;
            }}

            let html = `
                <table>
                    <thead>
                        <tr>
                            <th>Employee</th>
                            <th>Hours</th>
                            <th>Days Worked</th>
                            <th>Avg/Day</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            data.summary.forEach(row => {{
                const avgPerDay = row.days_worked > 0 ? (row.total_hours / row.days_worked).toFixed(1) : '0';
                html += `
                    <tr>
                        <td class="employee-name">${{row.employee}}</td>
                        <td>${{row.total_hours.toFixed(1)}} hrs</td>
                        <td>${{row.days_worked}}</td>
                        <td>${{avgPerDay}} hrs</td>
                    </tr>
                `;
            }});

            html += `
                    <tr class="total-row">
                        <td>Total</td>
                        <td>${{data.total_hours.toFixed(1)}} hrs</td>
                        <td>-</td>
                        <td>-</td>
                    </tr>
                </tbody></table>
            `;

            document.getElementById('tableContainer').innerHTML = html;
        }}

        // Tab switching
        function showView(view) {{
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.view-container').forEach(c => c.classList.remove('active'));

            const tabs = document.querySelectorAll('.tab-btn');
            if (view === 'today') {{
                tabs[0].classList.add('active');
                document.getElementById('todayView').classList.add('active');
                loadToday();
            }} else if (view === 'summary') {{
                tabs[1].classList.add('active');
                document.getElementById('summaryView').classList.add('active');
            }} else {{
                tabs[2].classList.add('active');
                document.getElementById('daysView').classList.add('active');
                loadDays();
            }}
        }}

        async function loadToday() {{
            document.getElementById('todayContainer').innerHTML = '<div class="loading">Loading...</div>';

            try {{
                const response = await fetch('/dashboard/today');
                const data = await response.json();
                renderToday(data);
            }} catch (error) {{
                document.getElementById('todayContainer').innerHTML = '<div class="loading">Error loading data</div>';
            }}
        }}

        function renderToday(data) {{
            if (!data.entries || data.entries.length === 0) {{
                document.getElementById('todayContainer').innerHTML = '<div class="loading">No one has clocked in today</div>';
                return;
            }}

            var workingCount = 0;
            var completedCount = 0;
            for (var i = 0; i < data.entries.length; i++) {{
                if (data.entries[i].status === 'working') workingCount++;
                else completedCount++;
            }}

            var html = '<div class="today-summary">' +
                '<div class="today-stat working"><div class="number">' + workingCount + '</div><div class="label">Currently Working</div></div>' +
                '<div class="today-stat"><div class="number">' + completedCount + '</div><div class="label">Completed Shift</div></div>' +
                '<div class="today-stat"><div class="number">' + data.entries.length + '</div><div class="label">Total Today</div></div>' +
                '</div>' +
                '<table class="today-table"><thead><tr>' +
                '<th>Employee</th><th>Status</th><th>Clock In</th><th>Clock Out</th><th>Hours</th>' +
                '</tr></thead><tbody>';

            for (var j = 0; j < data.entries.length; j++) {{
                var entry = data.entries[j];
                var statusClass = entry.status === 'working' ? 'status-working' : 'status-completed';
                var statusText = entry.status === 'working' ? 'Working' : 'Completed';
                var hours = entry.hours ? entry.hours.toFixed(1) : '-';
                html += '<tr>' +
                    '<td class="employee-name">' + entry.employee + '</td>' +
                    '<td><span class="status-badge ' + statusClass + '">' + statusText + '</span></td>' +
                    '<td>' + (entry.clock_in || '-') + '</td>' +
                    '<td>' + (entry.clock_out || '-') + '</td>' +
                    '<td>' + hours + ' hrs</td>' +
                    '</tr>';
            }}

            html += '</tbody></table>';
            document.getElementById('todayContainer').innerHTML = html;
        }}

        async function loadDays() {{
            const employee = document.getElementById('employeeFilter').value;
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;

            if (!startDate || !endDate) {{
                document.getElementById('daysContainer').innerHTML = '<div class="loading">Please select date range first</div>';
                return;
            }}

            document.getElementById('daysContainer').innerHTML = '<div class="loading">Loading daily breakdown...</div>';

            try {{
                const response = await fetch(`/dashboard/details?start=${{startDate}}&end=${{endDate}}&employee=${{encodeURIComponent(employee)}}`);
                const data = await response.json();
                renderDays(data.entries);
            }} catch (error) {{
                document.getElementById('daysContainer').innerHTML = '<div class="loading">Error loading data</div>';
            }}
        }}

        function renderDays(entries) {{
            if (!entries || entries.length === 0) {{
                document.getElementById('daysContainer').innerHTML = '<div class="loading">No daily entries found for this period</div>';
                return;
            }}

            let html = `
                <table class="days-table">
                    <thead>
                        <tr>
                            <th>Date</th>
                            ${{isAdmin ? '<th>Employee</th>' : ''}}
                            <th>Clock In</th>
                            <th>Clock Out</th>
                            <th>Hours</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            entries.forEach(entry => {{
                const hours = entry.hours ? entry.hours.toFixed(1) : '-';
                html += `
                    <tr>
                        <td class="day-date">${{entry.date}}</td>
                        ${{isAdmin ? `<td class="employee-name">${{entry.employee}}</td>` : ''}}
                        <td>${{entry.clock_in || '-'}}</td>
                        <td>${{entry.clock_out || '-'}}</td>
                        <td>${{hours}} hrs</td>
                    </tr>
                `;
            }});

            html += '</tbody></table>';
            document.getElementById('daysContainer').innerHTML = html;
        }}

        // Edit time entry functions
        async function loadDayData() {{
            const date = document.getElementById('editDate').value;
            let employee;

            if (isAdmin) {{
                employee = document.getElementById('editEmployee').value;
                if (!employee || !date) {{
                    document.getElementById('editFields').style.display = 'none';
                    return;
                }}
            }} else {{
                employee = userEmployeeName;
                if (!date) {{
                    document.getElementById('editFields').style.display = 'none';
                    return;
                }}
            }}

            const statusEl = document.getElementById('editStatus');
            statusEl.className = 'edit-status info';
            statusEl.textContent = 'Loading...';
            document.getElementById('editFields').style.display = 'block';

            try {{
                const response = await fetch(`/dashboard/day-entry?date=${{date}}&employee=${{encodeURIComponent(employee)}}`);
                const data = await response.json();

                if (data.clock_in) {{
                    document.getElementById('editClockIn').value = data.clock_in;
                }} else {{
                    document.getElementById('editClockIn').value = '';
                }}

                if (data.clock_out) {{
                    document.getElementById('editClockOut').value = data.clock_out;
                }} else {{
                    document.getElementById('editClockOut').value = '';
                }}

                if (data.clock_in || data.clock_out) {{
                    statusEl.className = 'edit-status info';
                    statusEl.textContent = `Found entry: ${{data.clock_in || '?'}} - ${{data.clock_out || '?'}}`;
                }} else {{
                    statusEl.className = 'edit-status info';
                    statusEl.textContent = 'No entry found for this date. Add new times below.';
                }}
            }} catch (error) {{
                statusEl.className = 'edit-status error';
                statusEl.textContent = 'Error loading data';
            }}
        }}

        async function saveTimeEntry() {{
            const date = document.getElementById('editDate').value;
            const clockIn = document.getElementById('editClockIn').value;
            const clockOut = document.getElementById('editClockOut').value;
            let employee;

            if (isAdmin) {{
                employee = document.getElementById('editEmployee').value;
            }} else {{
                // For non-admin, we need to find their actual employee name from the data
                if (currentData.summary && currentData.summary.length > 0) {{
                    employee = currentData.summary[0].employee;
                }} else {{
                    employee = userEmployeeName;
                }}
            }}

            if (!date) {{
                alert('Please select a date');
                return;
            }}

            if (!clockIn && !clockOut) {{
                alert('Please enter at least one time');
                return;
            }}

            const statusEl = document.getElementById('editStatus');
            statusEl.className = 'edit-status info';
            statusEl.textContent = 'Saving...';

            try {{
                const response = await fetch('/dashboard/adjust', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        employee: employee,
                        date: date,
                        clock_in: clockIn,
                        clock_out: clockOut
                    }})
                }});

                const result = await response.json();

                if (response.ok) {{
                    statusEl.className = 'edit-status success';
                    statusEl.textContent = 'Saved successfully!';
                    loadData();
                    if (isAdmin) loadAuditLog();
                }} else {{
                    statusEl.className = 'edit-status error';
                    statusEl.textContent = 'Error: ' + (result.error || 'Failed to save');
                }}
            }} catch (error) {{
                statusEl.className = 'edit-status error';
                statusEl.textContent = 'Error saving changes';
            }}
        }}

        function downloadCSV() {{
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            const employee = document.getElementById('employeeFilter').value;
            window.location.href = `/dashboard/download?start=${{startDate}}&end=${{endDate}}&employee=${{encodeURIComponent(employee)}}`;
        }}

        async function loadAuditLog() {{
            if (!isAdmin) return;
            try {{
                const response = await fetch('/dashboard/audit?limit=50');
                const data = await response.json();
                renderAuditLog(data.logs);
            }} catch (error) {{
                const container = document.getElementById('auditContainer');
                if (container) container.innerHTML = '<div class="loading">Error loading audit log</div>';
            }}
        }}

        function formatAction(action) {{
            const labels = {{
                'adjust_clock_in': 'Adjusted In',
                'adjust_clock_out': 'Adjusted Out',
                'late_clock_out': 'Late Out',
                'dashboard_adjust': 'Dashboard Edit'
            }};
            return labels[action] || action;
        }}

        function renderAuditLog(logs) {{
            const container = document.getElementById('auditContainer');
            if (!container) return;

            if (!logs || logs.length === 0) {{
                container.innerHTML = '<div class="loading">No adjustments recorded</div>';
                return;
            }}

            let html = `
                <table class="audit-table">
                    <thead>
                        <tr>
                            <th>Date/Time</th>
                            <th>Employee</th>
                            <th>Action</th>
                            <th>Change</th>
                            <th>Details</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            logs.forEach(log => {{
                const changeHtml = log.old_value
                    ? `${{log.old_value}}<span class="change-arrow">-></span>${{log.new_value}}`
                    : log.new_value || '-';

                html += `
                    <tr>
                        <td>${{log.timestamp}}</td>
                        <td class="employee-name">${{log.employee_name}}</td>
                        <td><span class="action-badge action-${{log.action}}">${{formatAction(log.action)}}</span></td>
                        <td>${{changeHtml}}</td>
                        <td>${{log.details || '-'}}</td>
                        <td><button class="btn-delete" onclick="deleteAuditLog(${{log.id}})">Delete</button></td>
                    </tr>
                `;
            }});

            html += '</tbody></table>';
            container.innerHTML = html;
        }}

        async function deleteAuditLog(id) {{
            if (!confirm('Delete this audit log entry?')) return;

            try {{
                const response = await fetch(`/dashboard/audit/${{id}}`, {{
                    method: 'DELETE'
                }});

                if (response.ok) {{
                    loadAuditLog();
                }} else {{
                    const result = await response.json();
                    alert('Error: ' + (result.error || 'Failed to delete'));
                }}
            }} catch (error) {{
                alert('Error deleting audit log');
            }}
        }}

        // Initialize
        initDates();
        loadData();
        if (isAdmin) loadAuditLog();
    </script>
</body>
</html>
'''


# =============================================================================
# ROUTES
# =============================================================================

@dashboard_bp.route('/dashboard')
def dashboard():
    """Serve the web dashboard."""
    user = get_current_user()
    if not user:
        return LOGIN_HTML
    return get_dashboard_html(user)


@dashboard_bp.route('/dashboard/data')
def dashboard_data():
    """API endpoint for dashboard data."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    is_admin = is_admin_user(user)
    employee_filter = request.args.get('employee', '').strip()

    # Non-admins can only see their own data
    if not is_admin:
        user_employee_name = get_employee_name_from_email(user['email'])
        employee_filter = user_employee_name

    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    today = now_local().date()

    if start_str and end_str:
        try:
            start_date = datetime.combine(
                datetime.strptime(start_str, '%Y-%m-%d').date(),
                datetime.min.time()
            ).replace(tzinfo=TIMEZONE)
            end_date = datetime.combine(
                datetime.strptime(end_str, '%Y-%m-%d').date(),
                datetime.max.time()
            ).replace(tzinfo=TIMEZONE)
        except ValueError:
            end_date = datetime.combine(today, datetime.max.time()).replace(tzinfo=TIMEZONE)
            start_date = datetime.combine(today - timedelta(days=14), datetime.min.time()).replace(tzinfo=TIMEZONE)
    else:
        end_date = datetime.combine(today, datetime.max.time()).replace(tzinfo=TIMEZONE)
        start_date = datetime.combine(today - timedelta(days=14), datetime.min.time()).replace(tzinfo=TIMEZONE)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT DISTINCT employee_name FROM clock_events ORDER BY employee_name')
            all_employees = [row[0] for row in cursor.fetchall()]

            query = '''
                SELECT
                    employee_name,
                    SUM(work_duration_minutes) as total_minutes,
                    COUNT(DISTINCT DATE(timestamp)) as days_worked,
                    COUNT(*) as sessions
                FROM clock_events
                WHERE event_type = 'clock_out'
                AND timestamp BETWEEN %s AND %s
            '''
            params = [start_date, end_date]

            if employee_filter:
                # Case-insensitive match for non-admin users
                if not is_admin:
                    query += ' AND LOWER(employee_name) LIKE LOWER(%s)'
                    params.append(f'%{employee_filter}%')
                else:
                    query += ' AND employee_name = %s'
                    params.append(employee_filter)

            query += ' GROUP BY employee_name ORDER BY employee_name'
            cursor.execute(query, params)
            results = cursor.fetchall()

    summary = []
    total_hours = 0
    total_sessions = 0

    for row in results:
        hours = (row[1] or 0) / 60
        summary.append({
            'employee': row[0],
            'total_hours': round(hours, 2),
            'days_worked': row[2],
            'sessions': row[3]
        })
        total_hours += hours
        total_sessions += row[3]

    return jsonify({
        'summary': summary,
        'total_hours': round(total_hours, 2),
        'total_sessions': total_sessions,
        'all_employees': all_employees if is_admin else [],
        'period': {
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d')
        }
    })


@dashboard_bp.route('/dashboard/today')
def dashboard_today():
    """API endpoint for today's clock-in/out activity."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    is_admin = is_admin_user(user)
    # Get today's date in local timezone
    today = now_local().date()
    # Database stores timestamps as naive local time (PST), so use naive boundaries
    day_start = datetime.combine(today, datetime.min.time())
    day_end = datetime.combine(today, datetime.max.time())

    # For non-admins, filter to their own data
    user_employee_name = None
    if not is_admin:
        user_employee_name = get_employee_name_from_email(user['email'])

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Get all clock events for today
            if is_admin:
                cursor.execute('''
                    SELECT id, employee_name, event_type, timestamp, work_duration_minutes, source
                    FROM clock_events
                    WHERE timestamp BETWEEN %s AND %s
                    ORDER BY employee_name, timestamp
                ''', (day_start, day_end))
            else:
                cursor.execute('''
                    SELECT id, employee_name, event_type, timestamp, work_duration_minutes, source
                    FROM clock_events
                    WHERE timestamp BETWEEN %s AND %s
                    AND LOWER(employee_name) LIKE LOWER(%s)
                    ORDER BY employee_name, timestamp
                ''', (day_start, day_end, f'%{user_employee_name}%'))

            results = cursor.fetchall()

    # Group events by employee
    employees = {}
    for row in results:
        event_id, employee, event_type, timestamp, duration, source = row

        # Handle timezone based on source:
        # - 'wifi' (warehouse): timestamps stored as naive PST
        # - 'slack' (remote): timestamps stored as naive UTC
        if timestamp.tzinfo is None:
            if source == 'slack':
                # Remote clock-ins are stored in UTC, convert to PST
                timestamp = timestamp.replace(tzinfo=ZoneInfo('UTC')).astimezone(TIMEZONE)
            else:
                # Warehouse wifi clock-ins are stored in PST
                timestamp = timestamp.replace(tzinfo=TIMEZONE)
        else:
            timestamp = timestamp.astimezone(TIMEZONE)

        if employee not in employees:
            employees[employee] = {
                'employee': employee,
                'clock_in': None,
                'clock_out': None,
                'hours': None,
                'status': 'working'
            }

        if event_type == 'clock_in':
            employees[employee]['clock_in'] = timestamp.strftime('%I:%M %p').lstrip('0')
        elif event_type == 'clock_out':
            employees[employee]['clock_out'] = timestamp.strftime('%I:%M %p').lstrip('0')
            employees[employee]['status'] = 'completed'
            if duration:
                employees[employee]['hours'] = duration / 60

    # Sort: working first, then by employee name
    entries = sorted(
        employees.values(),
        key=lambda x: (0 if x['status'] == 'working' else 1, x['employee'])
    )

    return jsonify({
        'entries': entries,
        'date': today.strftime('%Y-%m-%d')
    })


@dashboard_bp.route('/dashboard/details')
def dashboard_details():
    """API endpoint for detailed daily entries with edit capability."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    is_admin = is_admin_user(user)
    employee_filter = request.args.get('employee', '').strip()

    if not is_admin:
        user_employee_name = get_employee_name_from_email(user['email'])
        employee_filter = user_employee_name

    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    today = now_local().date()

    if start_str and end_str:
        try:
            start_date = datetime.combine(
                datetime.strptime(start_str, '%Y-%m-%d').date(),
                datetime.min.time()
            ).replace(tzinfo=TIMEZONE)
            end_date = datetime.combine(
                datetime.strptime(end_str, '%Y-%m-%d').date(),
                datetime.max.time()
            ).replace(tzinfo=TIMEZONE)
        except ValueError:
            end_date = datetime.combine(today, datetime.max.time()).replace(tzinfo=TIMEZONE)
            start_date = datetime.combine(today - timedelta(days=14), datetime.min.time()).replace(tzinfo=TIMEZONE)
    else:
        end_date = datetime.combine(today, datetime.max.time()).replace(tzinfo=TIMEZONE)
        start_date = datetime.combine(today - timedelta(days=14), datetime.min.time()).replace(tzinfo=TIMEZONE)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            query = '''
                SELECT id, employee_name, event_type, timestamp, work_duration_minutes
                FROM clock_events
                WHERE timestamp BETWEEN %s AND %s
            '''
            params = [start_date, end_date]

            if employee_filter:
                if not is_admin:
                    query += ' AND LOWER(employee_name) LIKE LOWER(%s)'
                    params.append(f'%{employee_filter}%')
                else:
                    query += ' AND employee_name = %s'
                    params.append(employee_filter)

            query += ' ORDER BY employee_name, timestamp'
            cursor.execute(query, params)
            results = cursor.fetchall()

    # Group events by employee and date
    entries = {}
    for row in results:
        event_id, employee, event_type, timestamp, duration = row

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=ZoneInfo('UTC')).astimezone(TIMEZONE)
        else:
            timestamp = timestamp.astimezone(TIMEZONE)

        date_str = timestamp.strftime('%Y-%m-%d')
        key = f"{employee}_{date_str}"

        if key not in entries:
            entries[key] = {
                'employee': employee,
                'date': date_str,
                'clock_in': None,
                'clock_out': None,
                'clock_in_raw': None,
                'clock_out_raw': None,
                'clock_in_id': None,
                'clock_out_id': None,
                'hours': None
            }

        if event_type == 'clock_in':
            entries[key]['clock_in'] = timestamp.strftime('%I:%M %p').lstrip('0')
            entries[key]['clock_in_raw'] = timestamp.strftime('%H:%M')
            entries[key]['clock_in_id'] = event_id
        elif event_type == 'clock_out':
            entries[key]['clock_out'] = timestamp.strftime('%I:%M %p').lstrip('0')
            entries[key]['clock_out_raw'] = timestamp.strftime('%H:%M')
            entries[key]['clock_out_id'] = event_id
            if duration:
                entries[key]['hours'] = duration / 60

    return jsonify({
        'entries': sorted(entries.values(), key=lambda x: (x['date'], x['employee']), reverse=True)
    })


@dashboard_bp.route('/dashboard/adjust', methods=['POST'])
def dashboard_adjust():
    """API endpoint to adjust time entries from dashboard."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    is_admin = is_admin_user(user)
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    employee = data.get('employee', '').strip()
    date_str = data.get('date', '').strip()
    clock_in_str = data.get('clock_in', '').strip()
    clock_out_str = data.get('clock_out', '').strip()

    if not employee or not date_str:
        return jsonify({'error': 'Employee and date are required'}), 400

    # Non-admins can only adjust their own entries
    if not is_admin:
        user_employee_name = get_employee_name_from_email(user['email'])
        if user_employee_name.lower() not in employee.lower():
            return jsonify({'error': 'You can only adjust your own time entries'}), 403

    try:
        entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    day_start = datetime.combine(entry_date, datetime.min.time()).replace(tzinfo=TIMEZONE)
    day_end = datetime.combine(entry_date, datetime.max.time()).replace(tzinfo=TIMEZONE)

    adjusted_by = user['email']

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Handle clock-in adjustment
            if clock_in_str:
                try:
                    clock_in_time = datetime.strptime(clock_in_str, '%H:%M').time()
                    new_clock_in = datetime.combine(entry_date, clock_in_time).replace(tzinfo=TIMEZONE)
                except ValueError:
                    return jsonify({'error': 'Invalid clock-in time format'}), 400

                # Find existing clock-in
                cursor.execute('''
                    SELECT id, timestamp FROM clock_events
                    WHERE employee_name = %s AND event_type = 'clock_in'
                    AND timestamp BETWEEN %s AND %s
                    ORDER BY timestamp DESC LIMIT 1
                ''', (employee, day_start, day_end))
                existing = cursor.fetchone()

                if existing:
                    old_time = existing[1]
                    if old_time.tzinfo is None:
                        old_time = old_time.replace(tzinfo=ZoneInfo('UTC')).astimezone(TIMEZONE)

                    cursor.execute('UPDATE clock_events SET timestamp = %s WHERE id = %s',
                                   (new_clock_in, existing[0]))

                    log_audit(
                        employee_name=employee,
                        action='dashboard_adjust',
                        details=f"Adjusted clock-in for {date_str}",
                        old_value=format_time(old_time),
                        new_value=format_time(new_clock_in),
                        adjusted_by=adjusted_by
                    )
                else:
                    # Create new clock-in
                    cursor.execute('''
                        INSERT INTO clock_events (mac_address, employee_name, event_type, timestamp, source)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (f'DASHBOARD-{employee}', employee, 'clock_in', new_clock_in, 'dashboard'))

                    log_audit(
                        employee_name=employee,
                        action='dashboard_adjust',
                        details=f"Added clock-in for {date_str}",
                        old_value=None,
                        new_value=format_time(new_clock_in),
                        adjusted_by=adjusted_by
                    )

            # Handle clock-out adjustment
            if clock_out_str:
                try:
                    clock_out_time = datetime.strptime(clock_out_str, '%H:%M').time()
                    new_clock_out = datetime.combine(entry_date, clock_out_time).replace(tzinfo=TIMEZONE)
                except ValueError:
                    return jsonify({'error': 'Invalid clock-out time format'}), 400

                # Calculate work duration if we have clock-in
                work_minutes = None
                cursor.execute('''
                    SELECT timestamp FROM clock_events
                    WHERE employee_name = %s AND event_type = 'clock_in'
                    AND timestamp BETWEEN %s AND %s
                    ORDER BY timestamp DESC LIMIT 1
                ''', (employee, day_start, day_end))
                clock_in_result = cursor.fetchone()

                if clock_in_result:
                    clock_in_ts = clock_in_result[0]
                    if clock_in_ts.tzinfo is None:
                        clock_in_ts = clock_in_ts.replace(tzinfo=ZoneInfo('UTC')).astimezone(TIMEZONE)
                    work_minutes = int((new_clock_out - clock_in_ts).total_seconds() / 60)
                    if work_minutes < 0:
                        return jsonify({'error': 'Clock-out cannot be before clock-in'}), 400

                # Find existing clock-out
                cursor.execute('''
                    SELECT id, timestamp FROM clock_events
                    WHERE employee_name = %s AND event_type = 'clock_out'
                    AND timestamp BETWEEN %s AND %s
                    ORDER BY timestamp DESC LIMIT 1
                ''', (employee, day_start, day_end))
                existing = cursor.fetchone()

                if existing:
                    old_time = existing[1]
                    if old_time.tzinfo is None:
                        old_time = old_time.replace(tzinfo=ZoneInfo('UTC')).astimezone(TIMEZONE)

                    cursor.execute('''
                        UPDATE clock_events SET timestamp = %s, work_duration_minutes = %s WHERE id = %s
                    ''', (new_clock_out, work_minutes, existing[0]))

                    log_audit(
                        employee_name=employee,
                        action='dashboard_adjust',
                        details=f"Adjusted clock-out for {date_str}",
                        old_value=format_time(old_time),
                        new_value=format_time(new_clock_out),
                        adjusted_by=adjusted_by
                    )
                else:
                    # Create new clock-out
                    cursor.execute('''
                        INSERT INTO clock_events (mac_address, employee_name, event_type, timestamp, work_duration_minutes, source)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    ''', (f'DASHBOARD-{employee}', employee, 'clock_out', new_clock_out, work_minutes, 'dashboard'))

                    log_audit(
                        employee_name=employee,
                        action='dashboard_adjust',
                        details=f"Added clock-out for {date_str}",
                        old_value=None,
                        new_value=format_time(new_clock_out),
                        adjusted_by=adjusted_by
                    )

            conn.commit()

    return jsonify({'status': 'ok', 'message': 'Time entry updated'})


@dashboard_bp.route('/dashboard/download')
def dashboard_download():
    """Download CSV of timesheet data."""
    user = get_current_user()
    if not user:
        return redirect('/dashboard')

    is_admin = is_admin_user(user)
    employee_filter = request.args.get('employee', '').strip()

    if not is_admin:
        user_employee_name = get_employee_name_from_email(user['email'])
        employee_filter = user_employee_name

    start_str = request.args.get('start', '')
    end_str = request.args.get('end', '')
    today = now_local().date()

    if start_str and end_str:
        try:
            start_date = datetime.combine(
                datetime.strptime(start_str, '%Y-%m-%d').date(),
                datetime.min.time()
            ).replace(tzinfo=TIMEZONE)
            end_date = datetime.combine(
                datetime.strptime(end_str, '%Y-%m-%d').date(),
                datetime.max.time()
            ).replace(tzinfo=TIMEZONE)
        except ValueError:
            end_date = datetime.combine(today, datetime.max.time()).replace(tzinfo=TIMEZONE)
            start_date = datetime.combine(today - timedelta(days=14), datetime.min.time()).replace(tzinfo=TIMEZONE)
    else:
        end_date = datetime.combine(today, datetime.max.time()).replace(tzinfo=TIMEZONE)
        start_date = datetime.combine(today - timedelta(days=14), datetime.min.time()).replace(tzinfo=TIMEZONE)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            query = '''
                SELECT
                    employee_name,
                    DATE(timestamp) as work_date,
                    SUM(work_duration_minutes) as total_minutes
                FROM clock_events
                WHERE event_type = 'clock_out'
                AND timestamp BETWEEN %s AND %s
            '''
            params = [start_date, end_date]

            if employee_filter:
                if not is_admin:
                    query += ' AND LOWER(employee_name) LIKE LOWER(%s)'
                    params.append(f'%{employee_filter}%')
                else:
                    query += ' AND employee_name = %s'
                    params.append(employee_filter)

            query += ' GROUP BY employee_name, DATE(timestamp) ORDER BY employee_name, work_date'
            cursor.execute(query, params)
            results = cursor.fetchall()

    lines = ['Employee,Date,Minutes,Hours']
    employee_totals = {}

    for row in results:
        employee = row[0]
        date = row[1]
        minutes = row[2] or 0
        hours = round(minutes / 60, 2)
        lines.append(f'{employee},{date},{minutes},{hours}')

        if employee not in employee_totals:
            employee_totals[employee] = 0
        employee_totals[employee] += minutes

    lines.append('')
    lines.append('TOTALS')
    for employee, minutes in sorted(employee_totals.items()):
        hours = round(minutes / 60, 2)
        lines.append(f'{employee},TOTAL,{minutes},{hours}')

    csv_content = '\n'.join(lines)
    filename = f"timesheet_{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}.csv"

    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@dashboard_bp.route('/dashboard/day-entry')
def dashboard_day_entry():
    """API endpoint to get a single day's clock-in/out times for editing."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    is_admin = is_admin_user(user)
    employee = request.args.get('employee', '').strip()
    date_str = request.args.get('date', '').strip()

    if not date_str:
        return jsonify({'error': 'Date is required'}), 400

    # Non-admins can only see their own data
    if not is_admin:
        user_employee_name = get_employee_name_from_email(user['email'])
        employee = user_employee_name

    if not employee:
        return jsonify({'error': 'Employee is required'}), 400

    try:
        entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    day_start = datetime.combine(entry_date, datetime.min.time()).replace(tzinfo=TIMEZONE)
    day_end = datetime.combine(entry_date, datetime.max.time()).replace(tzinfo=TIMEZONE)

    clock_in_time = None
    clock_out_time = None

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Get clock-in
            if is_admin:
                cursor.execute('''
                    SELECT timestamp FROM clock_events
                    WHERE employee_name = %s AND event_type = 'clock_in'
                    AND timestamp BETWEEN %s AND %s
                    ORDER BY timestamp DESC LIMIT 1
                ''', (employee, day_start, day_end))
            else:
                cursor.execute('''
                    SELECT timestamp FROM clock_events
                    WHERE LOWER(employee_name) LIKE LOWER(%s) AND event_type = 'clock_in'
                    AND timestamp BETWEEN %s AND %s
                    ORDER BY timestamp DESC LIMIT 1
                ''', (f'%{employee}%', day_start, day_end))
            result = cursor.fetchone()
            if result:
                ts = result[0]
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=ZoneInfo('UTC')).astimezone(TIMEZONE)
                else:
                    ts = ts.astimezone(TIMEZONE)
                clock_in_time = ts.strftime('%H:%M')

            # Get clock-out
            if is_admin:
                cursor.execute('''
                    SELECT timestamp FROM clock_events
                    WHERE employee_name = %s AND event_type = 'clock_out'
                    AND timestamp BETWEEN %s AND %s
                    ORDER BY timestamp DESC LIMIT 1
                ''', (employee, day_start, day_end))
            else:
                cursor.execute('''
                    SELECT timestamp FROM clock_events
                    WHERE LOWER(employee_name) LIKE LOWER(%s) AND event_type = 'clock_out'
                    AND timestamp BETWEEN %s AND %s
                    ORDER BY timestamp DESC LIMIT 1
                ''', (f'%{employee}%', day_start, day_end))
            result = cursor.fetchone()
            if result:
                ts = result[0]
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=ZoneInfo('UTC')).astimezone(TIMEZONE)
                else:
                    ts = ts.astimezone(TIMEZONE)
                clock_out_time = ts.strftime('%H:%M')

    return jsonify({
        'clock_in': clock_in_time,
        'clock_out': clock_out_time,
        'employee': employee,
        'date': date_str
    })


@dashboard_bp.route('/dashboard/audit')
def dashboard_audit():
    """API endpoint for audit log data (admin only)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    if not is_admin_user(user):
        return jsonify({'error': 'Admin access required'}), 403

    limit = request.args.get('limit', 50, type=int)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT id, timestamp, employee_name, action, details, old_value, new_value
                FROM audit_log
                ORDER BY timestamp DESC
                LIMIT %s
            ''', (limit,))
            results = cursor.fetchall()

    logs = []
    for row in results:
        timestamp = row[1]
        if hasattr(timestamp, 'strftime'):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=ZoneInfo('UTC')).astimezone(TIMEZONE)
            else:
                timestamp = timestamp.astimezone(TIMEZONE)
            timestamp_str = timestamp.strftime('%Y-%m-%d %I:%M %p')
        else:
            timestamp_str = str(timestamp)

        logs.append({
            'id': row[0],
            'timestamp': timestamp_str,
            'employee_name': row[2],
            'action': row[3],
            'details': row[4],
            'old_value': row[5],
            'new_value': row[6]
        })

    return jsonify({'logs': logs})


@dashboard_bp.route('/dashboard/audit/<int:audit_id>', methods=['DELETE'])
def dashboard_audit_delete(audit_id):
    """API endpoint to delete an audit log entry (admin only)."""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    if not is_admin_user(user):
        return jsonify({'error': 'Admin access required'}), 403

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM audit_log WHERE id = %s', (audit_id,))
            deleted = cursor.rowcount
            conn.commit()

    if deleted:
        return jsonify({'status': 'ok', 'message': 'Audit log entry deleted'})
    else:
        return jsonify({'error': 'Audit log entry not found'}), 404
