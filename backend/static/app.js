// PodcastSync Web UI

const API = "";

const SOURCE_PALETTES = [
    { accent: "#244983", soft: "rgba(36, 73, 131, 0.15)", glow: "rgba(36, 73, 131, 0.24)" },
    { accent: "#c76346", soft: "rgba(199, 99, 70, 0.16)", glow: "rgba(199, 99, 70, 0.24)" },
    { accent: "#1d8d86", soft: "rgba(29, 141, 134, 0.15)", glow: "rgba(29, 141, 134, 0.24)" },
    { accent: "#8c5bb6", soft: "rgba(140, 91, 182, 0.16)", glow: "rgba(140, 91, 182, 0.24)" },
    { accent: "#d58c2d", soft: "rgba(213, 140, 45, 0.16)", glow: "rgba(213, 140, 45, 0.24)" },
    { accent: "#2b7a78", soft: "rgba(43, 122, 120, 0.16)", glow: "rgba(43, 122, 120, 0.24)" },
];

let sources = [];
let selectedSourceId = null;
let autoSelectSource = true;
let settingsCache = null;
let currentStatus = null;
let detailVideos = [];
let detailVideosSourceId = null;
let pollTimer = null;
let progressTimer = null;
let _prevProgressIds = new Set();
let _progressRunning = false;
let displayNameManuallyEdited = false;
let detailActiveTab = "episodes";
let detailDeleteConfirmVisible = false;

async function api(method, path, body) {
    const options = { method, headers: {} };

    if (body) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }

    const response = await fetch(`${API}${path}`, options);
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || "Request failed");
    }

    if (response.status === 204) {
        return null;
    }

    return response.json();
}

function toast(message, type = "success") {
    const element = document.createElement("div");
    element.className = `toast ${type}`;
    element.textContent = message;
    document.body.appendChild(element);
    setTimeout(() => element.remove(), 3000);
}

function esc(value) {
    const element = document.createElement("span");
    element.textContent = value || "";
    return element.innerHTML;
}

function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value) || 0);
}

function formatFileSize(bytes) {
    if (!bytes) {
        return "";
    }

    return `${(bytes / 1048576).toFixed(1)} MB`;
}

function parseAppDate(value) {
    if (!value) {
        return null;
    }

    if (value instanceof Date) {
        return value;
    }

    const raw = String(value).trim();
    if (!raw) {
        return null;
    }

    // SQLite datetime('now') comes back as "YYYY-MM-DD HH:MM:SS" in UTC.
    // Treat that form as UTC explicitly so local browsers do not shift it.
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(raw)) {
        return new Date(raw.replace(" ", "T") + "Z");
    }

    return new Date(raw);
}

function timeAgo(isoString) {
    if (!isoString) {
        return "never";
    }

    const date = parseAppDate(isoString);
    if (!date || Number.isNaN(date.getTime())) {
        return "never";
    }
    const diffSeconds = (Date.now() - date.getTime()) / 1000;

    if (diffSeconds < 60) {
        return "just now";
    }
    if (diffSeconds < 3600) {
        return `${Math.floor(diffSeconds / 60)}m ago`;
    }
    if (diffSeconds < 86400) {
        return `${Math.floor(diffSeconds / 3600)}h ago`;
    }

    return `${Math.floor(diffSeconds / 86400)}d ago`;
}

function formatSyncAge(isoString) {
    if (!isoString) {
        return "New";
    }

    const date = parseAppDate(isoString);
    if (!date || Number.isNaN(date.getTime())) {
        return "New";
    }
    const diffSeconds = (Date.now() - date.getTime()) / 1000;

    if (diffSeconds < 60) {
        return "Just now";
    }
    if (diffSeconds < 3600) {
        const minutes = Math.floor(diffSeconds / 60);
        return `${minutes} min${minutes === 1 ? "" : "s"}`;
    }
    if (diffSeconds < 86400) {
        const hours = Math.floor(diffSeconds / 3600);
        return `${hours} hour${hours === 1 ? "" : "s"}`;
    }
    if (diffSeconds < 604800) {
        const days = Math.floor(diffSeconds / 86400);
        return `${days} day${days === 1 ? "" : "s"}`;
    }
    if (diffSeconds < 2592000) {
        const weeks = Math.floor(diffSeconds / 604800);
        return `${weeks} week${weeks === 1 ? "" : "s"}`;
    }

    const months = Math.floor(diffSeconds / 2592000);
    return `${months} month${months === 1 ? "" : "s"}`;
}

