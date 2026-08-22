import { state } from "../store.js";
import { esc, formatDate, formatFileSize, normalizeDownloadStatus } from "../format.js";

export function showEpisodeLoading() {
    const container = document.getElementById("detail-videos");
    container.innerHTML = `
        <div class="episode-loading">Loading latest episodes...</div>
        <div class="episode-loading">Loading latest episodes...</div>
        <div class="episode-loading">Loading latest episodes...</div>
    `;
}

export function renderDetailVideos(videos) {
    const container = document.getElementById("detail-videos");

    if (!videos.length) {
        container.innerHTML = `
            <div class="episode-empty">
                No episodes have been discovered for this source yet. Run a sync to fetch the latest uploads.
            </div>
        `;
        return;
    }

    container.innerHTML = videos.map((video) => {
        const displayStatus = normalizeDownloadStatus(video.download_status);
        const sizeText = formatFileSize(video.file_size);
        const skipButton = !["completed", "skipped", "deleted", "downloading"].includes(displayStatus)
            ? `<button type="button" class="btn-ghost-sm" data-action="skip-video" data-source-id="${state.selectedSourceId}" data-video-id="${video.id}">Skip</button>`
            : "";
        const deleteButton = displayStatus === "completed"
            ? `<button type="button" class="btn-danger-sm" data-action="delete-video-file" data-source-id="${state.selectedSourceId}" data-video-id="${video.id}">Delete File</button>`
            : "";
        const requeueButton = ["deleted", "failed"].includes(displayStatus)
            ? `<button type="button" class="btn-ghost-sm" data-action="requeue-video" data-source-id="${state.selectedSourceId}" data-video-id="${video.id}">Re-download</button>`
            : "";
        const progressMarkup = displayStatus === "downloading"
            ? `
                <div class="download-progress-bar" id="progress-bar-${video.id}">
                    <div class="progress-fill"></div>
                </div>
                <div class="progress-info-text" id="progress-info-${video.id}">Downloading...</div>
            `
            : "";

        let errorMarkup = "";
        if (video.error_message) {
            if (video.error_message.startsWith("[AUTH_REQUIRED]")) {
                errorMarkup = `<div class="error-auth-required">
                    ⚠ YouTube requires sign-in —
                    <a href="#" data-action="open-settings">configure cookies in Settings</a>
                </div>`;
            } else {
                errorMarkup = `<div class="progress-info-text">${esc(video.error_message)}</div>`;
            }
        }

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
    }).join("");
}
