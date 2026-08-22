import { buildFeedUrl } from "../api.js";
import { formatDate, formatNumber, timeAgo } from "../format.js";
import { state, getSourceById } from "../store.js";
import { renderSourceArtMarkup, sourceKindLabel, sourceStateLabel } from "./sources.js";

function safeSetInputValue(id, value, force = false) {
    const input = document.getElementById(id);
    if (!input) {
        return;
    }
    if (force || document.activeElement !== input) {
        input.value = value;
    }
}

export function syncDetailTabUi() {
    const episodesView = document.getElementById("detail-episodes-view");
    const settingsView = document.getElementById("detail-settings-view");
    const settingsButton = document.getElementById("detail-settings-btn");
    const deleteConfirm = document.getElementById("detail-delete-confirm");

    if (episodesView) {
        episodesView.hidden = state.detailActiveTab !== "episodes";
    }
    if (settingsView) {
        settingsView.hidden = state.detailActiveTab !== "settings";
    }
    if (settingsButton) {
        settingsButton.textContent = state.detailActiveTab === "settings" ? "Back" : "Settings";
    }
    if (deleteConfirm) {
        deleteConfirm.hidden = !state.detailDeleteConfirmVisible;
    }
}

export async function updateDetailFeedUrl(sourceId) {
    const row = document.getElementById("detail-feed-url-row");
    const text = document.getElementById("detail-feed-url");

    if (!sourceId) {
        row.hidden = true;
        text.textContent = "";
        return;
    }

    try {
        const url = await buildFeedUrl(sourceId);
        if (state.selectedSourceId !== sourceId) {
            return;
        }
        text.textContent = url;
        row.hidden = false;
    } catch (error) {
        row.hidden = true;
    }
}

export function renderDetail({ resetInputs = false } = {}) {
    const panel = document.getElementById("detail-panel");
    const source = getSourceById(state.selectedSourceId);

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

    safeSetInputValue("detail-path", source.custom_storage_path || "", resetInputs);
    safeSetInputValue("detail-keep", source.max_keep_episodes ? String(source.max_keep_episodes) : "", resetInputs);

    const enabledInput = document.getElementById("detail-enabled");
    if (resetInputs || document.activeElement !== enabledInput) {
        enabledInput.checked = !!source.enabled;
    }
    document.getElementById("detail-enabled-text").textContent = source.enabled ? "Enabled" : "Paused";
    document.getElementById("detail-episode-summary").textContent =
        `${formatNumber(source.video_count)} tracked • ${formatNumber(source.completed_count)} ready`;

    void updateDetailFeedUrl(source.id);
}
