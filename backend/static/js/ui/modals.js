import { detectBrowserCookies } from "../actions/settings.js";

export function syncModalState() {
    const addModal = document.getElementById("add-modal");
    const settingsModal = document.getElementById("settings-modal");
    document.body.classList.toggle("modal-open", !addModal.hidden || !settingsModal.hidden);
}

export function openAddSource() {
    document.getElementById("add-modal").hidden = false;
    document.getElementById("add-error").hidden = true;
    syncModalState();
    document.getElementById("source-url").focus();
}

export function closeAddSource() {
    document.getElementById("add-modal").hidden = true;
    syncModalState();
}

export function closeAddOnBackdrop(event) {
    if (event.target.id === "add-modal") {
        closeAddSource();
    }
}

export function openSettings() {
    document.getElementById("settings-modal").hidden = false;
    syncModalState();
    void detectBrowserCookies();
}

export function closeSettings() {
    document.getElementById("settings-modal").hidden = true;
    syncModalState();
}

export function closeSettingsOnBackdrop(event) {
    if (event.target.id === "settings-modal") {
        closeSettings();
    }
}
