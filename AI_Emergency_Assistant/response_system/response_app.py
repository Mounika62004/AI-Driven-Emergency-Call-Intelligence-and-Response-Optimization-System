"""
Emergency Response Center — Flask App on port 5020
Receives alerts from the Emergency App (port 5006) and distributes
Web Push notifications to registered help centers.
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
import json
import os
import base64
from datetime import datetime

response_app = Flask(
    __name__,
    template_folder='response_templates',
    static_folder='response_static',
    static_url_path='/response_static'
)

# ─── File paths ───────────────────────────────────────────────────────────────
BASE          = os.path.dirname(os.path.abspath(__file__))
CENTERS_FILE  = os.path.join(BASE, 'help_centers.json')
SUBS_FILE     = os.path.join(BASE, 'push_subscriptions.json')
ALERTS_FILE   = os.path.join(BASE, 'alerts_log.json')
VAPID_PEM     = os.path.join(BASE, 'vapid_private.pem')
VAPID_PUB     = os.path.join(BASE, 'vapid_public_key.txt')
VAPID_EMAIL   = 'mailto:admin@emergency.local'


# ─── Helpers ──────────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return default


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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

    # Any meaningful word in extracted location found in center's fields?
    for word in loc_lower.split():
        if len(word) > 2 and word in combined:
            return True

    # Any meaningful word in center's fields found in extracted location?
    for word in combined.split():
        if len(word) > 2 and word in loc_lower:
            return True

    return False


# ─── Push notification sender ─────────────────────────────────────────────────
def send_push_to_center(center_name: str, payload: dict) -> int:
    """
    Send a Web Push notification to every subscribed browser for center_name.
    Returns the number of successful pushes.
    """
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print('pywebpush not installed – skipping push')
        return 0

    if not os.path.exists(VAPID_PEM):
        print('VAPID private key missing – skipping push')
        return 0

    subscriptions = load_json(SUBS_FILE, {})
    center_subs   = subscriptions.get(center_name, [])

    if not center_subs:
        print(f'No push subscriptions for "{center_name}"')
        return 0

    sent        = 0
    valid_subs  = []
    import json as _json
    payload_str = _json.dumps(payload)

    for sub in center_subs:
        try:
            webpush(
                subscription_info=sub,
                data=payload_str,
                vapid_private_key=VAPID_PEM,
                vapid_claims={'sub': VAPID_EMAIL}
            )
            sent += 1
            valid_subs.append(sub)
        except Exception as e:
            err = str(e)
            print(f'Push failed: {err}')
            if '410' not in err and '404' not in err:
                valid_subs.append(sub)

    # Prune dead subscriptions
    subscriptions[center_name] = valid_subs
    save_json(SUBS_FILE, subscriptions)
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
    return jsonify(load_json(CENTERS_FILE, []))


@response_app.route('/register', methods=['POST'])
def register_center():
    data     = request.json or {}
    name     = data.get('name', '').strip()
    location = data.get('location', '').strip()
    state    = data.get('state', '').strip()
    ctype    = data.get('type', 'General').strip()

    if not name or not location or not state:
        return jsonify({'error': 'Name, location, and state are required'}), 400

    centers = load_json(CENTERS_FILE, [])
    for c in centers:
        if c['name'].lower() == name.lower():
            return jsonify({'error': 'A center with this name already exists'}), 409

    new_center = {
        'id':            f'center_{len(centers)+1}_{int(datetime.now().timestamp())}',
        'name':          name,
        'location':      location,
        'state':         state,
        'type':          ctype,
        'registered_at': datetime.now().isoformat()
    }
    centers.append(new_center)
    save_json(CENTERS_FILE, centers)
    return jsonify({'success': True, 'center': new_center})


@response_app.route('/subscribe', methods=['POST'])
def subscribe():
    """Save a browser's Web Push subscription for a given help center."""
    data         = request.json or {}
    center_name  = data.get('center_name')
    subscription = data.get('subscription')

    if not center_name or not subscription:
        return jsonify({'error': 'center_name and subscription required'}), 400

    subscriptions      = load_json(SUBS_FILE, {})
    existing_endpoints = [s.get('endpoint') for s in subscriptions.get(center_name, [])]

    if subscription.get('endpoint') not in existing_endpoints:
        subscriptions.setdefault(center_name, []).append(subscription)
        save_json(SUBS_FILE, subscriptions)

    return jsonify({'success': True})


@response_app.route('/receive_alert', methods=['POST'])
def receive_alert():
    """
    Called by the Emergency App (port 5006) after every audio analysis.
    Matches location → registered centers → fires Web Push notifications.
    Only sends to centers whose location matches the extracted location.
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

    # ── Build short incident report ──────────────────────────────────────────
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

    centers = load_json(CENTERS_FILE, [])
    matched = [c for c in centers if location_matches(extracted_location, c)]

    # ── Only send to matching centers, no fallback broadcast ─────────────────
    targets = matched

    if not targets:
        print(f'⚠️  No matching center found for location: "{extracted_location}" — alert not sent')
        alerts = load_json(ALERTS_FILE, [])
        alerts.insert(0, {**report, 'matched_centers': []})
        save_json(ALERTS_FILE, alerts[:100])
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

    # ── Persist alert log ────────────────────────────────────────────────────
    alerts = load_json(ALERTS_FILE, [])
    alerts.insert(0, {**report, 'matched_centers': notified_centers})
    save_json(ALERTS_FILE, alerts[:100])

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
    alerts = load_json(ALERTS_FILE, [])

    # ── Only show alerts received after this server session started ───────────
    alerts = [a for a in alerts if a.get('timestamp', '') >= SERVER_START_TIME]

    if center:
        alerts = [
            a for a in alerts
            if center in a.get('matched_centers', [])
        ]

    return jsonify(alerts[:20])


# ─── Run ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print('🚑 Emergency Response Center starting on port 5020')
    print(f'🔑 VAPID key: {VAPID_PUBLIC_KEY[:40]}...' if len(VAPID_PUBLIC_KEY) > 40 else f'🔑 VAPID key: {VAPID_PUBLIC_KEY}')
    response_app.run(debug=True, port=5020, host='0.0.0.0')