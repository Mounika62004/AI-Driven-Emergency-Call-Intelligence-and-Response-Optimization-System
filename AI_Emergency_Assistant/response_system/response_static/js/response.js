/* ─── response.js ─────────────────────────────────────────────────────────── */

let selectedCenter = null;
let swRegistration  = null;
let pollInterval    = null;
let lastAlertTime   = null;   // track newest alert for change detection

// ─── Audio: generate an emergency siren sound with Web Audio API ──────────────
function playEmergencySound(durationSec = 5) {
    try {
        const ctx     = new (window.AudioContext || window.webkitAudioContext)();
        const gainNode = ctx.createGain();
        gainNode.connect(ctx.destination);

        const startTime = ctx.currentTime;
        let t = startTime;

        // Three "woop" cycles over durationSec seconds
        const cycles    = Math.max(1, Math.floor(durationSec / 1.5));
        const cycleTime = durationSec / cycles;

        for (let i = 0; i < cycles; i++) {
            const osc = ctx.createOscillator();
            osc.connect(gainNode);
            osc.type = 'sawtooth';

            // Sweep from 800 Hz → 1400 Hz → 800 Hz per cycle
            osc.frequency.setValueAtTime(800,  t);
            osc.frequency.linearRampToValueAtTime(1400, t + cycleTime * 0.5);
            osc.frequency.linearRampToValueAtTime(800,  t + cycleTime);

            // Volume envelope: fade in / sustain / fade out
            gainNode.gain.setValueAtTime(0, t);
            gainNode.gain.linearRampToValueAtTime(0.25, t + 0.05);
            gainNode.gain.setValueAtTime(0.25, t + cycleTime - 0.1);
            gainNode.gain.linearRampToValueAtTime(0, t + cycleTime);

            osc.start(t);
            osc.stop(t + cycleTime);
            t += cycleTime;
        }
    } catch (e) {
        console.warn('Could not play emergency sound:', e);
    }
}

// ─── Fetch and populate the center dropdown ──────────────────────────────────
async function loadCenters() {
    try {
        const res     = await fetch('/centers');
        const centers = await res.json();
        const select  = document.getElementById('centerSelect');

        // Clear existing options (keep placeholder)
        while (select.options.length > 1) select.remove(1);

        centers.forEach(c => {
            const opt = document.createElement('option');
            opt.value            = c.name;
            opt.dataset.location = c.location;
            opt.dataset.state    = c.state;
            opt.dataset.type     = c.type || 'General';
            opt.textContent      = `${c.name}  (${c.location}, ${c.state})`;
            select.appendChild(opt);
        });

        // Restore previously selected center
        const saved = localStorage.getItem('selectedCenter');
        if (saved) {
            select.value = saved;
            if (select.value === saved) {
                selectedCenter = saved;
                document.getElementById('enableNotifBtn').style.display = 'flex';
            }
        }
    } catch (e) {
        console.error('Failed to load centers:', e);
    }
}

// ─── Dropdown change ─────────────────────────────────────────────────────────
document.getElementById('centerSelect').addEventListener('change', function () {
    selectedCenter = this.value || null;
    document.getElementById('enableNotifBtn').style.display = selectedCenter ? 'flex' : 'none';
    document.getElementById('notifStatus').textContent = '';
    document.getElementById('notifStatus').className   = 'status-text';
});

// ─── Enable push notifications ────────────────────────────────────────────────
async function enableNotifications() {
    if (!selectedCenter) return;

    const statusEl = document.getElementById('notifStatus');
    statusEl.textContent  = '⏳ Setting up notifications…';
    statusEl.className    = 'status-text';

    // 1. Register service worker
    if (!('serviceWorker' in navigator)) {
        statusEl.textContent = '❌ Service Workers not supported in this browser.';
        statusEl.className   = 'status-text error';
        return;
    }

    try {
        swRegistration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
        console.log('SW registered:', swRegistration.scope);

        // Wait until SW is active
        await new Promise(resolve => {
            if (swRegistration.active) { resolve(); return; }
            swRegistration.addEventListener('updatefound', () => {
                const sw = swRegistration.installing;
                sw.addEventListener('statechange', () => {
                    if (sw.state === 'activated') resolve();
                });
            });
            setTimeout(resolve, 3000); // failsafe
        });

    } catch (err) {
        statusEl.textContent = `❌ SW registration failed: ${err.message}`;
        statusEl.className   = 'status-text error';
        return;
    }

    // 2. Request notification permission
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
        statusEl.textContent = '❌ Notification permission denied. Please allow notifications in your browser.';
        statusEl.className   = 'status-text error';
        return;
    }

    // 3. Subscribe to Web Push (if VAPID key is configured)
    if (VAPID_PUBLIC_KEY && VAPID_PUBLIC_KEY !== 'NOT_CONFIGURED') {
        try {
            const subscription = await swRegistration.pushManager.subscribe({
                userVisibleOnly:      true,
                applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY)
            });

            await fetch('/subscribe', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    center_name:  selectedCenter,
                    subscription: subscription.toJSON()
                })
            });

            console.log('Push subscription registered.');
        } catch (err) {
            console.warn('Push subscription failed (falling back to polling):', err);
        }
    }

    // 4. Persist choice and show dashboard
    localStorage.setItem('selectedCenter', selectedCenter);
    statusEl.textContent = '✅ All set! Notifications enabled.';
    statusEl.className   = 'status-text success';

    setTimeout(() => showDashboard(), 800);
}

