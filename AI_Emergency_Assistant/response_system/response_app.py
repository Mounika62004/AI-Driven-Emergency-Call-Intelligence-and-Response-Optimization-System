"""
Emergency Response Center — Flask App on port 5020
Receives alerts from the Emergency App (port 5006) and distributes
Web Push notifications to registered help centers.
Storage: PostgreSQL (replaces JSON flat files)
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
import json
import os
import base64
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

response_app = Flask(
    __name__,
    template_folder='response_templates',
    static_folder='response_static',
    static_url_path='/response_static'
)

# ─── File paths ───────────────────────────────────────────────────────────────
BASE        = os.path.dirname(os.path.abspath(__file__))
VAPID_PEM   = os.path.join(BASE, 'vapid_private.pem')
VAPID_PUB   = os.path.join(BASE, 'vapid_public_key.txt')
VAPID_EMAIL = 'mailto:admin@emergency.local'

# ─── PostgreSQL connection config ─────────────────────────────────────────────
# Edit these values to match your PostgreSQL setup, or set environment variables.
DB_CONFIG = {
    'dbname':   os.environ.get('PG_DB',       'emergency_response'),
    'user':     os.environ.get('PG_USER',     'postgres'),
    'password': os.environ.get('PG_PASSWORD', 'postgres'),
    'host':     os.environ.get('PG_HOST',     'localhost'),
    'port':     os.environ.get('PG_PORT',     '5432'),
}


def get_db():
    """Open and return a new database connection."""
    return psycopg2.connect(**DB_CONFIG)


def init_db():
    """Create all required tables if they don't already exist."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS help_centers (
                    id            TEXT PRIMARY KEY,
                    name          TEXT NOT NULL UNIQUE,
                    location      TEXT NOT NULL,
                    state         TEXT NOT NULL,
                    type          TEXT NOT NULL DEFAULT 'General',
                    registered_at TEXT NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS push_subscriptions (
                    id          SERIAL PRIMARY KEY,
                    center_name TEXT NOT NULL,
                    endpoint    TEXT NOT NULL UNIQUE,
                    subscription JSONB NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS alerts_log (
                    id              SERIAL PRIMARY KEY,
                    title           TEXT,
                    body            TEXT,
                    priority        INTEGER,
                    priority_text   TEXT,
                    emergency_type  TEXT,
                    location        TEXT,
                    emotion         TEXT,
                    transcript      TEXT,
                    filename        TEXT,
                    matched_centers JSONB,
                    play_sound      BOOLEAN DEFAULT TRUE,
                    timestamp       TEXT NOT NULL
                );
            """)
        conn.commit()
    print('✅ PostgreSQL tables verified / created.')


# ─── VAPID key generation ─────────────────────────────────────────────────────
def get_or_generate_vapid():
    """Generate VAPID keys once; reuse them on subsequent restarts."""
    if os.path.exists(VAPID_PEM) and os.path.exists(VAPID_PUB):
        with open(VAPID_PUB) as f:
            return f.read().strip()

    try:
        from py_vapid import Vapid
        from cryptography.hazmat.primitives import serialization

        vapid = Vapid()
        vapid.generate_keys()
        vapid.save_key(VAPID_PEM)

        pub_bytes = vapid.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b'=').decode()

        with open(VAPID_PUB, 'w') as f:
            f.write(pub_b64)

        print(f'✅ VAPID public key generated: {pub_b64[:40]}...')
        return pub_b64

    except ImportError:
        print('⚠️  py-vapid / cryptography not installed. Push notifications disabled.')
        print('   Run: pip install pywebpush py-vapid --break-system-packages')
        return 'NOT_CONFIGURED'
    except Exception as e:
        print(f'⚠️  VAPID generation failed: {e}')
        return 'NOT_CONFIGURED'


VAPID_PUBLIC_KEY = get_or_generate_vapid()

# ─── Track server start time — only show alerts from this session ─────────────
SERVER_START_TIME = datetime.now().isoformat()
print(f'🕐 Server session started at: {SERVER_START_TIME}')

# ─── Initialise DB tables on startup ─────────────────────────────────────────
init_db()


# ─── Location matching ────────────────────────────────────────────────────────
def location_matches(extracted_loc: str, center: dict) -> bool:
    """
    Return True if the extracted location overlaps with a help center's
    registered location or state (case-insensitive word-level matching).
    """
    if not extracted_loc:
        return False

    loc_lower    = extracted_loc.lower().strip()
    center_loc   = center.get('location', '').lower().strip()
    center_state = center.get('state', '').lower().strip()
    combined     = f'{center_loc} {center_state}'

    for word in loc_lower.split():
        if len(word) > 2 and word in combined:
            return True
    for word in combined.split():
        if len(word) > 2 and word in loc_lower:
            return True

    return False


# ─── Push notification sender ─────────────────────────────────────────────────
def send_push_to_center(center_name: str, payload: dict) -> int:
    """
    Send a Web Push notification to every subscribed browser for center_name.
    Returns the number of successful pushes.
    Prunes dead subscriptions (410 / 404) from the database automatically.
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print('pywebpush not installed – skipping push')
        return 0

    if not os.path.exists(VAPID_PEM):
        print('VAPID private key missing – skipping push')
        return 0

    # Fetch subscriptions for this center
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, endpoint, subscription FROM push_subscriptions WHERE center_name = %s",
                (center_name,)
            )
            rows = cur.fetchall()

    if not rows:
        print(f'No push subscriptions for "{center_name}"')
        return 0

    sent         = 0
    dead_ids     = []
    payload_str  = json.dumps(payload)

    for row in rows:
        try:
            webpush(
                subscription_info=dict(row['subscription']),
                data=payload_str,
                vapid_private_key=VAPID_PEM,
                vapid_claims={'sub': VAPID_EMAIL}
            )
            sent += 1
        except Exception as e:
            err = str(e)
            print(f'Push failed: {err}')
            if '410' in err or '404' in err:
                dead_ids.append(row['id'])

    # Prune dead subscriptions
    if dead_ids:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM push_subscriptions WHERE id = ANY(%s)",
                    (dead_ids,)
                )
            conn.commit()

    return sent