function formatDate(isoString) {
    if (!isoString) {
        return "Not yet";
    }

    const date = parseAppDate(isoString);
    if (!date || Number.isNaN(date.getTime())) {
        return "Not yet";
    }
    return new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
    }).format(date);
}

function deriveDisplayNameFromUrl(rawUrl) {
    const url = (rawUrl || "").trim();
    if (!url) {
        return "";
    }

    const handleMatch = url.match(/@([A-Za-z0-9._-]+)/);
    if (!handleMatch) {
        return "";
    }

    return handleMatch[1].replace(/[-_]+/g, " ").trim();
}

function normalizeDownloadStatus(status) {
    const normalized = String(status || "").toLowerCase();

    if (normalized === "finish" || normalized === "finished" || normalized === "complete") {
        return "completed";
    }

    if (normalized === "downloading" || normalized === "in_progress" || normalized === "in-progress") {
        return "downloading";
    }

    return normalized || "pending";
}

function getSourceById(id) {
    return sources.find((source) => source.id === id) || null;
}

function getPalette(source) {
    const offset = source.source_type === "playlist" ? 2 : 0;
    return SOURCE_PALETTES[(source.id + offset) % SOURCE_PALETTES.length];
}

function sourceKindLabel(sourceType) {
    return sourceType === "playlist" ? "Playlist" : "Channel";
}

function sourceStateLabel(enabled) {
    return enabled ? "Active" : "Paused";
}

function sourceSignature(sourceList) {
    return JSON.stringify(
        sourceList.map((source) => ({
            id: source.id,
            name: source.name,
            source_type: source.source_type,
            enabled: source.enabled,
            last_polled_at: source.last_polled_at,
            video_count: source.video_count,
            completed_count: source.completed_count,
            custom_storage_path: source.custom_storage_path,
            max_keep_episodes: source.max_keep_episodes,
            icon_url: source.icon_url,
        }))
    );
}

function ensureSelectedSource() {
    if (!sources.length) {
        selectedSourceId = null;
        return;
    }

    const selectionStillExists = sources.some((source) => source.id === selectedSourceId);
    if (!selectionStillExists) {
        selectedSourceId = autoSelectSource ? sources[0].id : null;
    }
}

function replaceSourceInState(updatedSource) {
    sources = sources.map((source) => (source.id === updatedSource.id ? updatedSource : source));
}

function safeSetInputValue(id, value, force = false) {
    const input = document.getElementById(id);
    if (!input) {
        return;
    }

    if (force || document.activeElement !== input) {
        input.value = value;
    }
}

function buildSourceSummary(source) {
    const parts = [
        `${formatNumber(source.completed_count)} ready`,
        `${formatNumber(source.video_count)} tracked`,
    ];

    if (source.last_polled_at) {
        parts.push(`Checked ${timeAgo(source.last_polled_at)}`);
    } else {
        parts.push("Not synced yet");
    }

    return parts.join(" • ");
}

function renderSourceArtMarkup(source, className = "source-art") {
    const palette = getPalette(source);
    const style = `style="--tile-accent:${palette.accent};--tile-soft:${palette.soft};--tile-glow:${palette.glow};"`;

    if (source.icon_url) {
        return `
            <div class="${className}" ${style}>
                <img src="${esc(source.icon_url)}" alt="${esc(source.name)} artwork">
            </div>
        `;
    }

    const initials = source.name
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => part[0].toUpperCase())
        .join("") || "PS";

    return `
        <div class="${className}" ${style}>
            <span class="source-art-fallback">${esc(initials)}</span>
        </div>
    `;
}

function renderOverview() {
    const totalShows = sources.length;
    const totalDownloaded = sources.reduce((sum, source) => sum + (source.completed_count || 0), 0);
    const activeOrQueued = (currentStatus?.active_downloads || 0) + (currentStatus?.download_queue_size || 0);

    const subtitle = document.getElementById("library-subtitle");
    if (!totalShows) {
        subtitle.textContent = "No sources attached yet.";
        return;
    }

    const summaryParts = [
        `${formatNumber(totalShows)} show${totalShows === 1 ? "" : "s"} attached`,
        `${formatNumber(totalDownloaded)} episode${totalDownloaded === 1 ? "" : "s"} ready`,
    ];

    if (activeOrQueued > 0) {
        summaryParts.push(`${formatNumber(activeOrQueued)} active or queued`);
    } else if (currentStatus?.next_poll) {
        const nextPoll = new Date(currentStatus.next_poll);
        const mins = Math.max(0, Math.round((nextPoll.getTime() - Date.now()) / 60000));
        summaryParts.push(`Next sync in ${mins}m`);
    } else {
        summaryParts.push("Library idle");
    }

    subtitle.textContent = summaryParts.join(" • ");
}

