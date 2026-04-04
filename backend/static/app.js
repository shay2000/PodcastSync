// PodcastSync Web UI

const API = '';  // same origin

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(`${API}${path}`, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Request failed');
    }
    if (res.status === 204) return null;
    return res.json();
}

function toast(message, type = 'success') {
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

function timeAgo(isoString) {
    if (!isoString) return 'never';
    const d = new Date(isoString);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let sources = [];
let expandedSourceId = null;

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

async function loadSources() {
    try {
        sources = await api('GET', '/api/sources');
        renderSources();
    } catch (e) {
        console.error('Failed to load sources:', e);
    }
}

function renderSources() {
    const list = document.getElementById('sources-list');
    const empty = document.getElementById('no-sources');

    if (sources.length === 0) {
        list.innerHTML = '';
        empty.hidden = false;
        return;
    }
    empty.hidden = true;

    list.innerHTML = sources.map(s => `
        <div class="source-card" data-id="${s.id}">
            <div class="source-header">
                <span>
                    <span class="source-name">${esc(s.name)}</span>
                    <span class="badge ${s.source_type}">${s.source_type}</span>
                </span>
                <label style="font-size:13px;min-width:auto">
                    <input type="checkbox" ${s.enabled ? 'checked' : ''} onchange="toggleEnabled(${s.id}, this.checked)"> Enabled
                </label>
            </div>
            <div class="source-meta">
                ${s.completed_count}/${s.video_count} episodes downloaded
                &middot; Last polled: ${timeAgo(s.last_polled_at)}
            </div>
            <div class="source-actions">
                <button onclick="syncSource(${s.id})" class="btn-secondary" style="font-size:12px;padding:4px 10px">Sync Now</button>
                <button onclick="copyFeedUrl(${s.id})" class="btn-secondary" style="font-size:12px;padding:4px 10px">Copy Feed URL</button>
                <span class="feed-url" id="feed-url-${s.id}"></span>
                <button onclick="toggleVideos(${s.id})" class="videos-toggle">
                    ${expandedSourceId === s.id ? 'Hide' : 'Show'} videos
                </button>
                <button onclick="deleteSource(${s.id})" class="btn-danger">Delete</button>
            </div>
            ${expandedSourceId === s.id ? `<div class="video-list" id="videos-${s.id}">Loading...</div>` : ''}
        </div>
    `).join('');

    if (expandedSourceId) loadVideos(expandedSourceId);
}

function esc(str) {
    const el = document.createElement('span');
    el.textContent = str;
    return el.innerHTML;
}

async function loadVideos(sourceId) {
    try {
        const videos = await api('GET', `/api/sources/${sourceId}/videos`);
        const container = document.getElementById(`videos-${sourceId}`);
        if (!container) return;

        if (videos.length === 0) {
            container.innerHTML = '<p class="info-text">No videos yet. Click "Sync Now" to fetch.</p>';
            return;
        }

        container.innerHTML = videos.map(v => `
            <div class="video-item">
                <span>${esc(v.title)} <span class="info-text">${v.publish_date ? v.publish_date.slice(0, 10) : ''}</span></span>
                <span class="video-status ${v.download_status}">${v.download_status}</span>
            </div>
        `).join('');
    } catch (e) {
        console.error('Failed to load videos:', e);
    }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

document.getElementById('add-source-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const errEl = document.getElementById('add-error');
    errEl.hidden = true;

    const url = document.getElementById('source-url').value.trim();
    const name = document.getElementById('source-name').value.trim();
    const maxBackfill = parseInt(document.getElementById('source-backfill').value, 10);

    try {
        await api('POST', '/api/sources', { url, name, max_backfill: maxBackfill });
        document.getElementById('source-url').value = '';
        document.getElementById('source-name').value = '';
        toast('Source added');
        loadSources();
    } catch (e) {
        errEl.textContent = e.message;
        errEl.hidden = false;
    }
});

async function syncSource(id) {
    try {
        toast('Syncing...');
        const result = await api('POST', `/api/sources/${id}/sync`);
        toast(`Found ${result.new_videos} new, downloaded ${result.downloaded}`);
        loadSources();
    } catch (e) {
        toast(e.message, 'error');
    }
}

document.getElementById('sync-all-btn').addEventListener('click', async () => {
    try {
        toast('Syncing all sources...');
        const result = await api('POST', '/api/sync-all');
        toast(`Synced ${result.sources_synced} sources: ${result.new_videos} new, ${result.downloaded} downloaded`);
        loadSources();
    } catch (e) {
        toast(e.message, 'error');
    }
});

async function copyFeedUrl(sourceId) {
    try {
        const settings = await api('GET', '/api/settings');
        const url = `${settings.base_url}/feed/${sourceId}.xml`;

        // Show the URL next to the button
        const urlEl = document.getElementById(`feed-url-${sourceId}`);
        if (urlEl) urlEl.textContent = url;

        await navigator.clipboard.writeText(url);
        toast('Feed URL copied!');
    } catch (e) {
        toast('Failed to copy URL', 'error');
    }
}

async function toggleEnabled(id, enabled) {
    try {
        await api('PATCH', `/api/sources/${id}`, { enabled });
    } catch (e) {
        toast(e.message, 'error');
        loadSources();
    }
}

function toggleVideos(id) {
    expandedSourceId = expandedSourceId === id ? null : id;
    renderSources();
}

async function deleteSource(id) {
    if (!confirm('Delete this source and all its videos?')) return;
    try {
        await api('DELETE', `/api/sources/${id}`);
        toast('Source deleted');
        if (expandedSourceId === id) expandedSourceId = null;
        loadSources();
    } catch (e) {
        toast(e.message, 'error');
    }
}

// Settings
document.getElementById('save-api-key').addEventListener('click', async () => {
    const key = document.getElementById('api-key').value.trim();
    try {
        await api('PATCH', '/api/settings', { youtube_api_key: key });
        document.getElementById('api-key').value = '';
        toast('API key saved');
        loadStatus();
    } catch (e) {
        toast(e.message, 'error');
    }
});

document.getElementById('save-poll-interval').addEventListener('click', async () => {
    const interval = parseInt(document.getElementById('poll-interval').value, 10);
    try {
        await api('PATCH', '/api/settings', { poll_interval_minutes: interval });
        toast('Poll interval updated');
        loadStatus();
    } catch (e) {
        toast(e.message, 'error');
    }
});

// ---------------------------------------------------------------------------
// Status polling
// ---------------------------------------------------------------------------

async function loadStatus() {
    try {
        const status = await api('GET', '/api/status');
        document.getElementById('server-status').className = 'status-dot green';
        document.getElementById('status-text').textContent = 'Connected';

        let pollText = '';
        if (status.next_poll) {
            const next = new Date(status.next_poll);
            const mins = Math.max(0, Math.round((next - Date.now()) / 60000));
            pollText = `Next poll: ${mins}m`;
        }
        if (status.active_downloads > 0) {
            pollText += ` | ${status.active_downloads} downloading`;
        }
        if (status.download_queue_size > 0) {
            pollText += ` | ${status.download_queue_size} queued`;
        }
        document.getElementById('next-poll').textContent = pollText;

        // Load settings
        const settings = await api('GET', '/api/settings');
        document.getElementById('poll-interval').value = settings.poll_interval_minutes;
        document.getElementById('settings-info').textContent =
            `Base URL: ${settings.base_url} | API key: ${settings.youtube_api_key_set ? 'set' : 'not set'} | Storage: ${settings.storage_path}`;
    } catch (e) {
        document.getElementById('server-status').className = 'status-dot red';
        document.getElementById('status-text').textContent = 'Disconnected';
    }
}

// Poll for updates when page is visible
let pollTimer;
function startPolling() {
    loadStatus();
    loadSources();
    pollTimer = setInterval(() => {
        if (!document.hidden) {
            loadStatus();
            loadSources();
        }
    }, 5000);
}

document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        loadStatus();
        loadSources();
    }
});

// Initialize
startPolling();
