import { api, getSettings } from "../api.js";
import { invalidateSettingsCache, state } from "../store.js";
import { toast } from "../ui/toast.js";

export const BROWSER_LABELS = {
    chrome: "Chrome", chromium: "Chromium", brave: "Brave",
    edge: "Edge", opera: "Opera", vivaldi: "Vivaldi",
    safari: "Safari", firefox: "Firefox",
};

export async function detectBrowserCookies() {
    const list = document.getElementById("browser-detect-list");
    if (!list) return;
    list.innerHTML = `<div class="browser-list-placeholder">Detecting browsers…</div>`;

    let data;
    try {
        data = await api("GET", "/api/cookies/detect");
    } catch {
        list.innerHTML = `<div class="browser-list-placeholder">Detection failed — check server logs.</div>`;
        return;
    }

    const settings = await getSettings();
    state.currentBrowserSelection = settings.cookies_from_browser || "";
    const rows = data.browsers.filter((browser) => browser.available).map((browser) => {
        let chipClass;
        let chipText;
        if (browser.needs_permission) {
            chipClass = "chip-needs-permission";
            chipText = "Needs permission";
        } else if (browser.has_youtube_cookies) {
            chipClass = "chip-ready";
            chipText = "Cookies ready";
        } else {
            chipClass = "chip-no-cookies";
            chipText = "Not logged in";
        }
        const selected = browser.name === state.currentBrowserSelection;
        return `
            <div class="browser-row${selected ? " is-selected" : ""}"
                 id="browser-row-${browser.name}"
                 data-action="select-cookie-browser"
                 data-browser="${browser.name}">
                <div class="browser-row-radio"></div>
                <span class="browser-name">${BROWSER_LABELS[browser.name] || browser.name}</span>
                <span class="browser-chip ${chipClass}">${chipText}</span>
                ${browser.needs_permission ? `<span title="Grant Full Disk Access in System Settings → Privacy & Security">ⓘ</span>` : ""}
            </div>`;
    });

    const noneSelected = !state.currentBrowserSelection;
    list.innerHTML = `
        <div class="browser-row${noneSelected ? " is-selected" : ""}"
             id="browser-row-none"
             data-action="select-cookie-browser"
             data-browser="">
            <div class="browser-row-radio"></div>
            <span class="browser-name">None</span>
            <span class="browser-chip chip-not-found">Disabled</span>
        </div>
        ${rows.join("")}
    `;

    if (rows.length === 0 && data.browsers.every((browser) => !browser.available)) {
        list.innerHTML += `<div class="browser-list-placeholder" style="margin-top:0.35rem">No supported browsers found — use the Advanced option below.</div>`;
    }
}

export async function selectCookieBrowser(browser) {
    state.currentBrowserSelection = browser;
    document.querySelectorAll(".browser-row").forEach((row) => row.classList.remove("is-selected"));
    const targetRow = document.getElementById(`browser-row-${browser || "none"}`);
    if (targetRow) targetRow.classList.add("is-selected");

    try {
        await api("PATCH", "/api/settings", { cookies_from_browser: browser });
        invalidateSettingsCache();
        if (browser) {
            await testCookies(browser);
        } else {
            clearTestResult();
        }
    } catch (error) {
        toast(error.message, "error");
    }
}

export function clearTestResult() {
    const element = document.getElementById("test-cookies-result");
    if (!element) return;
    element.hidden = true;
    element.textContent = "";
    element.className = "test-cookies-result";
}

export async function testCookies(browser) {
    const button = document.getElementById("test-cookies-btn");
    const result = document.getElementById("test-cookies-result");
    if (!result) return;

    result.hidden = false;
    result.className = "test-cookies-result";
    result.textContent = "Testing…";
    if (button) button.disabled = true;
    const globalChip = document.getElementById("auth-global-status");

    try {
        const data = await api("POST", "/api/cookies/test", browser ? { browser } : {});
        if (data.status === "ok") {
            result.className = "test-cookies-result is-ok";
            result.textContent = "✓ Working";
            if (globalChip) {
                globalChip.hidden = false;
                globalChip.className = "auth-global-chip is-ok";
                globalChip.textContent = "Signed in";
            }
        } else {
            result.className = "test-cookies-result is-err";
            result.textContent = `✗ ${data.message || "Failed"}`;
            if (globalChip) {
                globalChip.hidden = false;
                globalChip.className = "auth-global-chip is-err";
                globalChip.textContent = "Not working";
            }
        }
    } catch (error) {
        result.className = "test-cookies-result is-err";
        result.textContent = `✗ ${error.message}`;
    } finally {
        if (button) button.disabled = false;
    }
}

export async function saveApiKey() {
    const key = document.getElementById("api-key").value.trim();
    try {
        await api("PATCH", "/api/settings", { youtube_api_key: key });
        document.getElementById("api-key").value = "";
        toast("API key saved");
        await getSettings(true);
    } catch (error) {
        toast(error.message, "error");
    }
}

export async function savePollInterval() {
    const interval = parseInt(document.getElementById("poll-interval").value, 10);
    try {
        await api("PATCH", "/api/settings", { poll_interval_minutes: interval });
        toast("Sync interval updated");
        await getSettings(true);
    } catch (error) {
        toast(error.message, "error");
    }
}

export async function saveCookiesFile() {
    const filePath = document.getElementById("cookies-file-path").value.trim();
    try {
        await api("PATCH", "/api/settings", { cookies_file_path: filePath });
        toast(filePath ? "Cookie file path saved" : "Cookie file path cleared");
        invalidateSettingsCache();
    } catch (error) {
        toast(error.message, "error");
    }
}