function renderSourceGrid() {
    const grid = document.getElementById("sources-grid");
    const empty = document.getElementById("no-sources");

    if (!sources.length) {
        grid.innerHTML = "";
        empty.hidden = false;
        return;
    }

    empty.hidden = true;

    grid.innerHTML = sources
        .map((source) => {
            const palette = getPalette(source);
            const stateClass = source.enabled ? "is-active" : "is-paused";
            const selectedClass = source.id === selectedSourceId ? "is-selected" : "";

            return `
                <article
                    class="source-tile ${selectedClass}"
                    data-id="${source.id}"
                    tabindex="0"
                    style="--tile-accent:${palette.accent};--tile-soft:${palette.soft};--tile-glow:${palette.glow};"
                    onclick="selectSource(${source.id})"
                    onkeydown="handleTileKeydown(event, ${source.id})"
                >
                    <div class="tile-top">
                        ${renderSourceArtMarkup(source)}
                        <div class="tile-meta-row">
                            <span class="tile-type ${source.source_type}">${sourceKindLabel(source.source_type)}</span>
                            <span class="tile-state-pill ${stateClass}">${sourceStateLabel(source.enabled)}</span>
                        </div>
                    </div>

                    <div class="tile-body">
                        <div>
                            <h3 class="tile-name">${esc(source.name)}</h3>
                            <p class="tile-subtitle">${esc(buildSourceSummary(source))}</p>
                        </div>

                        <div class="tile-stats">
                            <div class="tile-stat">
                                <span class="tile-stat-value">${formatNumber(source.completed_count)}</span>
                                <span class="tile-stat-label">Ready</span>
                            </div>
                            <div class="tile-stat">
                                <span class="tile-stat-value">${formatNumber(source.video_count)}</span>
                                <span class="tile-stat-label">Tracked</span>
                            </div>
                            <div class="tile-stat">
                                <span class="tile-stat-value tile-stat-sync">
                                    <svg class="tile-stat-sync-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                                        <circle cx="12" cy="12" r="8"></circle>
                                        <path d="M12 8v5l3 2"></path>
                                    </svg>
                                    <span class="tile-stat-sync-value">${formatSyncAge(source.last_polled_at)}</span>
                                </span>
                                <span class="tile-stat-label">Last sync</span>
                            </div>
                        </div>
                    </div>

                    <div class="tile-actions">
                        <button type="button" class="btn-ghost-sm" onclick="event.stopPropagation(); syncSource(${source.id})">Sync</button>
                        <button type="button" class="btn-ghost-sm" onclick="event.stopPropagation(); copyFeedUrl(${source.id})">RSS</button>
                        <label class="mini-toggle" onclick="event.stopPropagation()">
                            <input
                                type="checkbox"
                                ${source.enabled ? "checked" : ""}
                                onchange="toggleEnabled(${source.id}, this.checked)"
                            >
                            <span>${source.enabled ? "Enabled" : "Paused"}</span>
                        </label>
                    </div>
                </article>
            `;
        })
        .join("");
}