# ─── Service Worker ───────────────────────────────────────────────────────────
@response_app.route('/sw.js')
def service_worker():
    return send_from_directory('response_static', 'sw.js',
                               mimetype='application/javascript')


# ─── Routes ───────────────────────────────────────────────────────────────────
@response_app.route('/')
def index():
    return render_template('index.html', vapid_public_key=VAPID_PUBLIC_KEY)


@response_app.route('/centers', methods=['GET'])
def get_centers():
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM help_centers ORDER BY registered_at")
            centers = [dict(r) for r in cur.fetchall()]
    return jsonify(centers)


@response_app.route('/register', methods=['POST'])
def register_center():
    data     = request.json or {}
    name     = data.get('name', '').strip()
    location = data.get('location', '').strip()
    state    = data.get('state', '').strip()
    ctype    = data.get('type', 'General').strip()

    if not name or not location or not state:
        return jsonify({'error': 'Name, location, and state are required'}), 400

    center_id = f'center_{int(datetime.now().timestamp())}'
    now       = datetime.now().isoformat()

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO help_centers (id, name, location, state, type, registered_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (center_id, name, location, state, ctype, now))
            conn.commit()
    except psycopg2.errors.UniqueViolation:
        return jsonify({'error': 'A center with this name already exists'}), 409

    new_center = {
        'id': center_id, 'name': name, 'location': location,
        'state': state, 'type': ctype, 'registered_at': now
    }
    return jsonify({'success': True, 'center': new_center})


