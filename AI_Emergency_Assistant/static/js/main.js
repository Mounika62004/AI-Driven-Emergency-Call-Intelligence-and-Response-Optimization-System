let selectedFiles = [];
let mediaRecorder;
let audioChunks = [];
let recordingInterval;
let recordingTime = 0;
let mapInstances = {};

// ===== DRAG & DROP =====
const dropZone = document.getElementById('dropZone');

dropZone.addEventListener('click', () => document.getElementById('fileInput').click());

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', async (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('audio/'));
    if (files.length > 0) {
        selectedFiles = files;
        displayFileList();
        await processFiles();
    }
});

// ===== FILE INPUT =====
document.getElementById('browseBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    document.getElementById('fileInput').click();
});

document.getElementById('fileInput').addEventListener('change', async (e) => {
    selectedFiles = Array.from(e.target.files);
    displayFileList();
    if (selectedFiles.length > 0) await processFiles();
});

function displayFileList() {
    const fileList = document.getElementById('fileList');
    fileList.innerHTML = '';
    selectedFiles.forEach((file) => {
        const item = document.createElement('div');
        item.className = 'file-item';
        item.innerHTML = `
            <span>🎵 ${file.name}</span>
            <span>${(file.size / 1024 / 1024).toFixed(2)} MB</span>
        `;
        fileList.appendChild(item);
    });
}

async function processFiles() {
    if (selectedFiles.length === 0) return;

    const statusDiv = document.getElementById('uploadStatus');
    statusDiv.className = 'status-message processing';
    statusDiv.innerHTML = '<div class="loading-spinner"></div><p>Processing audio files… This may take a few moments.</p>';

    const formData = new FormData();
    selectedFiles.forEach(file => formData.append('files[]', file));

    try {
        const response = await fetch('/upload', { method: 'POST', body: formData });
        if (!response.ok) throw new Error('Upload failed');

        const results = await response.json();

        statusDiv.className = 'status-message success';
        statusDiv.textContent = `✅ Successfully processed ${results.length} audio file(s)!`;

        displayResults(results);
        setTimeout(() => {
            document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 300);

    } catch (error) {
        statusDiv.className = 'status-message error';
        statusDiv.textContent = `❌ Error: ${error.message}`;
        console.error('Upload error:', error);
    }
}

// ===== RECORDING =====
document.getElementById('recordBtn').addEventListener('click', toggleRecording);

async function toggleRecording() {
    const recordBtn     = document.getElementById('recordBtn');
    const recordBtnText = document.getElementById('recordBtnText');
    const statusDiv     = document.getElementById('recordingStatus');
    const timerDiv      = document.getElementById('recordingTimer');

    if (!mediaRecorder || mediaRecorder.state === 'inactive') {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks   = [];

            mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                await sendRecording(audioBlob);
                stream.getTracks().forEach(t => t.stop());
            };

            mediaRecorder.start();
            recordBtnText.textContent = '⏹ Stop Recording';
            recordBtn.classList.add('recording');
            statusDiv.textContent     = '🔴 Recording in progress…';
            timerDiv.style.display    = 'block';

            recordingTime    = 0;
            recordingInterval = setInterval(() => {
                recordingTime++;
                const m = Math.floor(recordingTime / 60).toString().padStart(2, '0');
                const s = (recordingTime % 60).toString().padStart(2, '0');
                timerDiv.textContent = `${m}:${s}`;
            }, 1000);

        } catch (error) {
            alert('Error accessing microphone: ' + error.message);
        }
    } else {
        mediaRecorder.stop();
        recordBtnText.textContent = 'Record Now';
        recordBtn.classList.remove('recording');
        statusDiv.textContent     = 'Processing recording…';
        timerDiv.style.display    = 'none';
        clearInterval(recordingInterval);
    }
}

