from flask import Flask, render_template, request, jsonify
import os
from werkzeug.utils import secure_filename
import json
from asr import transcribe_audio
from emotion import analyze_emotion
from ner import extract_entities
from geomapping import get_location_data
import tempfile
from datetime import datetime

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size

# ===== FOLDER SETUP =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
RESULTS_FOLDER = os.path.join(BASE_DIR, 'results')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['RESULTS_FOLDER'] = RESULTS_FOLDER

ALLOWED_EXTENSIONS = {'wav', 'mp3', 'ogg', 'flac', 'm4a', 'webm'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_result_to_file(result, prefix='result'):
    """Save a result dict as a timestamped JSON file in the results folder."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    result_filename = f"{prefix}_{timestamp}.json"
    result_path = os.path.join(app.config['RESULTS_FOLDER'], result_filename)
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"Result saved to: {result_path}")
    return result_filename


def calculate_priority(entities, emotion):
    """Calculate priority based on emergency type and emotion."""
    priority_keywords = {
        'critical': ['fire', 'shooting', 'explosion', 'heart attack', 'stroke', 'bleeding', 'unconscious', 'dying',
                     'weapon', 'gun'],
        'high': ['accident', 'injury', 'assault', 'robbery', 'burglary', 'chest pain', 'difficulty breathing',
                 'severe pain'],
        'medium': ['theft', 'suspicious', 'noise complaint', 'minor injury', 'disturbance'],
        'low': ['lost', 'found', 'information', 'general inquiry']
    }

    text_lower = entities.get('full_text', '').lower()

    for keyword in priority_keywords['critical']:
        if keyword in text_lower:
            return 1

    for keyword in priority_keywords['high']:
        if keyword in text_lower:
            return 2

    if emotion in ['angry', 'fear', 'sad', 'PANIC']:
        return 2

    for keyword in priority_keywords['medium']:
        if keyword in text_lower:
            return 3

    return 4


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_files():
    if 'files[]' not in request.files:
        return jsonify({'error': 'No files provided'}), 400

    files = request.files.getlist('files[]')
    results = []

    for file in files:
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Save original upload to uploads/ folder
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            try:
                transcript = transcribe_audio(filepath)
                emotion = analyze_emotion(filepath)
                entities = extract_entities(transcript)
                entities['full_text'] = transcript

                priority = calculate_priority(entities, emotion)

                result = {
                    'filename': filename,
                    'transcript': transcript,
                    'emotion': emotion,
                    'entities': entities,
                    'priority': priority,
                    'processed_at': datetime.now().isoformat()
                }

                # Save result JSON to results/ folder
                save_result_to_file(result, prefix=filename.rsplit('.', 1)[0])

                results.append(result)

            except Exception as e:
                print(f"Error processing {filename}: {str(e)}")
                error_result = {
                    'filename': filename,
                    'error': str(e),
                    'processed_at': datetime.now().isoformat()
                }
                save_result_to_file(error_result, prefix=f"error_{filename.rsplit('.', 1)[0]}")
                results.append(error_result)

    # Sort by priority (1 = highest)
    results.sort(key=lambda x: x.get('priority', 999))
    return jsonify(results)


@app.route('/record', methods=['POST'])
def record_audio():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided'}), 400

    audio_file = request.files['audio']

    # Save recording to uploads/ folder with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    recording_filename = f"recording_{timestamp}.webm"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], recording_filename)
    audio_file.save(filepath)

    try:
        transcript = transcribe_audio(filepath)
        emotion = analyze_emotion(filepath)
        entities = extract_entities(transcript)
        entities['full_text'] = transcript

        priority = calculate_priority(entities, emotion)

        result = {
            'filename': 'Live Recording',
            'transcript': transcript,
            'emotion': emotion,
            'entities': entities,
            'priority': priority,
            'processed_at': datetime.now().isoformat()
        }

        # Save result to results/ folder
        save_result_to_file(result, prefix=f"recording_{timestamp}")

        return jsonify(result)

    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': str(e)}), 500


@app.route('/geocode', methods=['POST'])
def geocode():
    data = request.json
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
    app.run(debug=True, port=5006, host='0.0.0.0')