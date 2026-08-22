import { api, buildFeedUrl } from "../api.js";
import { notify, replaceSource, state, updateState } from "../store.js";
import { toast } from "../ui/toast.js";
import { loadDetailVideos, loadSources, loadStatus } from "../poll.js";

export async function patchSource(sourceId, updates, successMessage) {
    const updatedSource = await api("PATCH", `/api/sources/${sourceId}`, updates);
    replaceSource(updatedSource, { resetInputs: true });

    if (successMessage) {
        toast(successMessage);
    }
    return updatedSource;
}

export function selectSource(sourceId) {
    state.autoSelectSource = true;
    const selectionChanged = state.selectedSourceId !== sourceId;
    state.selectedSourceId = sourceId;
    notify({ resetInputs: selectionChanged });

    if (selectionChanged || state.detailVideosSourceId !== sourceId) {
        void loadDetailVideos(sourceId, { showLoading: true });
    }

    if (window.innerWidth <= 1200) {
        document.getElementById("detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    }
}

export async function syncSource(sourceId) {
    try {
        await api("POST", `/api/sources/${sourceId}/sync`);
        const source = state.sources.find((candidate) => candidate.id === sourceId);
        if (source) {
            source.last_polled_at = new Date().toISOString();
        }
        state.autoSelectSource = true;
        state.selectedSourceId = sourceId;
        notify({ resetInputs: true });
        void loadDetailVideos(sourceId, { showLoading: true });
        void loadStatus();
        void loadSources();
        toast("Sync started");
    } catch (error) {
        toast(error.message, "error");
    }
}

export function syncDetailSource() {
    if (state.selectedSourceId) {
        void syncSource(state.selectedSourceId);
    }
}

export async function copyFeedUrl(sourceId) {
    try {
        const url = await buildFeedUrl(sourceId);
        await navigator.clipboard.writeText(url);

        if (sourceId === state.selectedSourceId) {
            document.getElementById("detail-feed-url").textContent = url;
            document.getElementById("detail-feed-url-row").hidden = false;
        }
        toast("RSS feed copied");
    } catch (error) {
        toast("Failed to copy RSS feed", "error");
    }
}

export function copyDetailFeedUrl() {
    if (state.selectedSourceId) {
        void copyFeedUrl(state.selectedSourceId);
    }
}

export async function toggleEnabled(sourceId, enabled) {
    try {
        await patchSource(sourceId, { enabled }, enabled ? "Source enabled" : "Source paused");
    } catch (error) {
        notify({ resetInputs: true });
        toast(error.message, "error");
    }
}

export async function saveDetailPath() {
    if (!state.selectedSourceId) {
        return;
    }
    const customStoragePath = document.getElementById("detail-path").value.trim() || null;
    try {
        await patchSource(state.selectedSourceId, { custom_storage_path: customStoragePath }, "Download folder saved");
    } catch (error) {
        toast(error.message, "error");
    }
}

export async function saveDetailKeep() {
    if (!state.selectedSourceId) {
        return;
    }
    const raw = document.getElementById("detail-keep").value.trim();
    const maxKeepEpisodes = raw ? parseInt(raw, 10) : null;
    try {
        await patchSource(
            state.selectedSourceId,
            { max_keep_episodes: maxKeepEpisodes },
            maxKeepEpisodes ? `Will keep last ${maxKeepEpisodes} episodes` : "Keep limit removed",
        );
    } catch (error) {
        toast(error.message, "error");
    }
}

export async function saveDetailEnabled() {
    if (!state.selectedSourceId) {
        return;
    }
    const enabled = document.getElementById("detail-enabled").checked;
    try {
        await patchSource(state.selectedSourceId, { enabled }, enabled ? "Source enabled" : "Source paused");
    } catch (error) {
        notify({ resetInputs: true });
        toast(error.message, "error");
    }
}

export async function browseDirectory(inputId) {
    try {
        const result = await api("POST", "/api/pick-directory");
        if (result.path) {
            document.getElementById(inputId).value = result.path;
        }
    } catch (error) {
        toast("Could not open folder picker", "error");
    }
}

export function closeDetail() {
    updateState({
        selectedSourceId: null,
        autoSelectSource: false,
        detailVideos: [],
        detailVideosSourceId: null,
        detailActiveTab: "episodes",
        detailDeleteConfirmVisible: false,
    }, { resetInputs: true });
}

export function openDetailTab(tabName) {
    updateState({
        detailActiveTab: state.detailActiveTab === tabName ? "episodes" : tabName,
    });
}

export function deleteDetailSource() {
    if (state.selectedSourceId) {
        updateState({ detailDeleteConfirmVisible: true });
    }
}

export function cancelDetailDelete() {
    updateState({ detailDeleteConfirmVisible: false });
}

export function confirmDeleteDetailSource() {
    if (state.selectedSourceId) {
        const sourceId = state.selectedSourceId;
        updateState({ detailDeleteConfirmVisible: false });
        void deleteSource(sourceId);
    }
}

export async function deleteSource(sourceId) {
    try {
        await api("DELETE", `/api/sources/${sourceId}`);
        toast("Source deleted");

        if (state.selectedSourceId === sourceId) {
            state.selectedSourceId = null;
            state.detailVideos = [];
            state.detailVideosSourceId = null;
            state.detailActiveTab = "episodes";
            state.detailDeleteConfirmVisible = false;
            notify({ resetInputs: true });
        }

        await loadSources();
        await loadStatus();
    } catch (error) {
        toast(error.message, "error");
    }
}