function renderDetail(forceInputs = false) {
    const panel = document.getElementById("detail-panel");
    const source = getSourceById(selectedSourceId);

    if (!source) {
        panel.hidden = true;
        document.getElementById("detail-videos").innerHTML = "";
        return;
    }

    panel.hidden = false;
    syncDetailTabUi();
    document.getElementById("detail-art").innerHTML = renderSourceArtMarkup(source);

    const detailBadge = document.getElementById("detail-badge");
    detailBadge.textContent = sourceKindLabel(source.source_type);
    detailBadge.className = `detail-badge ${source.source_type}`;

    const detailEnabledChip = document.getElementById("detail-enabled-chip");
    detailEnabledChip.textContent = sourceStateLabel(source.enabled);
    detailEnabledChip.className = `detail-enabled-chip ${source.enabled ? "is-active" : "is-paused"}`;

    document.getElementById("detail-name").textContent = source.name;
    document.getElementById("detail-meta").textContent =
        `${formatNumber(source.completed_count)} downloaded of ${formatNumber(source.video_count)} tracked • Added ${formatDate(source.created_at)} • Last checked ${source.last_polled_at ? timeAgo(source.last_polled_at) : "never"}`;

    safeSetInputValue("detail-path", source.custom_storage_path || "", forceInputs);
    safeSetInputValue("detail-keep", source.max_keep_episodes ? String(source.max_keep_episodes) : "", forceInputs);

    const enabledInput = document.getElementById("detail-enabled");
    if (forceInputs || document.activeElement !== enabledInput) {
        enabledInput.checked = !!source.enabled;
    }
    document.getElementById("detail-enabled-text").textContent = source.enabled ? "Enabled" : "Paused";

    document.getElementById("detail-episode-summary").textContent =
        `${formatNumber(source.video_count)} tracked • ${formatNumber(source.completed_count)} ready`;

    void updateDetailFeedUrl(source.id);
}

function renderAll(forceInputs = false) {
    ensureSelectedSource();
    renderOverview();
    renderSourceGrid();
    renderDetail(forceInputs);
}

function showEpisodeLoading() {
    const container = document.getElementById("detail-videos");
    container.innerHTML = `
        <div class="episode-loading">Loading latest episodes...</div>
        <div class="episode-loading">Loading latest episodes...</div>
        <div class="episode-loading">Loading latest episodes...</div>
    `;
}

function renderDetailVideos(videos) {
    const container = document.getElementById("detail-videos");

    if (!videos.length) {
        container.innerHTML = `
            <div class="episode-empty">
                No episodes have been discovered for this source yet. Run a sync to fetch the latest uploads.
            </div>
        `;
        return;
    }

    container.innerHTML = videos
        .map((video) => {
            const displayStatus = normalizeDownloadStatus(video.download_status);
            const sizeText = formatFileSize(video.file_size);
            const skipButton = !["completed", "skipped", "deleted", "downloading"].includes(displayStatus)
                ? `<button type="button" class="btn-ghost-sm" onclick="skipVideo(${selectedSourceId}, ${video.id})">Skip</button>`
                : "";
            const deleteButton = displayStatus === "completed"
                ? `<button type="button" class="btn-danger-sm" onclick="deleteVideoFile(${selectedSourceId}, ${video.id})">Delete File</button>`
                : "";
            const requeueButton = ["deleted", "failed"].includes(displayStatus)
                ? `<button type="button" class="btn-ghost-sm" onclick="requeueVideo(${selectedSourceId}, ${video.id})">Re-download</button>`
                : "";
            const progressMarkup = displayStatus === "downloading"
                ? `
                    <div class="download-progress-bar" id="progress-bar-${video.id}">
                        <div class="progress-fill"></div>
                    </div>
                    <div class="progress-info-text" id="progress-info-${video.id}">Downloading...</div>
                `
                : "";
            const errorMarkup = video.error_message
                ? `<div class="progress-info-text">${esc(video.error_message)}</div>`
                : "";

            return `
                <article class="episode-card" id="video-item-${video.id}">
                    <div class="episode-card-top">
                        <div>
                            <h5 class="episode-title">${esc(video.title)}</h5>
                            <p class="episode-subline">
                                <span>${video.publish_date ? formatDate(video.publish_date) : "No publish date"}</span>
                                ${sizeText ? `<span>${sizeText}</span>` : ""}
                            </p>
                        </div>
                        <div class="episode-status-row">
                            <span class="video-status ${displayStatus}">${esc(displayStatus)}</span>
                        </div>
                    </div>
                    ${progressMarkup}
                    ${errorMarkup}
                    <div class="episode-actions">
                        ${skipButton}
                        ${deleteButton}
                        ${requeueButton}
                    </div>
                </article>
            `;
        })
        .join("");
}

async function loadDetailVideos(sourceId) {
    try {
        const videos = await api("GET", `/api/sources/${sourceId}/videos`);
        if (selectedSourceId !== sourceId) {
            return;
        }

        detailVideos = videos;
        detailVideosSourceId = sourceId;
        renderDetailVideos(videos);
    } catch (error) {
        if (selectedSourceId !== sourceId) {
            return;
        }

        document.getElementById("detail-videos").innerHTML = `
            <div class="episode-empty">Could not load episodes for this source.</div>
        `;
        console.error("Failed to load videos:", error);
    }
}