// ─── Show active dashboard ────────────────────────────────────────────────────
function showDashboard() {
    const select  = document.getElementById('centerSelect');
    const opt     = select.selectedOptions[0];
    const cType   = opt?.dataset.type     || '';
    const cLoc    = opt?.dataset.location || '';
    const cState  = opt?.dataset.state    || '';

    document.getElementById('selectCard').style.display   = 'none';
    document.getElementById('registerCard').style.display = 'none';
    document.getElementById('dashboard').style.display    = 'block';

    document.getElementById('activeCenterName').textContent = selectedCenter;
    document.getElementById('activeCenterMeta').textContent =
        `${cType} · ${cLoc}, ${cState}`;

    // Update header status dot
    setOnline(true);

    // Start polling for new alerts (every 15 s — fallback for push)
    loadAlerts();
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(loadAlerts, 15000);
}

function changeCenterView() {
    clearInterval(pollInterval);
    document.getElementById('dashboard').style.display  = 'none';
    document.getElementById('selectCard').style.display = 'block';
    setOnline(false);
}

function setOnline(online) {
    const el  = document.getElementById('connectionStatus');
    const dot = el.querySelector('.dot');
    dot.className     = `dot ${online ? 'online' : 'offline'}`;
    el.querySelector('span:last-child').textContent = online ? 'Online' : 'Offline';
}

// ─── Fetch & render alerts ───────────────────────────────────────────────────
async function loadAlerts() {
    if (!selectedCenter) return;
    try {
        const res    = await fetch(`/alerts?center=${encodeURIComponent(selectedCenter)}`);
        const alerts = await res.json();
        renderAlerts(alerts);

        // Detect new alert since last poll → auto-show modal + sound
        if (alerts.length > 0) {
            const newest = alerts[0].timestamp;
            if (lastAlertTime && newest !== lastAlertTime) {
                // New alert arrived while tab was open
                playEmergencySound(5);
                showAlertModal(alerts[0]);
            }
            lastAlertTime = newest;
        }
    } catch (e) {
        console.error('Failed to load alerts:', e);
    }
}

const PRIORITY_CLASS = { 1: 'critical', 2: 'high', 3: 'medium', 4: 'low' };

function renderAlerts(alerts) {
    const list = document.getElementById('alertsList');
    if (!alerts || alerts.length === 0) {
        list.innerHTML = `
            <div class="no-alerts">
                <div class="no-alerts-icon">📭</div>
                <p>No alerts received yet.</p>
                <p class="no-alerts-sub">Alerts from the Emergency App will appear here automatically.</p>
            </div>`;
        return;
    }

    list.innerHTML = alerts.map(a => {
        const pClass = PRIORITY_CLASS[a.priority] || 'medium';
        const time   = a.timestamp ? new Date(a.timestamp).toLocaleString() : '—';
        const loc    = a.location  || 'Unknown';
        const etype  = (a.emergency_type || 'Unknown').charAt(0).toUpperCase()
                     + (a.emergency_type || 'unknown').slice(1);
        const txt    = (a.transcript || '').substring(0, 150);
        const more   = (a.transcript || '').length > 150 ? '…' : '';

        return `
            <div class="alert-item priority-${pClass}">
                <div class="alert-item-header">
                    <span class="alert-badge">${a.title || '🚨 Emergency Alert'}</span>
                    <span class="alert-time">${time}</span>
                </div>
                <div class="alert-detail">📍 ${loc} &nbsp;|&nbsp; 🚨 ${etype} &nbsp;|&nbsp; 😤 ${a.emotion || '—'}</div>
                <div class="alert-transcript">${txt}${more}</div>
            </div>`;
    }).join('');
}

