#!/usr/bin/env python3
"""
Unified Time Tracker API Server (for Sevalla deployment)

This server handles:
1. Slack slash commands (/clockin, /clockout, /hours) for remote employees
2. API endpoints for the laptop's WiFi tracker to push events
3. All data stored in PostgreSQL

Deploy this to Sevalla, then configure:
- Slack slash commands to point to this server
- Laptop's time_tracker.py to push events here

Environment Variables (set in Sevalla):
- DATABASE_URL: PostgreSQL connection string (Sevalla provides this)
- SLACK_SIGNING_SECRET: From your Slack app
- SLACK_WEBHOOK_URL: For sending notifications
- API_SECRET: Secret key for laptop to authenticate when pushing events
"""

import os
import json
import hmac
import time
import hashlib
import smtplib
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from flask import Flask, request, jsonify
from functools import wraps
import requests
import random

app = Flask(__name__)
_db_initialized = False

# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.environ.get('DATABASE_URL')
SLACK_SIGNING_SECRET = os.environ.get('SLACK_SIGNING_SECRET', '')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')
API_SECRET = os.environ.get('API_SECRET', '')  # For laptop authentication

# Email configuration for reports
SMTP_HOST = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER = os.environ.get('SMTP_USER', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
REPORT_EMAIL_TO = os.environ.get('REPORT_EMAIL_TO', '')

# Slack message templates
SLACK_MESSAGES = {
    "clock_in": [
        "🟢 {name} clocked in at {time}",
        "🟢 {name} started work at {time}",
    ],
    "clock_out": [
        "🔴 {name} clocked out at {time}",
        "🔴 {name} finished work at {time}",
    ],
}

# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def get_db_connection():
    """Get a PostgreSQL database connection."""
    return psycopg2.connect(DATABASE_URL)


def init_database():
    """Initialize the PostgreSQL database with required tables."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS clock_events (
                    id SERIAL PRIMARY KEY,
                    mac_address TEXT NOT NULL,
                    employee_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    work_duration_minutes INTEGER,
                    source TEXT DEFAULT 'wifi'
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS remote_employees (
                    slack_user_id TEXT PRIMARY KEY,
                    employee_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_clock_events_timestamp
                ON clock_events(timestamp)
            ''')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_clock_events_mac
                ON clock_events(mac_address)
            ''')

            conn.commit()
    print("Database initialized")


@app.before_request
def ensure_db_initialized():
    """Initialize database tables on first request."""
    global _db_initialized
    if not _db_initialized and DATABASE_URL:
        try:
            init_database()
            _db_initialized = True
        except Exception as e:
            print(f"Database init error: {e}")


def record_clock_event(
    mac_address: str,
    employee_name: str,
    event_type: str,
    timestamp: datetime,
    work_duration_minutes: Optional[int] = None,
    source: str = 'wifi'
) -> None:
    """Record a clock-in or clock-out event to the database."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO clock_events
                (mac_address, employee_name, event_type, timestamp, work_duration_minutes, source)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (mac_address, employee_name, event_type, timestamp, work_duration_minutes, source))
            conn.commit()


def get_last_event(mac_address: str) -> Optional[Tuple[str, datetime]]:
    """Get the most recent event for a MAC address."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT event_type, timestamp FROM clock_events
                WHERE mac_address = %s
                ORDER BY timestamp DESC
                LIMIT 1
            ''', (mac_address,))
            result = cursor.fetchone()
            if result:
                return result[0], result[1]
            return None


def get_last_clock_in(mac_address: str) -> Optional[datetime]:
    """Get the timestamp of the most recent clock-in for a MAC address."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT timestamp FROM clock_events
                WHERE mac_address = %s AND event_type = 'clock_in'
                ORDER BY timestamp DESC
                LIMIT 1
            ''', (mac_address,))
            result = cursor.fetchone()
            if result:
                return result[0]
            return None


# =============================================================================
# REMOTE EMPLOYEE FUNCTIONS
# =============================================================================

def get_remote_employee(slack_user_id: str) -> Optional[str]:
    """Get employee name from Slack user ID."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT employee_name FROM remote_employees WHERE slack_user_id = %s',
                (slack_user_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else None


def register_remote_employee(slack_user_id: str, employee_name: str) -> None:
    """Register a new remote employee."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO remote_employees (slack_user_id, employee_name)
                VALUES (%s, %s)
                ON CONFLICT (slack_user_id) DO UPDATE SET employee_name = %s
            ''', (slack_user_id, employee_name, employee_name))
            conn.commit()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_duration(minutes: int) -> str:
    """Convert minutes into a human-readable duration string."""
    if minutes < 0:
        minutes = 0
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def format_time(dt: datetime) -> str:
    """Format a datetime as a human-readable time string."""
    return dt.strftime("%-I:%M %p") if hasattr(dt, 'strftime') else str(dt)


