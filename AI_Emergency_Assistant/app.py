from flask import Flask, render_template, request, jsonify
import os
from werkzeug.utils import secure_filename
import json
from asr import transcribe_audio
from emotion import analyze_emotion
from ner import extract_entities
from geomapping import get_location_data
from datetime import datetime
import hashlib
import requests as http_requests   # renamed to avoid clash with flask.request

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

# ===== FOLDER SETUP =====
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER   = os.path.join(BASE_DIR, 'uploads')
RESULTS_FOLDER  = os.path.join(BASE_DIR, 'results')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['RESULTS_FOLDER'] = RESULTS_FOLDER

ALLOWED_EXTENSIONS = {'wav', 'mp3', 'ogg', 'flac', 'm4a', 'webm'}
RESPONSE_APP_URL   = 'http://localhost:5020/receive_alert'


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_hash(file_stream):
    md5 = hashlib.md5()
    for chunk in iter(lambda: file_stream.read(8192), b''):
        md5.update(chunk)
    file_stream.seek(0)
    return md5.hexdigest()


def find_existing_result(file_hash):
    for fname in os.listdir(RESULTS_FOLDER):
        if not fname.endswith('.json'):
            continue
        path = os.path.join(RESULTS_FOLDER, fname)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('file_hash') == file_hash:
                print(f"♻️  Duplicate — returning cached result from {fname}")
                return data
        except Exception:
            continue
    return None


def save_result_to_file(result, prefix='result'):
    timestamp       = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    result_filename = f"{prefix}_{timestamp}.json"
    result_path     = os.path.join(app.config['RESULTS_FOLDER'], result_filename)
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Result saved to: {result_path}")
    return result_filename


def calculate_priority(entities, emotion):
    priority_keywords = {
        'critical': ['fire', 'shooting', 'explosion', 'heart attack', 'stroke',
                     'bleeding', 'unconscious', 'dying', 'weapon', 'gun'],
        'high':     ['accident', 'injury', 'assault', 'robbery', 'burglary',
                     'chest pain', 'difficulty breathing', 'severe pain'],
        'medium':   ['theft', 'suspicious', 'noise complaint', 'minor injury', 'disturbance'],
        'low':      ['lost', 'found', 'information', 'general inquiry']
    }
    text_lower = entities.get('full_text', '').lower()

    for kw in priority_keywords['critical']:
        if kw in text_lower:
            return 1
    for kw in priority_keywords['high']:
        if kw in text_lower:
            return 2
    if emotion in ['angry', 'fear', 'sad', 'PANIC']:
        return 2
    for kw in priority_keywords['medium']:
        if kw in text_lower:
            return 3
    return 4


def notify_response_app(result: dict) -> dict:
    """
    POST the analysis result to the Response Center (port 5020).
    Returns a dict with alert_sent, matched_centers, and notifications_sent.
    Silently ignores any connection error so the emergency app keeps working.
    """
    try:
        resp = http_requests.post(
            RESPONSE_APP_URL,
            json=result,
            timeout=5
        )
        data = resp.json()
        print(f"📢 Response app notified — alert_sent={data.get('alert_sent')}, "
              f"centers={data.get('matched_centers')}")
        return data
    except Exception as e:
        print(f"⚠️  Could not reach response app: {e}")
        return {'alert_sent': False, 'matched_centers': [], 'notifications_sent': 0}


# ─── Routes ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_files():
    if 'files[]' not in request.files:
        return jsonify({'error': 'No files provided'}), 400

    files   = request.files.getlist('files[]')
    results = []

    for file in files:
        if not (file and allowed_file(file.filename)):
            continue

        file_hash = get_file_hash(file.stream)

        # ── Duplicate file: still notify response app with cached result ──
        cached = find_existing_result(file_hash)
        if cached:
            alert_info = notify_response_app(cached)
            cached['alert_sent']       = alert_info.get('alert_sent', False)
            cached['notified_centers'] = alert_info.get('matched_centers', [])
            results.append(cached)
            continue

        # ── New file: save to uploads/ ────────────────────────────────────
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if os.path.exists(filepath):
            base, ext = os.path.splitext(filename)
            ts        = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename  = f"{base}_{ts}{ext}"
            filepath  = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        file.save(filepath)

        try:
            transcript = transcribe_audio(filepath)
            emotion    = analyze_emotion(filepath)
            entities   = extract_entities(transcript)
            entities['full_text'] = transcript

            priority = calculate_priority(entities, emotion)

            result = {
                'filename':     filename,
                'transcript':   transcript,
                'emotion':      emotion,
                'entities':     entities,
                'priority':     priority,
                'file_hash':    file_hash,
                'processed_at': datetime.now().isoformat()
            }

            # ── Notify Response App ──
            alert_info = notify_response_app(result)
            result['alert_sent']       = alert_info.get('alert_sent', False)
            result['notified_centers'] = alert_info.get('matched_centers', [])

            save_result_to_file(result, prefix=filename.rsplit('.', 1)[0])
            results.append(result)

        except Exception as e:
            print(f"Error processing {filename}: {e}")
            error_result = {
                'filename':     filename,
                'error':        str(e),
                'processed_at': datetime.now().isoformat()
            }
            save_result_to_file(error_result,
                                prefix=f"error_{filename.rsplit('.', 1)[0]}")
            results.append(error_result)

    results.sort(key=lambda x: x.get('priority', 999))
    return jsonify(results)


@app.route('/record', methods=['POST'])
def record_audio():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']
    file_hash  = get_file_hash(audio_file.stream)

    # ── Duplicate recording: still notify response app ──
    cached = find_existing_result(file_hash)
    if cached:
        print("♻️  Duplicate recording — returning cached result")
        alert_info = notify_response_app(cached)
        cached['alert_sent']       = alert_info.get('alert_sent', False)
        cached['notified_centers'] = alert_info.get('matched_centers', [])
        return jsonify(cached)

    timestamp          = datetime.now().strftime('%Y%m%d_%H%M%S')
    recording_filename = f"recording_{timestamp}.webm"
    filepath           = os.path.join(app.config['UPLOAD_FOLDER'], recording_filename)
    audio_file.save(filepath)

    try:
        transcript = transcribe_audio(filepath)
        emotion    = analyze_emotion(filepath)
        entities   = extract_entities(transcript)
        entities['full_text'] = transcript

        priority = calculate_priority(entities, emotion)

        result = {
            'filename':     'Live Recording',
            'transcript':   transcript,
            'emotion':      emotion,
            'entities':     entities,
            'priority':     priority,
            'file_hash':    file_hash,
            'processed_at': datetime.now().isoformat()
        }

        # ── Notify Response App ──
        alert_info = notify_response_app(result)
        result['alert_sent']       = alert_info.get('alert_sent', False)
        result['notified_centers'] = alert_info.get('matched_centers', [])

        save_result_to_file(result, prefix=f"recording_{timestamp}")
        return jsonify(result)

    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': str(e)}), 500


@app.route('/geocode', methods=['POST'])
def geocode():
    data     = request.json
    location = data.get('location', '')
    if not location:
        return jsonify({'error': 'No location provided'}), 400

    try:
        location_data = get_location_data(location)
        return jsonify(location_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print(f"📁 Uploads folder : {UPLOAD_FOLDER}")
    print(f"📁 Results folder : {RESULTS_FOLDER}")
    print(f"🔗 Response App   : {RESPONSE_APP_URL}")
    app.run(debug=True, port=5006, host='0.0.0.0')