// ─── Alert Modal ─────────────────────────────────────────────────────────────
function showAlertModal(data) {
    const modal     = document.getElementById('alertModal');
    const pLabels   = { 1: 'CRITICAL', 2: 'HIGH', 3: 'MEDIUM', 4: 'LOW' };
    const pBadge    = document.getElementById('modalPriorityBadge');
    const pColors   = { 1: '#dc2626', 2: '#f97316', 3: '#eab308', 4: '#22c55e' };

    pBadge.textContent        = pLabels[data.priority] || 'ALERT';
    pBadge.style.background   = pColors[data.priority] || '#e83e4a';

    document.getElementById('modalTitle').textContent = data.title || '🚨 Emergency Alert';
    document.getElementById('modalBody').innerHTML = `
        <div class="modal-field"><strong>📍 Location:</strong> ${data.location || 'Not specified'}</div>
        <div class="modal-field"><strong>🚨 Type:</strong> ${(data.emergency_type || 'Unknown').charAt(0).toUpperCase() + (data.emergency_type || 'unknown').slice(1)}</div>
        <div class="modal-field"><strong>😤 Caller Emotion:</strong> ${data.emotion || 'Unknown'}</div>
        <div class="modal-field"><strong>📝 Transcript:</strong><br><em>${(data.transcript || '').substring(0, 200)}${(data.transcript || '').length > 200 ? '…' : ''}</em></div>
    `;

    modal.style.display = 'flex';

    // Update header dot to "alerting"
    const dot = document.querySelector('.status-indicator .dot');
    if (dot) { dot.className = 'dot alerting'; }

    // Auto-restore after 60 s
    setTimeout(() => {
        if (dot) dot.className = 'dot online';
    }, 60000);
}

function dismissAlert(e) {
    // Dismiss only if clicking the backdrop, not the content
    if (e && e.target === document.getElementById('alertModal')) dismissAlertBtn();
}
function dismissAlertBtn() {
    document.getElementById('alertModal').style.display = 'none';
    const dot = document.querySelector('.status-indicator .dot');
    if (dot) dot.className = 'dot online';
}

// ─── Handle messages from service worker (notification click) ─────────────────
navigator.serviceWorker?.addEventListener('message', (e) => {
    if (e.data && e.data.type === 'ALERT_CLICKED') {
        playEmergencySound(5);
        showAlertModal(e.data.payload);
        // Reload alerts list too
        loadAlerts();
    }
});

// ─── Registration form ────────────────────────────────────────────────────────
function showRegister() {
    document.getElementById('selectCard').style.display   = 'none';
    document.getElementById('registerCard').style.display = 'block';
}
function hideRegister() {
    document.getElementById('registerCard').style.display = 'none';
    document.getElementById('selectCard').style.display   = 'block';
}

async function registerCenter() {
    const name     = document.getElementById('regName').value.trim();
    const location = document.getElementById('regLocation').value.trim();
    const state    = document.getElementById('regState').value.trim();
    const type     = document.getElementById('regType').value;
    const statusEl = document.getElementById('regStatus');

    if (!name || !location || !state) {
        statusEl.textContent = '⚠️ Please fill in all fields.';
        statusEl.className   = 'status-text error';
        return;
    }

    try {
        const res  = await fetch('/register', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ name, location, state, type })
        });
        const data = await res.json();

        if (data.error) {
            statusEl.textContent = `❌ ${data.error}`;
            statusEl.className   = 'status-text error';
        } else {
            statusEl.textContent = '✅ Registered successfully! Redirecting…';
            statusEl.className   = 'status-text success';
            setTimeout(async () => {
                await loadCenters();
                // Auto-select the new center
                const select = document.getElementById('centerSelect');
                select.value = name;
                if (select.value === name) {
                    selectedCenter = name;
                    document.getElementById('enableNotifBtn').style.display = 'flex';
                }
                hideRegister();
            }, 1200);
        }
    } catch (e) {
        statusEl.textContent = `❌ Error: ${e.message}`;
        statusEl.className   = 'status-text error';
    }
}

// ─── Utility: VAPID key conversion ───────────────────────────────────────────
function urlBase64ToUint8Array(base64String) {
    const padding  = '='.repeat((4 - base64String.length % 4) % 4);
    const base64   = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData  = window.atob(base64);
    const output   = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) output[i] = rawData.charCodeAt(i);
    return output;
}

// ─── Init ─────────────────────────────────────────────────────────────────────
loadCenters();

// If returning to dashboard with saved center, auto-restore dashboard
window.addEventListener('load', () => {
    const saved = localStorage.getItem('selectedCenter');
    if (saved && Notification.permission === 'granted') {
        selectedCenter = saved;
        // Brief delay so dropdown loads first
        setTimeout(() => {
            const select = document.getElementById('centerSelect');
            select.value = saved;
            if (select.value === saved) {
                showDashboard();
            }
        }, 600);
    }
});