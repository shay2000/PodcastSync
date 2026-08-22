import { api, getSettings } from "./api.js";
import { renderDetailVideos, showEpisodeLoading } from "./render/episodes.js";
import { renderOverview } from "./render/sources.js";
import { toast } from "./ui/toast.js";
import {
    hasSourceDataChanged,
    setCurrentStatus,
    setDetailVideos,
    setSources,
    state,
} from "./store.js";

export async function loadDetailVideos(sourceId, { showLoading = false } = {}) {
    if (showLoading) {
        showEpisodeLoading();
    }

    try {
        const videos = await api("GET", `/api/sources/${sourceId}/videos`);
        if (state.selectedSourceId !== sourceId) {
            return;
        }
        setDetailVideos(videos, sourceId);
        renderDetailVideos(videos);
    } catch (error) {
        if (state.selectedSourceId !== sourceId) {
            return;
        }
        document.getElementById("detail-videos").innerHTML = `
            <div class="episode-empty">Could not load episodes for this source.</div>
        `;
        console.error("Failed to load videos:", error);
    }
}

export async function loadSources() {
    try {
        const previousSources = state.sources;
        const previousSelection = state.selectedSourceId;
        const previousSelectedSignature = previousSelection
            ? JSON.stringify(previousSources.filter((source) => source.id === previousSelection))
            : "[]";
        const nextSources = await api("GET", "/api/sources");

        setSources(nextSources, { notify: false });
        const selectionChanged = previousSelection !== state.selectedSourceId;
        const nextSelectedSignature = state.selectedSourceId
            ? JSON.stringify(state.sources.filter((source) => source.id === state.selectedSourceId))
            : "[]";
        const selectedSourceChanged = previousSelectedSignature !== nextSelectedSignature;
        const dataChanged = hasSourceDataChanged(nextSources, previousSources);

        if (dataChanged || selectionChanged) {
            // Store notification is synchronous, matching the old renderAll path.
            setSources(state.sources, { resetInputs: selectionChanged });
        }

        if (state.selectedSourceId && (
            selectionChanged
            || selectedSourceChanged
            || state.detailVideosSourceId !== state.selectedSourceId
        )) {
            await loadDetailVideos(state.selectedSourceId, { showLoading: true });
        }
    } catch (error) {
        console.error("Failed to load sources:", error);
    }
}

export async function loadStatus() {
    try {
        const [status, settings] = await Promise.all([
            api("GET", "/api/status"),
            getSettings(true),
        ]);

        setCurrentStatus(status);
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

        const pollInterval = document.getElementById("poll-interval");
        if (document.activeElement !== pollInterval) {
            pollInterval.value = String(settings.poll_interval_minutes);
        }
        const cookiePath = document.getElementById("cookies-file-path");
        if (document.activeElement !== cookiePath) {
            cookiePath.value = settings.cookies_file_path || "";
        }
        document.getElementById("settings-info").textContent =
            `Base URL: ${settings.base_url} • API key: ${settings.youtube_api_key_set ? "set" : "not set"} • Storage: ${settings.storage_path}`;

        renderOverview();
    } catch (error) {
        state.currentStatus = null;
        document.getElementById("server-status").className = "status-dot is-offline";
        document.getElementById("status-text").textContent = "Disconnected";
        document.getElementById("next-poll").textContent = "";
        renderOverview();
    }
}

export async function refreshProgress() {
    if (state.progressRunning) {
        return;
    }
    state.progressRunning = true;

    try {
        const progress = await api("GET", "/api/downloads/progress");
        const currentIds = new Set(Object.keys(progress).map(Number));
        const completedSome = [...state.prevProgressIds].some((id) => !currentIds.has(id));
        const newStarted = [...currentIds].some((id) => !state.prevProgressIds.has(id));
        state.prevProgressIds = currentIds;

        if ((completedSome || newStarted) && state.selectedSourceId) {
            await loadDetailVideos(state.selectedSourceId);
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
        state.progressRunning = false;
    }
}

export async function cancelDownloads() {
    try {
        await api("POST", "/api/downloads/cancel-all");
        toast("Downloads cancelled");
        await loadStatus();
    } catch (error) {
        toast(error.message, "error");
    }
}

export function startPolling() {
    void loadStatus();
    void loadSources();

    state.pollTimer = setInterval(() => {
        if (!document.hidden) {
            void loadStatus();
            void loadSources();
        }
    }, 5000);

    state.progressTimer = setInterval(() => {
        if (!document.hidden) {
            void refreshProgress();
        }
    }, 1000);
}
