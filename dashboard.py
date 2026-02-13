#!/usr/bin/env python3
"""
Time Tracker Dashboard

Web dashboard for viewing employee hours.
Imported by api_server.py as a Flask Blueprint.
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, request, jsonify, Response
import psycopg2

# Create Blueprint
dashboard_bp = Blueprint('dashboard', __name__)

# Configuration
DATABASE_URL = os.environ.get('DATABASE_URL')
TIMEZONE = ZoneInfo(os.environ.get('TIMEZONE', 'America/Vancouver'))


def get_db_connection():
    """Get a PostgreSQL database connection."""
    return psycopg2.connect(DATABASE_URL)


def now_local():
    """Get current time in configured timezone."""
    return datetime.now(TIMEZONE)


# =============================================================================
# DASHBOARD HTML
# =============================================================================

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Time Tracker Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
            color: #333;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 {
            background: linear-gradient(135deg, #2d5016 0%, #4a7c23 100%);
            color: white;
            padding: 20px 30px;
            border-radius: 10px 10px 0 0;
            margin-bottom: 0;
        }
        .card {
            background: white;
            border-radius: 0 0 10px 10px;
            padding: 20px 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        .filters {
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            margin-bottom: 20px;
            align-items: center;
        }
        .filters label {
            font-weight: 500;
            margin-right: 5px;
        }
        select, button, input[type="date"] {
            padding: 10px 15px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
        }
        input[type="date"] {
            min-width: 140px;
        }
        button {
            background: #4a7c23;
            color: white;
            border: none;
            cursor: pointer;
            transition: background 0.2s;
        }
        button:hover { background: #2d5016; }
        .btn-download {
            background: #2196F3;
        }
        .btn-download:hover { background: #1976D2; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }
        th, td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        th {
            background: #f9f9f9;
            font-weight: 600;
        }
        tr:hover { background: #f5f5f5; }
        .total-row {
            background: #e8f5e9 !important;
            font-weight: 600;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        .summary-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .summary-card {
            background: #f9f9f9;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .summary-card .number {
            font-size: 24px;
            font-weight: 600;
            color: #4a7c23;
        }
        .summary-card .label {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }
        .employee-name { font-weight: 500; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Time Tracker Dashboard</h1>
        <div class="card">
            <div class="filters">
                <div>
                    <label>Employee:</label>
                    <select id="employeeFilter">
                        <option value="">All Employees</option>
                    </select>
                </div>
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
                <button class="btn-download" onclick="downloadCSV()">Download CSV</button>
            </div>

            <div class="summary-cards" id="summaryCards">
                <div class="summary-card">
                    <div class="number" id="totalEmployees">-</div>
                    <div class="label">Employees</div>
                </div>
                <div class="summary-card">
                    <div class="number" id="totalHours">-</div>
                    <div class="label">Total Hours</div>
                </div>
                <div class="summary-card">
                    <div class="number" id="totalSessions">-</div>
                    <div class="label">Sessions</div>
                </div>
            </div>

            <div id="tableContainer">
                <div class="loading">Loading...</div>
            </div>
        </div>
    </div>

    <script>
        let currentData = [];

        function initDates() {
            const today = new Date();
            const twoWeeksAgo = new Date(today);
            twoWeeksAgo.setDate(today.getDate() - 14);

            document.getElementById('endDate').value = today.toISOString().split('T')[0];
            document.getElementById('startDate').value = twoWeeksAgo.toISOString().split('T')[0];
        }

        function applyQuickPeriod() {
            const weeks = document.getElementById('periodFilter').value;
            if (!weeks) return;

            const today = new Date();
            const startDate = new Date(today);
            startDate.setDate(today.getDate() - (weeks * 7));

            document.getElementById('endDate').value = today.toISOString().split('T')[0];
            document.getElementById('startDate').value = startDate.toISOString().split('T')[0];
        }

        async function loadData() {
            const employee = document.getElementById('employeeFilter').value;
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;

            if (!startDate || !endDate) {
                alert('Please select both start and end dates');
                return;
            }

            document.getElementById('tableContainer').innerHTML = '<div class="loading">Loading...</div>';

            try {
                const response = await fetch(`/dashboard/data?start=${startDate}&end=${endDate}&employee=${encodeURIComponent(employee)}`);
                const data = await response.json();
                currentData = data;
                renderTable(data);
                updateSummary(data);
                updateEmployeeFilter(data.all_employees);
            } catch (error) {
                document.getElementById('tableContainer').innerHTML = '<div class="loading">Error loading data</div>';
            }
        }

        function updateSummary(data) {
            document.getElementById('totalEmployees').textContent = data.summary.length;
            document.getElementById('totalHours').textContent = data.total_hours.toFixed(1);
            document.getElementById('totalSessions').textContent = data.total_sessions;
        }

        function updateEmployeeFilter(employees) {
            const select = document.getElementById('employeeFilter');
            const currentValue = select.value;
            select.innerHTML = '<option value="">All Employees</option>';
            employees.forEach(emp => {
                const option = document.createElement('option');
                option.value = emp;
                option.textContent = emp;
                if (emp === currentValue) option.selected = true;
                select.appendChild(option);
            });
        }

        function renderTable(data) {
            if (data.summary.length === 0) {
                document.getElementById('tableContainer').innerHTML = '<div class="loading">No data found for this period</div>';
                return;
            }

            let html = `
                <table>
                    <thead>
                        <tr>
                            <th>Employee</th>
                            <th>Hours</th>
                            <th>Days Worked</th>
                            <th>Sessions</th>
                            <th>Avg/Day</th>
                        </tr>
                    </thead>
                    <tbody>
            `;

            data.summary.forEach(row => {
                const avgPerDay = row.days_worked > 0 ? (row.total_hours / row.days_worked).toFixed(1) : '0';
                html += `
                    <tr>
                        <td class="employee-name">${row.employee}</td>
                        <td>${row.total_hours.toFixed(1)} hrs</td>
                        <td>${row.days_worked}</td>
                        <td>${row.sessions}</td>
                        <td>${avgPerDay} hrs</td>
                    </tr>
                `;
            });

            html += `
                    <tr class="total-row">
                        <td>Total</td>
                        <td>${data.total_hours.toFixed(1)} hrs</td>
                        <td>-</td>
                        <td>${data.total_sessions}</td>
                        <td>-</td>
                    </tr>
                </tbody></table>
            `;

            document.getElementById('tableContainer').innerHTML = html;
        }

        function downloadCSV() {
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;
            const employee = document.getElementById('employeeFilter').value;
            window.location.href = `/dashboard/download?start=${startDate}&end=${endDate}&employee=${encodeURIComponent(employee)}`;
        }

        // Initialize dates and load data on page load
        initDates();
        loadData();
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
    return DASHBOARD_HTML


@dashboard_bp.route('/dashboard/data')
def dashboard_data():
    """API endpoint for dashboard data."""
    employee_filter = request.args.get('employee', '').strip()

    # Get date range from parameters or default to past 2 weeks
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
            # Fallback to past 2 weeks if invalid dates
            end_date = datetime.combine(today, datetime.max.time()).replace(tzinfo=TIMEZONE)
            start_date = datetime.combine(today - timedelta(days=14), datetime.min.time()).replace(tzinfo=TIMEZONE)
    else:
        # Default: past 2 weeks
        end_date = datetime.combine(today, datetime.max.time()).replace(tzinfo=TIMEZONE)
        start_date = datetime.combine(today - timedelta(days=14), datetime.min.time()).replace(tzinfo=TIMEZONE)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Get all employees for filter dropdown
            cursor.execute('SELECT DISTINCT employee_name FROM clock_events ORDER BY employee_name')
            all_employees = [row[0] for row in cursor.fetchall()]

            # Get summary data
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
        'all_employees': all_employees,
        'period': {
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d')
        }
    })


@dashboard_bp.route('/dashboard/download')
def dashboard_download():
    """Download CSV of timesheet data."""
    employee_filter = request.args.get('employee', '').strip()

    # Get date range from parameters or default to past 2 weeks
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
                query += ' AND employee_name = %s'
                params.append(employee_filter)

            query += ' GROUP BY employee_name, DATE(timestamp) ORDER BY employee_name, work_date'

            cursor.execute(query, params)
            results = cursor.fetchall()

    # Build CSV
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

    # Add totals
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
