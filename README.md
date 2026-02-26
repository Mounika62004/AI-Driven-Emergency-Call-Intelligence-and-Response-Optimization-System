🚨 AI Emergency Call Intelligence And Response Optimization System
An AI-powered platform that transcribes emergency audio, detects caller emotion, extracts incident details, maps locations, and sends real-time alerts to response centers.

✅ Features

🎙️ Live voice recording + audio file upload (MP3, WAV, M4A, OGG, FLAC, WEBM)
🤖 Auto transcription using OpenAI Whisper
😰 Emotion detection — PANIC / DISTRESS / CALM
🏷️ Named Entity Recognition — emergency type + location
🗺️ Interactive map with nearest hospitals, police stations, fire stations
🔔 Real-time Web Push notifications to registered help centers
🗄️ PostgreSQL database for persistent storage


🛠️ Tech Stack
Python, Flask, OpenAI Whisper, SpaCy, Librosa, Google Maps API, PostgreSQL, Leaflet.js, VAPID Web Push

⚙️ Setup
1. Install Dependencies
bashpip install -r requirements.txt
pip install -r requirements_response.txt
pip install python-dotenv
python -m spacy download en_core_web_sm
2. Create a .env File in the Project Root
PG_DB=emergency_response
PG_USER=postgres
PG_PASSWORD=yourpassword
PG_HOST=localhost
PG_PORT=5432
3. Add to the Top of Both app.py and response_app.py
pythonfrom dotenv import load_dotenv
load_dotenv()
4. Create the PostgreSQL Database
sqlCREATE DATABASE emergency_response;

Tables are created automatically on first run.


▶️ Running
Open two terminals in your project folder:
Terminal 1 — Emergency Call App
bashpython app.py
Terminal 2 — Response Center App
bashpython response_app.py

🌐 Access
AppURLEmergency Call Apphttp://localhost:5006Response Centerhttp://localhost:5020
