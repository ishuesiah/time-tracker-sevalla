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
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, List
from flask import Flask, request, jsonify
from functools import wraps
import requests
import random

app = Flask(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DATABASE_URL = os.environ.get('DATABASE_URL')
SLACK_SIGNING_SECRET = os.environ.get('SLACK_SIGNING_SECRET', '')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')
API_SECRET = os.environ.get('API_SECRET', '')  # For laptop authentication

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
        print("Warning: SLACK_SIGNING_SECRET not set")
        return True

    if abs(time.time() - float(timestamp)) > 60 * 5:
        return False

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
