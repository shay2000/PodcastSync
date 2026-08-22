import { state } from "../store.js";
import { esc, formatNumber, formatSyncAge, timeAgo } from "../format.js";

export const SOURCE_PALETTES = [
    { accent: "#244983", soft: "rgba(36, 73, 131, 0.15)", glow: "rgba(36, 73, 131, 0.24)" },
    { accent: "#c76346", soft: "rgba(199, 99, 70, 0.16)", glow: "rgba(199, 99, 70, 0.24)" },
    { accent: "#1d8d86", soft: "rgba(29, 141, 134, 0.15)", glow: "rgba(29, 141, 134, 0.24)" },
    { accent: "#8c5bb6", soft: "rgba(140, 91, 182, 0.16)", glow: "rgba(140, 91, 182, 0.24)" },
    { accent: "#d58c2d", soft: "rgba(213, 140, 45, 0.16)", glow: "rgba(213, 140, 45, 0.24)" },
    { accent: "#2b7a78", soft: "rgba(43, 122, 120, 0.16)", glow: "rgba(43, 122, 120, 0.24)" },
];

export function getPalette(source) {
    const offset = source.source_type === "playlist" ? 2 : 0;
    return SOURCE_PALETTES[(source.id + offset) % SOURCE_PALETTES.length];
}

export function sourceKindLabel(sourceType) {
    return sourceType === "playlist" ? "Playlist" : "Channel";
}

export function sourceStateLabel(enabled) {
    return enabled ? "Active" : "Paused";
}

export function buildSourceSummary(source) {
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

export function renderSourceArtMarkup(source, className = "source-art") {
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

export function renderOverview() {
    const totalShows = state.sources.length;
    const totalDownloaded = state.sources.reduce(
        (sum, source) => sum + (source.completed_count || 0),
        0,
    );
    const activeOrQueued = (state.currentStatus?.active_downloads || 0)
        + (state.currentStatus?.download_queue_size || 0);
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
    } else if (state.currentStatus?.next_poll) {
        const nextPoll = new Date(state.currentStatus.next_poll);
        const mins = Math.max(0, Math.round((nextPoll.getTime() - Date.now()) / 60000));
        summaryParts.push(`Next sync in ${mins}m`);
    } else {
        summaryParts.push("Library idle");
    }
    subtitle.textContent = summaryParts.join(" • ");
}

export function renderSourceGrid() {
    const grid = document.getElementById("sources-grid");
    const empty = document.getElementById("no-sources");

    if (!state.sources.length) {
        grid.innerHTML = "";
        empty.hidden = false;
        return;
    }

    empty.hidden = true;
    grid.innerHTML = state.sources.map((source) => {
        const palette = getPalette(source);
        const stateClass = source.enabled ? "is-active" : "is-paused";
        const selectedClass = source.id === state.selectedSourceId ? "is-selected" : "";

        return `
            <article
                class="source-tile ${selectedClass}"
                data-action="select-source"
                data-source-id="${source.id}"
                tabindex="0"
                style="--tile-accent:${palette.accent};--tile-soft:${palette.soft};--tile-glow:${palette.glow};"
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
                    <button type="button" class="btn-ghost-sm" data-action="sync-source" data-source-id="${source.id}">Sync</button>
                    <button type="button" class="btn-ghost-sm" data-action="copy-feed-url" data-source-id="${source.id}">RSS</button>
                    <label class="mini-toggle" data-action="ignore-tile" data-source-id="${source.id}">
                        <input
                            type="checkbox"
                            data-action="toggle-enabled"
                            data-source-id="${source.id}"
                            ${source.enabled ? "checked" : ""}
                        >
                        <span>${source.enabled ? "Enabled" : "Paused"}</span>
                    </label>
                </div>
            </article>
        `;
    }).join("");
}
