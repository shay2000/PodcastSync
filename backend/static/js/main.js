import { deriveDisplayNameFromUrl } from "./format.js";
import {
    cancelDownloads,
    loadSources,
    loadStatus,
    startPolling,
} from "./poll.js";
import { renderDetail } from "./render/detail.js";
import { renderOverview, renderSourceGrid } from "./render/sources.js";
import {
    ensureSelectedSource,
    state,
    subscribe,
} from "./store.js";
import {
    browseDirectory,
    cancelDetailDelete,
    closeDetail,
    confirmDeleteDetailSource,
    copyDetailFeedUrl,
    copyFeedUrl,
    deleteDetailSource,
    openDetailTab,
    saveDetailEnabled,
    saveDetailKeep,
    selectSource,
    saveDetailPath,
    syncDetailSource,
    syncSource,
    toggleEnabled,
} from "./actions/sources.js";
import { deleteVideoFile, requeueVideo, skipVideo } from "./actions/videos.js";
import {
    clearTestResult,
    detectBrowserCookies,
    saveApiKey,
    saveCookiesFile,
    savePollInterval,
    selectCookieBrowser,
    testCookies,
} from "./actions/settings.js";
import {
    closeAddOnBackdrop,
    closeAddSource,
    closeSettings,
    closeSettingsOnBackdrop,
    openAddSource,
    openSettings,
} from "./ui/modals.js";
import { toast } from "./ui/toast.js";

function renderAll({ resetInputs = false } = {}) {
    ensureSelectedSource();
    renderOverview();
    renderSourceGrid();
    renderDetail({ resetInputs });
}

subscribe((metadata = {}) => {
    ensureSelectedSource();
    renderOverview();
    if (!metadata.overviewOnly) {
        renderSourceGrid();
        renderDetail({ resetInputs: metadata.resetInputs });
    }
});

function actionTarget(event) {
    return event.target.closest("[data-action]");
}

document.addEventListener("click", (event) => {
    const target = actionTarget(event);
    if (!target) {
        return;
    }

    const action = target.dataset.action;
    const sourceId = target.dataset.sourceId ? Number(target.dataset.sourceId) : null;
    const videoId = target.dataset.videoId ? Number(target.dataset.videoId) : null;

    switch (action) {
        case "select-source":
            selectSource(sourceId);
            break;
        case "sync-source":
            event.stopPropagation();
            void syncSource(sourceId);
            break;
        case "copy-feed-url":
            event.stopPropagation();
            void copyFeedUrl(sourceId);
            break;
        case "ignore-tile":
        case "toggle-enabled":
            event.stopPropagation();
            break;
        case "open-add-source":
            openAddSource();
            break;
        case "close-add-source":
            closeAddSource();
            break;
        case "close-add-backdrop":
            closeAddOnBackdrop(event);
            break;
        case "open-settings":
            event.preventDefault();
            openSettings();
            break;
        case "close-settings":
            closeSettings();
            break;
        case "close-settings-backdrop":
            closeSettingsOnBackdrop(event);
            break;
        case "cancel-downloads":
            void cancelDownloads();
            break;
        case "sync-detail-source":
            void syncDetailSource();
            break;
        case "copy-detail-feed-url":
            copyDetailFeedUrl();
            break;
        case "open-detail-tab":
            openDetailTab(target.dataset.tab);
            break;
        case "delete-detail-source":
            deleteDetailSource();
            break;
        case "close-detail":
            closeDetail();
            break;
        case "cancel-detail-delete":
            cancelDetailDelete();
            break;
        case "confirm-delete-detail-source":
            confirmDeleteDetailSource();
            break;
        case "browse-directory":
            void browseDirectory(target.dataset.inputId);
            break;
        case "save-detail-path":
            void saveDetailPath();
            break;
        case "save-detail-keep":
            void saveDetailKeep();
            break;
        case "skip-video":
            void skipVideo(sourceId, videoId);
            break;
        case "delete-video-file":
            void deleteVideoFile(sourceId, videoId);
            break;
        case "requeue-video":
            void requeueVideo(sourceId, videoId);
            break;
        case "select-cookie-browser":
            void selectCookieBrowser(target.dataset.browser || "");
            break;
        case "test-cookies":
            void testCookies(state.currentBrowserSelection || undefined);
            break;
        case "refresh-detect":
            clearTestResult();
            void detectBrowserCookies();
            break;
        case "save-api-key":
            void saveApiKey();
            break;
        case "save-poll-interval":
            void savePollInterval();
            break;
        case "save-cookies-file":
            void saveCookiesFile();
            break;
        default:
            break;
    }
});

document.addEventListener("change", (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) {
        return;
    }
    const sourceId = target.dataset.sourceId ? Number(target.dataset.sourceId) : null;
    if (target.dataset.action === "toggle-enabled") {
        void toggleEnabled(sourceId, target.checked);
    } else if (target.dataset.action === "save-detail-enabled") {
        void saveDetailEnabled();
    }
});

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
        const createdSource = await (await import("./api.js")).api("POST", "/api/sources", {
            url,
            name,
            max_backfill: maxBackfill,
            custom_storage_path: customStoragePath,
            max_keep_episodes: maxKeepEpisodes,
        });

        document.getElementById("add-source-form").reset();
        document.getElementById("source-backfill").value = "15";
        state.displayNameManuallyEdited = false;
        state.selectedSourceId = createdSource.id;
        state.autoSelectSource = true;
        state.detailVideos = [];
        state.detailVideosSourceId = null;
        closeAddSource();
        toast("Source added");
        await loadSources();
        await loadStatus();
    } catch (error) {
        errorElement.textContent = error.message;
        errorElement.hidden = false;
    }
});

document.getElementById("source-url").addEventListener("input", (event) => {
    if (state.displayNameManuallyEdited) {
        return;
    }
    document.getElementById("source-name").value = deriveDisplayNameFromUrl(event.target.value);
});

document.getElementById("source-name").addEventListener("input", (event) => {
    const currentValue = event.target.value.trim();
    const suggestedName = deriveDisplayNameFromUrl(document.getElementById("source-url").value);
    state.displayNameManuallyEdited = currentValue !== "" && currentValue !== suggestedName;
});

document.getElementById("sync-all-btn").addEventListener("click", async () => {
    try {
        const { api } = await import("./api.js");
        await api("POST", "/api/sync-all");
        toast("Sync started for all sources");
        await loadStatus();
        await loadSources();
    } catch (error) {
        toast(error.message, "error");
    }
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        const tile = event.target.closest('[data-action="select-source"]');
        if (tile && event.target === tile) {
            event.preventDefault();
            selectSource(Number(tile.dataset.sourceId));
            return;
        }
    }

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
    if (window.innerWidth <= 1200 && state.selectedSourceId) {
        closeDetail();
    }
});

document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
        void loadStatus();
        void loadSources();
    }
});

renderAll({ resetInputs: true });
startPolling();