async function sendRecording(audioBlob) {
    const statusDiv = document.getElementById('recordingStatus');
    statusDiv.textContent = 'Analyzing recording…';

    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');

    try {
        const response = await fetch('/record', { method: 'POST', body: formData });
        if (!response.ok) throw new Error('Recording upload failed');

        const result = await response.json();
        statusDiv.textContent = '✅ Recording processed successfully!';

        displayResults([result]);
        setTimeout(() => {
            document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 300);

    } catch (error) {
        statusDiv.textContent = `❌ Error: ${error.message}`;
    }
}

// ===== DISPLAY RESULTS =====
async function displayResults(results) {
    const resultsSection  = document.getElementById('resultsSection');
    const resultsContainer = document.getElementById('resultsContainer');

    resultsSection.style.display = 'block';
    resultsContainer.innerHTML   = '';

    for (let i = 0; i < results.length; i++) {
        const result = results[i];

        if (result.error) {
            resultsContainer.appendChild(createErrorCard(result));
            continue;
        }

        const cardContainer = document.createElement('div');
        cardContainer.className = 'result-with-map-container';

        cardContainer.appendChild(createResultCard(result, i));

        // ── NEW: Alert notification banner ──────────────────────────────────
        if (result.alert_sent) {
            cardContainer.appendChild(createAlertBanner(result));
        }

        if (result.entities && result.entities.location) {
            const mapSection = createMapSection(i);
            cardContainer.appendChild(mapSection);
            resultsContainer.appendChild(cardContainer);
            await showMapForResult(result.entities.location, i);
        } else {
            resultsContainer.appendChild(cardContainer);
        }
    }
}

// ─── NEW: Build the "alert sent" banner ─────────────────────────────────────
function createAlertBanner(result) {
    const banner = document.createElement('div');
    banner.className = 'alert-sent-banner';

    const centers = result.notified_centers && result.notified_centers.length
        ? result.notified_centers.join(', ')
        : 'nearby help centers';

    banner.innerHTML = `
        <div class="alert-sent-inner">
            <span class="alert-sent-icon">🔔</span>
            <div class="alert-sent-text">
                <strong>Alert Notification Sent!</strong>
                <span>Emergency alert dispatched to: <em>${centers}</em></span>
            </div>
            <span class="alert-sent-check">✔</span>
        </div>
    `;
    return banner;
}

function createResultCard(result, index) {
    const card = document.createElement('div');
    card.className = `result-card priority-${result.priority}`;

    const priorityLabels = { 1: 'CRITICAL', 2: 'HIGH', 3: 'MEDIUM', 4: 'LOW' };
    const emotionEmojis  = {
        'PANIC': '😨', 'DISTRESS': '😢', 'CALM': '😌',
        'angry': '😠', 'fear': '😨', 'sad': '😢', 'neutral': '😐',
        'happy': '😊', 'surprised': '😲'
    };

    card.innerHTML = `
        <div class="result-header">
            <div class="result-filename">Call #${index + 1}: ${result.filename}</div>
            <div class="badges">
                <span class="badge badge-priority">${priorityLabels[result.priority] || result.priority}</span>
                <span class="badge badge-emotion">${emotionEmojis[result.emotion] || ''} ${result.emotion}</span>
            </div>
        </div>

        <div class="result-transcript">
            <div class="transcript-label">📝 Transcript</div>
            <div>${result.transcript}</div>
        </div>

        <div class="entities-grid">
            ${result.entities.priority_level ? `
                <div class="entity-item">
                    <div class="entity-label">⚠️ Priority Level</div>
                    <div class="entity-value">${result.entities.priority_level}</div>
                </div>` : ''}

            ${result.entities.emergency_type ? `
                <div class="entity-item">
                    <div class="entity-label">🚨 Emergency Type</div>
                    <div class="entity-value">${result.entities.emergency_type}</div>
                </div>` : ''}

            ${result.entities.location ? `
                <div class="entity-item">
                    <div class="entity-label">📍 Location</div>
                    <div class="entity-value">${result.entities.location}</div>
                </div>` : ''}
        </div>
    `;
    return card;
}

function createErrorCard(result) {
    const card = document.createElement('div');
    card.className = 'result-card priority-4';
    card.innerHTML = `
        <div class="result-header">
            <div class="result-filename">❌ ${result.filename}</div>
        </div>
        <div class="result-transcript">
            <div class="transcript-label">Error</div>
            <div>${result.error}</div>
        </div>
    `;
    return card;
}

// ===== MAP + HELP CENTERS SIDE PANEL =====
function createMapSection(index) {
    const mapSection = document.createElement('div');
    mapSection.className = 'map-section-inline';
    mapSection.id = `mapSection-${index}`;
    mapSection.innerHTML = `
        <h3>🗺️ Incident Location &amp; Nearby Help Centers</h3>
        <div class="map-and-centers">
            <div class="map-col">
                <div id="map-${index}" class="map-inline"></div>
                <div class="map-legend">
                    <div><span class="legend-marker incident"></span> Incident</div>
                    <div><span class="legend-marker hospital"></span> Hospital</div>
                    <div><span class="legend-marker police"></span> Police</div>
                    <div><span class="legend-marker fire"></span> Fire Station</div>
                </div>
            </div>
            <div class="centers-col" id="centers-${index}">
                <div class="centers-loading">
                    <div class="loading-spinner"></div>
                    <p>Finding nearby help centers…</p>
                </div>
            </div>
        </div>
    `;
    return mapSection;
}

function serviceIcon(type) {
    const icons = {
        hospital:     '🏥',
        clinic:       '🏨',
        doctors:      '🏨',
        police:       '🚓',
        fire_station: '🚒'
    };
    return icons[type] || '🏢';
}

async function showMapForResult(location, index) {
    const mapId        = `map-${index}`;
    const mapSectionId = `mapSection-${index}`;
    const centersId    = `centers-${index}`;

    try {
        const response = await fetch('/geocode', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ location })
        });

        if (!response.ok) throw new Error('Geocoding failed');
        const data = await response.json();

        if (!data.found) {
            document.getElementById(mapSectionId).style.display = 'none';
            return;
        }

        if (mapInstances[mapId]) mapInstances[mapId].remove();

        mapInstances[mapId] = L.map(mapId).setView([data.location.lat, data.location.lon], 14);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(mapInstances[mapId]);

        const incidentIcon = L.divIcon({
            className: '',
            html: '<div style="background:#f08080;width:28px;height:28px;border-radius:50%;border:3px solid white;box-shadow:0 2px 8px rgba(0,0,0,0.3);"></div>',
            iconSize: [28, 28], iconAnchor: [14, 14]
        });
        L.marker([data.location.lat, data.location.lon], { icon: incidentIcon })
            .addTo(mapInstances[mapId])
            .bindPopup(`<b>Incident Location</b><br>${data.location.display_name}`);

        const services = data.emergency_services || [];
        services.forEach(service => {
            const color = (service.type === 'hospital' || service.type === 'clinic' || service.type === 'doctors')
                ? '#4da8da'
                : service.type === 'police' ? '#5580c8' : '#3a60a8';

            const icon = L.divIcon({
                className: '',
                html: `<div style="background:${color};width:22px;height:22px;border-radius:50%;border:2px solid white;box-shadow:0 2px 6px rgba(0,0,0,0.25);"></div>`,
                iconSize: [22, 22], iconAnchor: [11, 11]
            });

            L.marker([service.lat, service.lon], { icon })
                .addTo(mapInstances[mapId])
                .bindPopup(`<b>${service.name}</b><br>${service.type_label || service.type}<br>${service.distance_km} km away`);
        });

        setTimeout(() => { if (mapInstances[mapId]) mapInstances[mapId].invalidateSize(); }, 100);

        const centersDiv = document.getElementById(centersId);
        if (services.length === 0) {
            centersDiv.innerHTML = '<p class="no-centers">No help centers found nearby.</p>';
            return;
        }

        let listHTML = `
            <div class="centers-header">
                <span class="centers-icon">🏥</span>
                Nearby Help Centers (${services.length})
            </div>
            <div class="centers-list">
        `;
        services.forEach(s => {
            listHTML += `
                <div class="center-item">
                    <div class="center-icon-wrap">${serviceIcon(s.type)}</div>
                    <div class="center-details">
                        <div class="center-name">${s.name}</div>
                        <div class="center-type">${s.type_label || s.type}</div>
                        <div class="center-distance">Distance: ${s.distance_km} km</div>
                    </div>
                </div>
            `;
        });
        listHTML += '</div>';
        centersDiv.innerHTML = listHTML;

    } catch (error) {
        console.error('Map error:', error);
        const section = document.getElementById(mapSectionId);
        if (section) section.style.display = 'none';
    }
}