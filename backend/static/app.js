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
        const newSources = await api('GET', '/api/sources');
        // Full re-render only when the source list size changes or on first load
        if (newSources.length !== sources.length) {
            sources = newSources;
            renderSources();
        } else {
            refreshSourceMeta(newSources);
        }
    } catch (e) {
        console.error('Failed to load sources:', e);
    }
}

/** Targeted in-place update of counter + last-polled text. No DOM wipe. */
function refreshSourceMeta(newSources) {
    for (const s of newSources) {
        const card = document.querySelector(`.source-card[data-id="${s.id}"]`);
        if (!card) {
            // A card is missing — fall back to full render
            sources = newSources;
            renderSources();
            return;
        }
        const meta = card.querySelector('.source-meta');
        if (meta) {
            meta.innerHTML =
                `${s.completed_count}/${s.video_count} episodes downloaded` +
                ` &middot; Last polled: ${timeAgo(s.last_polled_at)}`;
        }
    }
    sources = newSources;
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
                    ${s.icon_url ? `<img src="${s.icon_url}" class="source-icon" alt="">` : ''}
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
            <div class="source-path-row">
                <span class="path-label">Download to:</span>
                <input type="text" class="path-input" id="path-${s.id}"
                    value="${esc(s.custom_storage_path || '')}"
                    placeholder="Default (~/PodcastMirror/${esc(s.name)}/)">
                <button onclick="browseDirectory('path-${s.id}')" class="btn-secondary btn-sm">Browse…</button>
                <button onclick="savePath(${s.id})" class="btn-secondary btn-sm">Save path</button>
            </div>
            <div class="source-path-row">
                <span class="path-label">Keep last:</span>
                <input type="number" class="keep-input" id="keep-${s.id}" min="1"
                    value="${s.max_keep_episodes || ''}"
                    placeholder="∞ (keep all)">
                <span class="path-label" style="white-space:nowrap">episodes on disk</span>
                <button onclick="saveKeep(${s.id})" class="btn-secondary btn-sm">Save</button>
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

        container.innerHTML = videos.map(v => {
            const sizeMB = v.file_size ? `<span class="size-text">${(v.file_size / 1048576).toFixed(1)} MB</span>` : '';

            const isActionable = !['completed', 'skipped', 'deleted', 'downloading'].includes(v.download_status);
            const skipBtn = isActionable
                ? `<button onclick="skipVideo(${sourceId}, ${v.id})" class="btn-skip" title="Skip this video">Skip</button>`
                : '';
            const deleteBtn = v.download_status === 'completed'
                ? `<button onclick="deleteVideoFile(${sourceId}, ${v.id})" class="btn-delete-file" title="Delete file (won't auto-re-download)">Delete file</button>`
                : '';
            const requeueBtn = (v.download_status === 'deleted' || v.download_status === 'failed')
                ? `<button onclick="requeueVideo(${sourceId}, ${v.id})" class="btn-requeue" title="Re-queue for download">Re-download</button>`
                : '';

            const progressBar = v.download_status === 'downloading' ? `
                <div class="download-progress-bar" id="progress-bar-${v.id}">
                    <div class="progress-fill" style="width:0%"></div>
                </div>
                <div class="progress-info-text" id="progress-info-${v.id}">Downloading…</div>` : '';

            return `
            <div class="video-item" id="video-item-${v.id}">
                <div class="video-item-row">
                    <span class="video-title">${esc(v.title)} <span class="info-text">${v.publish_date ? v.publish_date.slice(0, 10) : ''}</span></span>
                    <span class="video-right">
                        ${sizeMB}
                        <span class="video-status ${v.download_status}">${v.download_status}</span>
                        ${skipBtn}${deleteBtn}${requeueBtn}
                    </span>
                </div>
                ${progressBar}
            </div>`;
        }).join('');
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
    const customPath = document.getElementById('source-path').value.trim() || null;

    const keepRaw = document.getElementById('source-keep').value.trim();
    const maxKeep = keepRaw ? parseInt(keepRaw, 10) : null;

    try {
        await api('POST', '/api/sources', { url, name, max_backfill: maxBackfill, custom_storage_path: customPath, max_keep_episodes: maxKeep });
        document.getElementById('source-url').value = '';
        document.getElementById('source-name').value = '';
        document.getElementById('source-path').value = '';
        document.getElementById('source-keep').value = '';
        toast('Source added');
        sources = [];  // Force full re-render on next load
        loadSources();
    } catch (e) {
        errEl.textContent = e.message;
        errEl.hidden = false;
    }
});

document.getElementById('browse-source-path').addEventListener('click', () => {
    browseDirectory('source-path');
});

async function browseDirectory(inputId) {
    try {
        const result = await api('POST', '/api/pick-directory');
        if (result.path) {
            document.getElementById(inputId).value = result.path;
        }
    } catch (e) {
        toast('Could not open folder picker', 'error');
    }
}

async function syncSource(id) {
    try {
        await api('POST', `/api/sources/${id}/sync`);
        toast('Sync started — downloads will appear below');
        // Expand the video list so progress bars are visible
        expandedSourceId = id;
        sources = [];
        loadSources();
    } catch (e) {
        toast(e.message, 'error');
    }
}

document.getElementById('sync-all-btn').addEventListener('click', async () => {
    try {
        await api('POST', '/api/sync-all');
        toast('Sync started for all sources');
        sources = [];
        loadSources();
    } catch (e) {
        toast(e.message, 'error');
    }
});

