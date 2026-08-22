export function esc(value) {
    const element = document.createElement("span");
    element.textContent = value || "";
    return element.innerHTML;
}

export function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value) || 0);
}

export function formatFileSize(bytes) {
    if (!bytes) {
        return "";
    }
    return `${(bytes / 1048576).toFixed(1)} MB`;
}

export function parseAppDate(value) {
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
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(raw)) {
        return new Date(raw.replace(" ", "T") + "Z");
    }
    return new Date(raw);
}

export function timeAgo(isoString) {
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

export function formatSyncAge(isoString) {
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

export function formatDate(isoString) {
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

export function deriveDisplayNameFromUrl(rawUrl) {
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

export function normalizeDownloadStatus(status) {
    const normalized = String(status || "").toLowerCase();
    if (normalized === "finish" || normalized === "finished" || normalized === "complete") {
        return "completed";
    }
    if (normalized === "downloading" || normalized === "in_progress" || normalized === "in-progress") {
        return "downloading";
    }
    return normalized || "pending";
}