def send_slack_notification(message: str) -> bool:
    """Send a notification message to Slack via webhook."""
    if not SLACK_WEBHOOK_URL:
        print(f"No webhook URL - would have sent: {message}")
        return False

    try:
        response = requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": message},
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Slack notification failed: {e}")
        return False


def verify_slack_signature(request_data: bytes, timestamp: str, signature: str) -> bool:
    """Verify that the request actually came from Slack."""
    if not SLACK_SIGNING_SECRET:
        print("Warning: SLACK_SIGNING_SECRET not set - skipping verification")
        return True

    # If no timestamp/signature provided (testing), skip verification
    if not timestamp or not signature:
        print("Warning: No Slack headers - skipping verification (test mode)")
        return True

    try:
        if abs(time.time() - float(timestamp)) > 60 * 5:
            return False
    except ValueError:
        return True

    sig_basestring = f"v0:{timestamp}:{request_data.decode('utf-8')}"
    my_signature = 'v0=' + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(my_signature, signature)


def require_api_secret(f):
    """Decorator to require API secret for laptop endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if auth_header != f'Bearer {API_SECRET}':
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


# =============================================================================
# SLACK COMMAND ENDPOINTS
# =============================================================================

@app.route('/slack/clockin', methods=['POST'])
def handle_clockin():
    """Handle /clockin slash command."""
    if not verify_slack_signature(
        request.get_data(),
        request.headers.get('X-Slack-Request-Timestamp', ''),
        request.headers.get('X-Slack-Signature', '')
    ):
        return jsonify({'error': 'Invalid signature'}), 403

    user_id = request.form.get('user_id')
    user_name = request.form.get('user_name')
    text = request.form.get('text', '').strip()

    mac_address = f"REMOTE-{user_id}"
    employee_name = get_remote_employee(user_id)

    # Register if providing name or use Slack username
    if not employee_name:
        name_to_use = text or user_name
        register_remote_employee(user_id, name_to_use)
        employee_name = name_to_use

    # Check if already clocked in
    last_event = get_last_event(mac_address)
    if last_event and last_event[0] == 'clock_in':
        clock_in_time = last_event[1]
        return jsonify({
            'response_type': 'ephemeral',
            'text': f"You're already clocked in since {format_time(clock_in_time)}.\nUse `/clockout` when you're done."
        })

    # Clock in
    now = datetime.now()
    record_clock_event(
        mac_address=mac_address,
        employee_name=employee_name,
        event_type='clock_in',
        timestamp=now,
        source='slack'
    )

    message = f"🟢 {employee_name} clocked in at {format_time(now)} (remote)"
    send_slack_notification(message)

    return jsonify({
        'response_type': 'ephemeral',
        'text': f"Clocked in at {format_time(now)}. Have a productive day!"
    })


@app.route('/slack/clockout', methods=['POST'])
def handle_clockout():
    """Handle /clockout slash command."""
    if not verify_slack_signature(
        request.get_data(),
        request.headers.get('X-Slack-Request-Timestamp', ''),
        request.headers.get('X-Slack-Signature', '')
    ):
        return jsonify({'error': 'Invalid signature'}), 403

    user_id = request.form.get('user_id')
    mac_address = f"REMOTE-{user_id}"
    employee_name = get_remote_employee(user_id)

    if not employee_name:
        return jsonify({
            'response_type': 'ephemeral',
            'text': "You're not registered. Use `/clockin YourName` to register first."
        })

    # Check if clocked in
    last_event = get_last_event(mac_address)
    if not last_event or last_event[0] != 'clock_in':
        return jsonify({
            'response_type': 'ephemeral',
            'text': "You're not clocked in. Use `/clockin` first."
        })

    clock_in_time = last_event[1]
    now = datetime.now()
    work_duration = now - clock_in_time
    work_minutes = int(work_duration.total_seconds() / 60)

    record_clock_event(
        mac_address=mac_address,
        employee_name=employee_name,
        event_type='clock_out',
        timestamp=now,
        work_duration_minutes=work_minutes,
        source='slack'
    )

    message = f"🔴 {employee_name} clocked out at {format_time(now)} (worked {format_duration(work_minutes)}) (remote)"
    send_slack_notification(message)

    return jsonify({
        'response_type': 'ephemeral',
        'text': f"Clocked out at {format_time(now)}.\nSession: {format_duration(work_minutes)}"
    })


@app.route('/slack/hours', methods=['POST'])
def handle_hours():
    """Handle /hours slash command."""
    if not verify_slack_signature(
        request.get_data(),
        request.headers.get('X-Slack-Request-Timestamp', ''),
        request.headers.get('X-Slack-Signature', '')
    ):
        return jsonify({'error': 'Invalid signature'}), 403

    user_id = request.form.get('user_id')
    mac_address = f"REMOTE-{user_id}"
    employee_name = get_remote_employee(user_id)

    if not employee_name:
        return jsonify({
            'response_type': 'ephemeral',
            'text': "You're not registered. Use `/clockin YourName` to register first."
        })

    # Get today's hours
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Get this week's hours (Mon-Sun)
    today = datetime.now().date()
    days_since_monday = today.weekday()
    week_start = datetime.combine(today - timedelta(days=days_since_monday), datetime.min.time())
    week_end = week_start + timedelta(days=7)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Today's completed hours
            cursor.execute('''
                SELECT COALESCE(SUM(work_duration_minutes), 0)
                FROM clock_events
                WHERE mac_address = %s AND event_type = 'clock_out'
                AND timestamp BETWEEN %s AND %s
            ''', (mac_address, today_start, today_end))
            today_minutes = cursor.fetchone()[0]

            # Week's completed hours
            cursor.execute('''
                SELECT COALESCE(SUM(work_duration_minutes), 0)
                FROM clock_events
                WHERE mac_address = %s AND event_type = 'clock_out'
                AND timestamp BETWEEN %s AND %s
            ''', (mac_address, week_start, week_end))
            week_minutes = cursor.fetchone()[0]

    # Check if currently clocked in
    last_event = get_last_event(mac_address)
    is_clocked_in = last_event and last_event[0] == 'clock_in'

    if is_clocked_in:
        current_session = int((datetime.now() - last_event[1]).total_seconds() / 60)
        today_minutes += current_session
        week_minutes += current_session

    status = "Currently clocked in" if is_clocked_in else "Not clocked in"

    return jsonify({
        'response_type': 'ephemeral',
        'text': f"*{employee_name}*\nStatus: {status}\nToday: {format_duration(today_minutes)}\nThis week: {format_duration(week_minutes)}"
    })


# =============================================================================
# API ENDPOINTS (for laptop's WiFi tracker)
# =============================================================================

@app.route('/api/clock-event', methods=['POST'])
@require_api_secret
def api_clock_event():
    """
    Receive clock events from the laptop's WiFi tracker.

    Expected JSON:
    {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "employee_name": "Tia",
        "event_type": "clock_in" or "clock_out",
        "timestamp": "2024-01-15T09:03:00",
        "work_duration_minutes": 480  (optional, for clock_out)
    }
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No JSON data'}), 400

    required_fields = ['mac_address', 'employee_name', 'event_type', 'timestamp']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing field: {field}'}), 400

    try:
        timestamp = datetime.fromisoformat(data['timestamp'])
    except ValueError:
        return jsonify({'error': 'Invalid timestamp format'}), 400

    record_clock_event(
        mac_address=data['mac_address'],
        employee_name=data['employee_name'],
        event_type=data['event_type'],
        timestamp=timestamp,
        work_duration_minutes=data.get('work_duration_minutes'),
        source='wifi'
    )

    return jsonify({'status': 'ok'})