async function copyFeedUrl(sourceId) {
    try {
        // If the UI is accessed via a LAN IP, use that — it's already known-good
        // for other devices. If accessed via localhost, fall back to the server's
        // detected LAN IP so phone/tablet clients can still reach the feed.
        const pageOrigin = window.location.origin;
        const isLocal = pageOrigin.includes('localhost') || pageOrigin.includes('127.0.0.1');
        let origin = pageOrigin;
        if (isLocal) {
            const settings = await api('GET', '/api/settings');
            origin = settings.base_url;
        }

        const url = `${origin}/feed/${sourceId}.xml`;

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
        sources = [];
        loadSources();
    }
}

function toggleVideos(id) {
    expandedSourceId = expandedSourceId === id ? null : id;
    renderSources();
}

async function savePath(id) {
    const path = document.getElementById(`path-${id}`).value.trim();
    try {
        await api('PATCH', `/api/sources/${id}`, { custom_storage_path: path || null });
        toast('Download path saved');
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function saveKeep(id) {
    const raw = document.getElementById(`keep-${id}`).value.trim();
    const max_keep_episodes = raw ? parseInt(raw, 10) : null;
    try {
        await api('PATCH', `/api/sources/${id}`, { max_keep_episodes });
        toast(max_keep_episodes ? `Will keep last ${max_keep_episodes} episodes` : 'Keep limit removed');
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function skipVideo(sourceId, videoId) {
    try {
        await api('DELETE', `/api/sources/${sourceId}/videos/${videoId}`);
        const el = document.getElementById(`video-item-${videoId}`);
        if (el) {
            el.querySelector('.video-status').className = 'video-status skipped';
            el.querySelector('.video-status').textContent = 'skipped';
            const skipBtn = el.querySelector('.btn-skip');
            if (skipBtn) skipBtn.remove();
        }
        refreshSourceMeta(sources);
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function deleteVideoFile(sourceId, videoId) {
    if (!confirm('Delete the downloaded file? It will NOT be re-downloaded automatically — use "Re-download" to queue it again.')) return;
    try {
        await api('DELETE', `/api/sources/${sourceId}/videos/${videoId}/file`);
        loadVideos(sourceId);
        sources = [];
        loadSources();
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function requeueVideo(sourceId, videoId) {
    try {
        await api('POST', `/api/sources/${sourceId}/videos/${videoId}/requeue`);
        toast('Re-queued — will download on next sync');
        loadVideos(sourceId);
    } catch (e) {
        toast(e.message, 'error');
    }
}

async function deleteSource(id) {
    if (!confirm('Delete this source and all its videos?')) return;
    try {
        await api('DELETE', `/api/sources/${id}`);
        toast('Source deleted');
        if (expandedSourceId === id) expandedSourceId = null;
        sources = [];
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

        const cancelBtn = document.getElementById('cancel-downloads-btn');
        if (cancelBtn) {
            cancelBtn.hidden = (status.active_downloads === 0 && status.download_queue_size === 0);
        }

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

let _prevProgressIds = new Set();
let _progressRunning = false;

async function refreshProgress() {
    if (_progressRunning) return;
    _progressRunning = true;
    try {
        const progress = await api('GET', '/api/downloads/progress');
        const currentIds = new Set(Object.keys(progress).map(Number));

        const completedSome = [..._prevProgressIds].some(id => !currentIds.has(id));
        const newStarted = [...currentIds].some(id => !_prevProgressIds.has(id));
        _prevProgressIds = currentIds;

        // Refresh the video list FIRST (creates/removes progress bar DOM elements),
        // then paint bars below. Awaiting ensures the DOM is ready before we update it.
        if ((completedSome || newStarted) && expandedSourceId) {
            await loadVideos(expandedSourceId);
            if (completedSome) {
                sources = [];
                loadSources();
            }
        }

        // Paint / update all visible progress bars
        for (const [videoDbId, data] of Object.entries(progress)) {
            const bar = document.getElementById(`progress-bar-${videoDbId}`);
            const info = document.getElementById(`progress-info-${videoDbId}`);
            if (!bar) continue;
            const fill = bar.querySelector('.progress-fill');
            if (data.total_bytes > 0) {
                const pct = Math.min(100, (data.downloaded_bytes / data.total_bytes) * 100);
                fill.style.width = `${pct.toFixed(1)}%`;
                const dlMB = (data.downloaded_bytes / 1048576).toFixed(1);
                const totalMB = (data.total_bytes / 1048576).toFixed(1);
                if (info) info.textContent = `${dlMB} / ${totalMB} MB`;
            } else if (data.downloaded_bytes > 0) {
                const dlMB = (data.downloaded_bytes / 1048576).toFixed(1);
                if (info) info.textContent = `${dlMB} MB downloaded…`;
            }
        }
    } catch (e) {
        // Non-critical — ignore
    } finally {
        _progressRunning = false;
    }
}

async function cancelDownloads() {
    try {
        await api('POST', '/api/downloads/cancel-all');
        toast('Downloads cancelled — queued items will not start');
        loadStatus();
    } catch (e) {
        toast(e.message, 'error');
    }
}

// Poll for updates when page is visible
let pollTimer;
let progressTimer;
function startPolling() {
    loadStatus();
    loadSources();
    pollTimer = setInterval(() => {
        if (!document.hidden) {
            loadStatus();
            loadSources();  // Uses refreshSourceMeta when count is unchanged — no flicker
        }
    }, 5000);
    progressTimer = setInterval(() => {
        if (!document.hidden) refreshProgress();
    }, 1000);
}

document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        loadStatus();
        loadSources();
    }
});

// Initialize
startPolling();