async function loadSources() {
    try {
        const previousSignature = sourceSignature(sources);
        const previousSelection = selectedSourceId;
        const previousSelectedSignature = previousSelection
            ? sourceSignature(sources.filter((source) => source.id === previousSelection))
            : "[]";
        const nextSources = await api("GET", "/api/sources");
        const nextSignature = sourceSignature(nextSources);

        sources = nextSources;
        ensureSelectedSource();

        const dataChanged = previousSignature !== nextSignature;
        const selectionChanged = previousSelection !== selectedSourceId;
        const nextSelectedSignature = selectedSourceId
            ? sourceSignature(sources.filter((source) => source.id === selectedSourceId))
            : "[]";
        const selectedSourceChanged = previousSelectedSignature !== nextSelectedSignature;

        if (dataChanged || selectionChanged) {
            renderAll(selectionChanged);
        }

        if (selectedSourceId && (selectionChanged || selectedSourceChanged || detailVideosSourceId !== selectedSourceId)) {
            showEpisodeLoading();
            await loadDetailVideos(selectedSourceId);
        }
    } catch (error) {
        console.error("Failed to load sources:", error);
    }
}

function isLocalOrigin() {
    return ["localhost", "127.0.0.1"].includes(window.location.hostname);
}

async function getSettings(force = false) {
    if (!force && settingsCache) {
        return settingsCache;
    }

    settingsCache = await api("GET", "/api/settings");
    return settingsCache;
}

async function buildFeedUrl(sourceId) {
    const origin = isLocalOrigin() ? (await getSettings()).base_url : window.location.origin;
    return `${origin}/feed/${sourceId}.xml`;
}

async function updateDetailFeedUrl(sourceId) {
    const row = document.getElementById("detail-feed-url-row");
    const text = document.getElementById("detail-feed-url");

    if (!sourceId) {
        row.hidden = true;
        text.textContent = "";
        return;
    }

    try {
        const url = await buildFeedUrl(sourceId);
        if (selectedSourceId !== sourceId) {
            return;
        }

        text.textContent = url;
        row.hidden = false;
    } catch (error) {
        row.hidden = true;
    }
}

async function patchSource(sourceId, updates, successMessage) {
    const updatedSource = await api("PATCH", `/api/sources/${sourceId}`, updates);
    replaceSourceInState(updatedSource);
    renderAll(true);

    if (successMessage) {
        toast(successMessage);
    }

    return updatedSource;
}

function syncModalState() {
    const addModal = document.getElementById("add-modal");
    const settingsModal = document.getElementById("settings-modal");
    document.body.classList.toggle("modal-open", !addModal.hidden || !settingsModal.hidden);
}

function openAddSource() {
    document.getElementById("add-modal").hidden = false;
    document.getElementById("add-error").hidden = true;
    syncModalState();
    document.getElementById("source-url").focus();
}

function closeAddSource() {
    document.getElementById("add-modal").hidden = true;
    syncModalState();
}

function closeAddOnBackdrop(event) {
    if (event.target.id === "add-modal") {
        closeAddSource();
    }
}

function openSettings() {
    document.getElementById("settings-modal").hidden = false;
    syncModalState();
}

function closeSettings() {
    document.getElementById("settings-modal").hidden = true;
    syncModalState();
}

function closeSettingsOnBackdrop(event) {
    if (event.target.id === "settings-modal") {
        closeSettings();
    }
}

function handleTileKeydown(event, sourceId) {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectSource(sourceId);
    }
}