@app.route('/api/timesheet', methods=['GET'])
@require_api_secret
def api_timesheet():
    """
    Get timesheet data for a date range.

    Query params:
    - start: Start date (YYYY-MM-DD)
    - end: End date (YYYY-MM-DD)
    """
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    if not start_str or not end_str:
        return jsonify({'error': 'Missing start or end date'}), 400

    try:
        start_date = datetime.strptime(start_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('''
                SELECT employee_name, event_type, timestamp, work_duration_minutes, source
                FROM clock_events
                WHERE timestamp BETWEEN %s AND %s
                ORDER BY timestamp
            ''', (start_date, end_date))
            events = cursor.fetchall()

    # Convert timestamps to strings
    for event in events:
        event['timestamp'] = event['timestamp'].isoformat()

    return jsonify({'events': events})


@app.route('/api/summary', methods=['GET'])
@require_api_secret
def api_summary():
    """
    Get hours summary by employee for a date range.

    Query params:
    - start: Start date (YYYY-MM-DD)
    - end: End date (YYYY-MM-DD)
    """
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    if not start_str or not end_str:
        return jsonify({'error': 'Missing start or end date'}), 400

    try:
        start_date = datetime.strptime(start_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute('''
                SELECT
                    employee_name,
                    SUM(work_duration_minutes) as total_minutes,
                    COUNT(*) as sessions
                FROM clock_events
                WHERE event_type = 'clock_out'
                AND timestamp BETWEEN %s AND %s
                GROUP BY employee_name
                ORDER BY employee_name
            ''', (start_date, end_date))
            summary = cursor.fetchall()

    return jsonify({'summary': summary})


# =============================================================================
# EMAIL REPORT FUNCTIONS
# =============================================================================

def get_weekly_summary(end_date: Optional[datetime] = None, weeks: int = 1) -> Tuple[datetime, datetime, Dict]:
    """Generate a summary of employee hours for the specified number of weeks."""
    if end_date is None:
        today = datetime.now().date()
        days_since_sunday = (today.weekday() + 1) % 7
        if days_since_sunday == 0:
            days_since_sunday = 7
        end_date = datetime.combine(
            today - timedelta(days=days_since_sunday),
            datetime.max.time()
        )

    start_date = datetime.combine(
        end_date.date() - timedelta(days=(7 * weeks) - 1),
        datetime.min.time()
    )

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT employee_name, event_type, timestamp, work_duration_minutes
                FROM clock_events
                WHERE timestamp BETWEEN %s AND %s
                ORDER BY employee_name, timestamp
            ''', (start_date, end_date))
            events = cursor.fetchall()

    employee_data: Dict[str, Dict] = {}

    for name, event_type, timestamp, duration in events:
        if name not in employee_data:
            employee_data[name] = {
                'total_minutes': 0,
                'days_worked': set(),
                'sessions': []
            }

        if event_type == 'clock_out' and duration:
            employee_data[name]['total_minutes'] += duration
            dt = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(str(timestamp))
            employee_data[name]['days_worked'].add(dt.date())
            employee_data[name]['sessions'].append({
                'date': dt.date(),
                'duration_minutes': duration
            })

    for name in employee_data:
        employee_data[name]['days_worked'] = len(employee_data[name]['days_worked'])

    return start_date, end_date, employee_data


def generate_report_email(start_date: datetime, end_date: datetime, employee_data: Dict, weeks: int = 1) -> Tuple[str, str]:
    """Generate plain text and HTML versions of the report email."""
    report_type = "BIWEEKLY" if weeks == 2 else "WEEKLY"
    report_type_title = "Biweekly" if weeks == 2 else "Weekly"
    date_range = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
    grand_total_minutes = sum(data['total_minutes'] for data in employee_data.values())
    grand_total_hours = grand_total_minutes / 60

    plain_lines = [
        f"{report_type} TIME REPORT: {date_range}",
        "=" * 50,
        "",
        "HOURS BY EMPLOYEE:",
        "-" * 30,
    ]

    for name in sorted(employee_data.keys()):
        data = employee_data[name]
        hours = data['total_minutes'] / 60
        days = data['days_worked']
        plain_lines.append(f"  {name}: {hours:.1f} hours ({days} days)")

    plain_lines.extend([
        "",
        "-" * 30,
        f"TOTAL: {grand_total_hours:.1f} hours",
        "",
        "---",
        "Time Tracker"
    ])

    plain_text = "\n".join(plain_lines)

    html_rows = ""
    for name in sorted(employee_data.keys()):
        data = employee_data[name]
        hours = data['total_minutes'] / 60
        days = data['days_worked']
        html_rows += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #eee;">{name}</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: right;">{hours:.1f} hrs</td>
            <td style="padding: 12px; border-bottom: 1px solid #eee; text-align: center;">{days}</td>
        </tr>"""

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #2d5016 0%, #4a7c23 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0;">
            <h1 style="margin: 0; font-size: 24px;">{report_type_title} Time Report</h1>
            <p style="margin: 10px 0 0 0; opacity: 0.9;">{date_range}</p>
        </div>

        <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
            <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <thead>
                    <tr style="background: #f5f5f5;">
                        <th style="padding: 12px; text-align: left; font-weight: 600;">Employee</th>
                        <th style="padding: 12px; text-align: right; font-weight: 600;">Hours</th>
                        <th style="padding: 12px; text-align: center; font-weight: 600;">Days</th>
                    </tr>
                </thead>
                <tbody>
                    {html_rows}
                    <tr style="background: #f0f7e6; font-weight: 600;">
                        <td style="padding: 12px;">Total</td>
                        <td style="padding: 12px; text-align: right;">{grand_total_hours:.1f} hrs</td>
                        <td style="padding: 12px; text-align: center;">-</td>
                    </tr>
                </tbody>
            </table>

            <p style="color: #666; font-size: 12px; margin-top: 30px; text-align: center;">
                Time Tracker<br>
                Automated {report_type_title.lower()} report
            </p>
        </div>
    </body>
    </html>
    """

    return plain_text, html_content


def generate_csv(employee_data: Dict, weeks: int = 1) -> str:
    """Generate CSV content with daily breakdown per employee."""
    lines = ["Employee,Date,Total Min,Total Hours"]

    for name in sorted(employee_data.keys()):
        data = employee_data[name]
        daily_minutes: Dict[str, int] = {}
        for session in data.get('sessions', []):
            date_str = session['date'].strftime('%Y-%m-%d')
            daily_minutes[date_str] = daily_minutes.get(date_str, 0) + session['duration_minutes']

        for date_str in sorted(daily_minutes.keys()):
            minutes = daily_minutes[date_str]
            hours = round(minutes / 60, 2)
            lines.append(f"{name},{date_str},{minutes},{hours}")

        total_minutes = data['total_minutes']
        total_hours = round(total_minutes / 60, 2)
        period_label = f"TOTAL (last {weeks * 7} days)"
        lines.append(f"{name},{period_label},{total_minutes},{total_hours}")

    return "\n".join(lines)


def send_email_report(to_email: str, subject: str, plain_text: str, html_content: str, csv_attachment: Optional[Tuple[str, str]] = None) -> bool:
    """Send an email using SMTP."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print("Email not configured - SMTP_USER and SMTP_PASSWORD required")
        return False

    try:
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = to_email

        body_part = MIMEMultipart('alternative')
        body_part.attach(MIMEText(plain_text, 'plain'))
        body_part.attach(MIMEText(html_content, 'html'))
        msg.attach(body_part)

        if csv_attachment:
            filename, csv_content = csv_attachment
            attachment = MIMEBase('text', 'csv')
            attachment.set_payload(csv_content.encode('utf-8'))
            encoders.encode_base64(attachment)
            attachment.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg.attach(attachment)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"Email sent successfully to {to_email}")
        return True

    except smtplib.SMTPAuthenticationError:
        print(f"SMTP authentication failed for {SMTP_USER}")
        return False
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def send_weekly_report(to_email: str = None, weeks: int = 1) -> bool:
    """Generate and send the time report email."""
    if not to_email:
        to_email = REPORT_EMAIL_TO
    if not to_email:
        print("No recipient email configured")
        return False

    report_type = "Biweekly" if weeks == 2 else "Weekly"
    print(f"Generating {report_type.lower()} report for {to_email}...")

    start_date, end_date, employee_data = get_weekly_summary(weeks=weeks)

    if not employee_data:
        print(f"No time data found for the past {weeks} week(s)")

    plain_text, html_content = generate_report_email(start_date, end_date, employee_data, weeks=weeks)

    csv_content = generate_csv(employee_data, weeks=weeks)
    date_range_file = f"{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}"
    csv_filename = f"timesheet_{date_range_file}.csv"
    csv_attachment = (csv_filename, csv_content)

    date_range = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}"
    subject = f"{report_type} Time Report: {date_range}"

    return send_email_report(to_email, subject, plain_text, html_content, csv_attachment=csv_attachment)


@app.route('/api/send-report', methods=['POST'])
@require_api_secret
def api_send_report():
    """
    Trigger sending an email report.

    Query params or JSON body:
    - weeks: 1 for weekly, 2 for biweekly (default: 1)
    - to: email address (optional, uses REPORT_EMAIL_TO if not provided)
    """
    data = request.get_json() or {}
    weeks = data.get('weeks', request.args.get('weeks', 1, type=int))
    to_email = data.get('to', request.args.get('to', REPORT_EMAIL_TO))

    if not to_email:
        return jsonify({'error': 'No recipient email provided'}), 400

    success = send_weekly_report(to_email=to_email, weeks=weeks)

    if success:
        return jsonify({'status': 'ok', 'message': f'Report sent to {to_email}'})
    else:
        return jsonify({'error': 'Failed to send report'}), 500


@app.route('/api/report-preview', methods=['GET'])
@require_api_secret
def api_report_preview():
    """
    Preview report data without sending email.

    Query params:
    - weeks: 1 for weekly, 2 for biweekly (default: 1)
    """
    weeks = request.args.get('weeks', 1, type=int)

    start_date, end_date, employee_data = get_weekly_summary(weeks=weeks)

    summary = []
    for name in sorted(employee_data.keys()):
        data = employee_data[name]
        summary.append({
            'employee': name,
            'total_hours': round(data['total_minutes'] / 60, 2),
            'days_worked': data['days_worked']
        })

    return jsonify({
        'period': {
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d'),
            'weeks': weeks
        },
        'summary': summary,
        'total_hours': round(sum(data['total_minutes'] for data in employee_data.values()) / 60, 2)
    })


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1')
        db_status = 'connected'
    except Exception as e:
        db_status = f'error: {e}'

    return jsonify({
        'status': 'ok',
        'database': db_status,
        'service': 'time-tracker-api'
    })


@app.route('/', methods=['GET'])
def index():
    """Root endpoint."""
    return jsonify({
        'service': 'Time Tracker API',
        'endpoints': {
            '/slack/clockin': 'POST - Slack clock in command',
            '/slack/clockout': 'POST - Slack clock out command',
            '/slack/hours': 'POST - Slack hours command',
            '/api/clock-event': 'POST - Push clock event from laptop',
            '/api/timesheet': 'GET - Get timesheet data',
            '/api/summary': 'GET - Get hours summary',
            '/api/send-report': 'POST - Send email report',
            '/api/report-preview': 'GET - Preview report data',
            '/health': 'GET - Health check'
        }
    })


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        exit(1)

    init_database()

    port = int(os.environ.get('PORT', 5000))
    print(f"Starting API server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