@response_app.route('/subscribe', methods=['POST'])
def subscribe():
    """Save a browser's Web Push subscription for a given help center."""
    data         = request.json or {}
    center_name  = data.get('center_name')
    subscription = data.get('subscription')

    if not center_name or not subscription:
        return jsonify({'error': 'center_name and subscription required'}), 400

    endpoint = subscription.get('endpoint')

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO push_subscriptions (center_name, endpoint, subscription)
                VALUES (%s, %s, %s)
                ON CONFLICT (endpoint) DO NOTHING
            """, (center_name, endpoint, json.dumps(subscription)))
        conn.commit()

    return jsonify({'success': True})


@response_app.route('/receive_alert', methods=['POST'])
def receive_alert():
    """
    Called by the Emergency App (port 5006) after every audio analysis.
    Matches location → registered centers → fires Web Push notifications.
    """
    data = request.json or {}

    transcript         = data.get('transcript', '')
    emotion            = data.get('emotion', 'CALM')
    entities           = data.get('entities', {})
    priority           = data.get('priority', 4)
    filename           = data.get('filename', 'Unknown')
    extracted_location = entities.get('location', '')
    emergency_type     = entities.get('emergency_type', 'Unknown')

    priority_labels = {1: 'CRITICAL', 2: 'HIGH', 3: 'MEDIUM', 4: 'LOW'}
    priority_text   = priority_labels.get(priority, 'MEDIUM')

    report = {
        'title':         f'🚨 {priority_text} Emergency — {emergency_type.title() if emergency_type else "Unknown"}',
        'body':          (
            f"📍 Location: {extracted_location or 'Not specified'}\n"
            f"🔥 Type: {(emergency_type or 'Unknown').title()}\n"
            f"😤 Emotion: {emotion}\n"
            f"📝 \"{transcript[:100]}{'...' if len(transcript) > 100 else ''}\""
        ),
        'priority':       priority,
        'priority_text':  priority_text,
        'emergency_type': emergency_type,
        'location':       extracted_location,
        'emotion':        emotion,
        'transcript':     transcript,
        'filename':       filename,
        'timestamp':      datetime.now().isoformat(),
        'play_sound':     True
    }

    # Fetch all centers and find matches
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM help_centers")
            centers = [dict(r) for r in cur.fetchall()]

    matched  = [c for c in centers if location_matches(extracted_location, c)]
    targets  = matched

    now_iso  = datetime.now().isoformat()

    if not targets:
        print(f'⚠️  No matching center found for location: "{extracted_location}" — alert not sent')
        # Still log the alert with empty matched_centers
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO alerts_log
                        (title, body, priority, priority_text, emergency_type,
                         location, emotion, transcript, filename, matched_centers, play_sound, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    report['title'], report['body'], priority, priority_text,
                    emergency_type, extracted_location, emotion, transcript,
                    filename, json.dumps([]), True, now_iso
                ))
            conn.commit()

        return jsonify({
            'success':            True,
            'matched_centers':    [],
            'notifications_sent': 0,
            'alert_sent':         False,
            'location_matched':   False,
            'message':            f'No registered center found for location: "{extracted_location or "unknown"}"'
        })

    total_sent       = 0
    notified_centers = []
    for center in targets:
        sent = send_push_to_center(center['name'], report)
        total_sent += sent
        notified_centers.append(center['name'])

    # Persist alert log
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO alerts_log
                    (title, body, priority, priority_text, emergency_type,
                     location, emotion, transcript, filename, matched_centers, play_sound, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                report['title'], report['body'], priority, priority_text,
                emergency_type, extracted_location, emotion, transcript,
                filename, json.dumps(notified_centers), True, now_iso
            ))
        conn.commit()

    print(f'📢 Alert dispatched to: {notified_centers}, push sent: {total_sent}')
    return jsonify({
        'success':            True,
        'matched_centers':    notified_centers,
        'notifications_sent': total_sent,
        'alert_sent':         len(notified_centers) > 0,
        'location_matched':   True,
        'message':            f'Alert sent to {len(notified_centers)} center(s): {", ".join(notified_centers)}'
    })


@response_app.route('/alerts', methods=['GET'])
def get_alerts():
    """Returns alerts from this server session only, optionally filtered by center."""
    center = request.args.get('center', '')

    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if center:
                cur.execute("""
                    SELECT * FROM alerts_log
                    WHERE timestamp >= %s
                      AND matched_centers @> %s::jsonb
                    ORDER BY timestamp DESC
                    LIMIT 20
                """, (SERVER_START_TIME, json.dumps([center])))
            else:
                cur.execute("""
                    SELECT * FROM alerts_log
                    WHERE timestamp >= %s
                    ORDER BY timestamp DESC
                    LIMIT 20
                """, (SERVER_START_TIME,))
            alerts = [dict(r) for r in cur.fetchall()]

    return jsonify(alerts)


# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print('🚑 Emergency Response Center starting on port 5020')
    print(f'🔑 VAPID key: {VAPID_PUBLIC_KEY[:40]}...' if len(VAPID_PUBLIC_KEY) > 40 else f'🔑 VAPID key: {VAPID_PUBLIC_KEY}')
    response_app.run(debug=True, port=5020, host='0.0.0.0')