function selectSource(sourceId) {
    autoSelectSource = true;
    const selectionChanged = selectedSourceId !== sourceId;
    selectedSourceId = sourceId;
    renderAll(selectionChanged);

    if (selectionChanged || detailVideosSourceId !== sourceId) {
        showEpisodeLoading();
        void loadDetailVideos(sourceId);
    }

    if (window.innerWidth <= 1200) {
        document.getElementById("detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    }
}

function closeDetail() {
    selectedSourceId = null;
    autoSelectSource = false;
    detailVideos = [];
    detailVideosSourceId = null;
    detailActiveTab = "episodes";
    detailDeleteConfirmVisible = false;
    renderAll(true);
}

function syncDetailTabUi() {
    const episodesView = document.getElementById("detail-episodes-view");
    const settingsView = document.getElementById("detail-settings-view");
    const settingsButton = document.getElementById("detail-settings-btn");
    const deleteConfirm = document.getElementById("detail-delete-confirm");

    if (episodesView) {
        episodesView.hidden = detailActiveTab !== "episodes";
    }
    if (settingsView) {
        settingsView.hidden = detailActiveTab !== "settings";
    }
    if (settingsButton) {
        settingsButton.textContent = detailActiveTab === "settings" ? "Back" : "Settings";
    }
    if (deleteConfirm) {
        deleteConfirm.hidden = !detailDeleteConfirmVisible;
    }
}

function openDetailTab(tabName) {
    detailActiveTab = detailActiveTab === tabName ? "episodes" : tabName;
    syncDetailTabUi();
}

async function browseDirectory(inputId) {
    try {
        const result = await api("POST", "/api/pick-directory");
        if (result.path) {
            document.getElementById(inputId).value = result.path;
        }
    } catch (error) {
        toast("Could not open folder picker", "error");
    }
}

async function syncSource(sourceId) {
    try {
        await api("POST", `/api/sources/${sourceId}/sync`);
        const source = getSourceById(sourceId);
        if (source) {
            source.last_polled_at = new Date().toISOString();
        }
        autoSelectSource = true;
        selectedSourceId = sourceId;
        renderAll(true);
        showEpisodeLoading();
        void loadDetailVideos(sourceId);
        void loadStatus();
        void loadSources();
        toast("Sync started");
    } catch (error) {
        toast(error.message, "error");
    }
}

function syncDetailSource() {
    if (selectedSourceId) {
        void syncSource(selectedSourceId);
    }
}

async function copyFeedUrl(sourceId) {
    try {
        const url = await buildFeedUrl(sourceId);
        await navigator.clipboard.writeText(url);

        if (sourceId === selectedSourceId) {
            document.getElementById("detail-feed-url").textContent = url;
            document.getElementById("detail-feed-url-row").hidden = false;
        }

        toast("RSS feed copied");
    } catch (error) {
        toast("Failed to copy RSS feed", "error");
    }
}

function copyDetailFeedUrl() {
    if (selectedSourceId) {
        void copyFeedUrl(selectedSourceId);
    }
}

async function toggleEnabled(sourceId, enabled) {
    try {
        await patchSource(sourceId, { enabled }, enabled ? "Source enabled" : "Source paused");
    } catch (error) {
        renderAll(true);
        toast(error.message, "error");
    }
}

async function saveDetailPath() {
    if (!selectedSourceId) {
        return;
    }

    const customStoragePath = document.getElementById("detail-path").value.trim() || null;
    try {
        await patchSource(selectedSourceId, { custom_storage_path: customStoragePath }, "Download folder saved");
    } catch (error) {
        toast(error.message, "error");
    }
}

async function saveDetailKeep() {
    if (!selectedSourceId) {
        return;
    }

    const raw = document.getElementById("detail-keep").value.trim();
    const maxKeepEpisodes = raw ? parseInt(raw, 10) : null;

    try {
        await patchSource(
            selectedSourceId,
            { max_keep_episodes: maxKeepEpisodes },
            maxKeepEpisodes ? `Will keep last ${maxKeepEpisodes} episodes` : "Keep limit removed"
        );
    } catch (error) {
        toast(error.message, "error");
    }
}

async function saveDetailEnabled() {
    if (!selectedSourceId) {
        return;
    }

    const enabled = document.getElementById("detail-enabled").checked;
    try {
        await patchSource(selectedSourceId, { enabled }, enabled ? "Source enabled" : "Source paused");
    } catch (error) {
        renderAll(true);
        toast(error.message, "error");
    }
}

async function skipVideo(sourceId, videoId) {
    try {
        await api("DELETE", `/api/sources/${sourceId}/videos/${videoId}`);
        toast("Episode skipped");
        await loadDetailVideos(sourceId);
        await loadSources();
    } catch (error) {
        toast(error.message, "error");
    }
}

async function deleteVideoFile(sourceId, videoId) {
    if (!confirm("Delete the downloaded file? It will not be re-downloaded automatically.")) {
        return;
    }

    try {
        await api("DELETE", `/api/sources/${sourceId}/videos/${videoId}/file`);
        toast("Downloaded file removed");
        await loadDetailVideos(sourceId);
        await loadSources();
    } catch (error) {
        toast(error.message, "error");
    }
}

async function requeueVideo(sourceId, videoId) {
    try {
        await api("POST", `/api/sources/${sourceId}/videos/${videoId}/requeue`);
        toast("Episode queued for download");
        await loadDetailVideos(sourceId);
        await loadSources();
    } catch (error) {
        toast(error.message, "error");
    }
}

async function deleteSource(sourceId) {
    try {
        await api("DELETE", `/api/sources/${sourceId}`);
        toast("Source deleted");

        if (selectedSourceId === sourceId) {
            selectedSourceId = null;
            detailVideos = [];
            detailVideosSourceId = null;
            detailActiveTab = "episodes";
            detailDeleteConfirmVisible = false;
        }

        await loadSources();
        await loadStatus();
    } catch (error) {
        toast(error.message, "error");
    }
}

function deleteDetailSource() {
    if (selectedSourceId) {
        detailDeleteConfirmVisible = true;
        syncDetailTabUi();
    }
}

function cancelDetailDelete() {
    detailDeleteConfirmVisible = false;
    syncDetailTabUi();
}

function confirmDeleteDetailSource() {
    if (selectedSourceId) {
        detailDeleteConfirmVisible = false;
        syncDetailTabUi();
        void deleteSource(selectedSourceId);
    }
}

async function loadStatus() {
    try {
        const [status, settings] = await Promise.all([
            api("GET", "/api/status"),
            getSettings(true),
        ]);

        currentStatus = status;
        settingsCache = settings;

        const dot = document.getElementById("server-status");
        dot.className = `status-dot ${status.active_downloads > 0 ? "is-busy" : "is-live"}`;
        document.getElementById("status-text").textContent = status.active_downloads > 0 ? "Syncing" : "Connected";

        const parts = [];
        if (status.next_poll) {
            const next = new Date(status.next_poll);
            const mins = Math.max(0, Math.round((next.getTime() - Date.now()) / 60000));
            parts.push(`Next sync ${mins}m`);
        }
        if (status.active_downloads > 0) {
            parts.push(`${status.active_downloads} downloading`);
        }
        if (status.download_queue_size > 0) {
            parts.push(`${status.download_queue_size} queued`);
        }
        document.getElementById("next-poll").textContent = parts.join(" • ");

        document.getElementById("cancel-downloads-btn").hidden =
            status.active_downloads === 0 && status.download_queue_size === 0;

        safeSetInputValue("poll-interval", String(settings.poll_interval_minutes));
        document.getElementById("settings-info").textContent =
            `Base URL: ${settings.base_url} • API key: ${settings.youtube_api_key_set ? "set" : "not set"} • Storage: ${settings.storage_path}`;

        renderOverview();
        if (selectedSourceId) {
            void updateDetailFeedUrl(selectedSourceId);
        }
    } catch (error) {
        currentStatus = null;
        document.getElementById("server-status").className = "status-dot is-offline";
        document.getElementById("status-text").textContent = "Disconnected";
        document.getElementById("next-poll").textContent = "";
        renderOverview();
    }
}

async function refreshProgress() {
    if (_progressRunning) {
        return;
    }

    _progressRunning = true;

    try {
        const progress = await api("GET", "/api/downloads/progress");
        const currentIds = new Set(Object.keys(progress).map(Number));

        const completedSome = [..._prevProgressIds].some((id) => !currentIds.has(id));
        const newStarted = [...currentIds].some((id) => !_prevProgressIds.has(id));
        _prevProgressIds = currentIds;

        if ((completedSome || newStarted) && selectedSourceId) {
            await loadDetailVideos(selectedSourceId);
            await loadSources();
        }

        for (const [videoDbId, data] of Object.entries(progress)) {
            const progressBar = document.getElementById(`progress-bar-${videoDbId}`);
            const progressInfo = document.getElementById(`progress-info-${videoDbId}`);
            if (!progressBar) {
                continue;
            }

            const fill = progressBar.querySelector(".progress-fill");
            if (data.total_bytes > 0) {
                const percentage = Math.min(100, (data.downloaded_bytes / data.total_bytes) * 100);
                fill.style.width = `${percentage.toFixed(1)}%`;

                if (progressInfo) {
                    const downloadedMb = (data.downloaded_bytes / 1048576).toFixed(1);
                    const totalMb = (data.total_bytes / 1048576).toFixed(1);
                    progressInfo.textContent = `${downloadedMb} / ${totalMb} MB`;
                }
            } else if (progressInfo && data.downloaded_bytes > 0) {
                const downloadedMb = (data.downloaded_bytes / 1048576).toFixed(1);
                progressInfo.textContent = `${downloadedMb} MB downloaded...`;
            }
        }
    } catch (error) {
        // Progress polling is best-effort only.
    } finally {
        _progressRunning = false;
    }
}

async function cancelDownloads() {
    try {
        await api("POST", "/api/downloads/cancel-all");
        toast("Downloads cancelled");
        await loadStatus();
    } catch (error) {
        toast(error.message, "error");
    }
}

document.getElementById("add-source-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    const errorElement = document.getElementById("add-error");
    errorElement.hidden = true;

    const url = document.getElementById("source-url").value.trim();
    const name = document.getElementById("source-name").value.trim();
    const maxBackfill = parseInt(document.getElementById("source-backfill").value, 10);
    const customStoragePath = document.getElementById("source-path").value.trim() || null;
    const keepRaw = document.getElementById("source-keep").value.trim();
    const maxKeepEpisodes = keepRaw ? parseInt(keepRaw, 10) : null;

    try {
        const createdSource = await api("POST", "/api/sources", {
            url,
            name,
            max_backfill: maxBackfill,
            custom_storage_path: customStoragePath,
            max_keep_episodes: maxKeepEpisodes,
        });

        document.getElementById("add-source-form").reset();
        document.getElementById("source-backfill").value = "15";
        displayNameManuallyEdited = false;
        selectedSourceId = createdSource.id;
        autoSelectSource = true;
        detailVideos = [];
        detailVideosSourceId = null;
        closeAddSource();
        toast("Source added");
        await loadSources();
        await loadStatus();
    } catch (error) {
        errorElement.textContent = error.message;
        errorElement.hidden = false;
    }
});

document.getElementById("browse-source-path").addEventListener("click", () => {
    void browseDirectory("source-path");
});

document.getElementById("source-url").addEventListener("input", (event) => {
    if (displayNameManuallyEdited) {
        return;
    }

    document.getElementById("source-name").value = deriveDisplayNameFromUrl(event.target.value);
});

document.getElementById("source-name").addEventListener("input", (event) => {
    const currentValue = event.target.value.trim();
    const suggestedName = deriveDisplayNameFromUrl(document.getElementById("source-url").value);
    displayNameManuallyEdited = currentValue !== "" && currentValue !== suggestedName;
});

document.getElementById("sync-all-btn").addEventListener("click", async () => {
    try {
        await api("POST", "/api/sync-all");
        toast("Sync started for all sources");
        await loadStatus();
        await loadSources();
    } catch (error) {
        toast(error.message, "error");
    }
});

document.getElementById("save-api-key").addEventListener("click", async () => {
    const key = document.getElementById("api-key").value.trim();

    try {
        await api("PATCH", "/api/settings", { youtube_api_key: key });
        document.getElementById("api-key").value = "";
        toast("API key saved");
        await loadStatus();
    } catch (error) {
        toast(error.message, "error");
    }
});

document.getElementById("save-poll-interval").addEventListener("click", async () => {
    const interval = parseInt(document.getElementById("poll-interval").value, 10);

    try {
        await api("PATCH", "/api/settings", { poll_interval_minutes: interval });
        toast("Sync interval updated");
        await loadStatus();
    } catch (error) {
        toast(error.message, "error");
    }
});

document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
        void loadStatus();
        void loadSources();
    }
});

document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
        return;
    }

    if (!document.getElementById("add-modal").hidden) {
        closeAddSource();
        return;
    }

    if (!document.getElementById("settings-modal").hidden) {
        closeSettings();
        return;
    }

    if (window.innerWidth <= 1200 && selectedSourceId) {
        closeDetail();
    }
});

function startPolling() {
    void loadStatus();
    void loadSources();

    pollTimer = setInterval(() => {
        if (!document.hidden) {
            void loadStatus();
            void loadSources();
        }
    }, 5000);

    progressTimer = setInterval(() => {
        if (!document.hidden) {
            void refreshProgress();
        }
    }, 1000);
}

startPolling();
