import { state, setSettingsCache } from "./store.js";

const API = "";

export async function api(method, path, body) {
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

export function isLocalOrigin() {
    return ["localhost", "127.0.0.1"].includes(window.location.hostname);
}

export async function getSettings(force = false) {
    if (!force && state.settingsCache) {
        return state.settingsCache;
    }

    const settings = await api("GET", "/api/settings");
    setSettingsCache(settings);
    return settings;
}

export async function buildFeedUrl(sourceId) {
    const origin = isLocalOrigin() ? (await getSettings()).base_url : window.location.origin;
    return `${origin}/feed/${sourceId}.xml`;
}
