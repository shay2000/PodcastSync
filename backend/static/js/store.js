export const state = {
    sources: [],
    selectedSourceId: null,
    autoSelectSource: true,
    settingsCache: null,
    currentStatus: null,
    detailVideos: [],
    detailVideosSourceId: null,
    pollTimer: null,
    progressTimer: null,
    prevProgressIds: new Set(),
    progressRunning: false,
    displayNameManuallyEdited: false,
    detailActiveTab: "episodes",
    detailDeleteConfirmVisible: false,
    currentBrowserSelection: "",
};

const subscribers = new Set();

export function subscribe(listener) {
    subscribers.add(listener);
    return () => subscribers.delete(listener);
}

export function notify(metadata = {}) {
    for (const listener of subscribers) {
        listener(metadata);
    }
}

export function updateState(changes, metadata = {}) {
    Object.assign(state, changes);
    notify(metadata);
}

export function getSourceById(id) {
    return state.sources.find((source) => source.id === id) || null;
}

function sourceSignature(sourceList) {
    return JSON.stringify(
        sourceList.map((source) => ({
            id: source.id,
            name: source.name,
            source_type: source.source_type,
            enabled: source.enabled,
            last_polled_at: source.last_polled_at,
            video_count: source.video_count,
            completed_count: source.completed_count,
            custom_storage_path: source.custom_storage_path,
            max_keep_episodes: source.max_keep_episodes,
            icon_url: source.icon_url,
        }))
    );
}

export function hasSourceDataChanged(nextSources, previousSources = state.sources) {
    return sourceSignature(previousSources) !== sourceSignature(nextSources);
}

export function ensureSelectedSource() {
    if (!state.sources.length) {
        state.selectedSourceId = null;
        return;
    }

    const selectionStillExists = state.sources.some((source) => source.id === state.selectedSourceId);
    if (!selectionStillExists) {
        state.selectedSourceId = state.autoSelectSource ? state.sources[0].id : null;
    }
}

export function setSources(sources, metadata = {}) {
    state.sources = sources;
    ensureSelectedSource();
    if (metadata.notify !== false) {
        notify(metadata);
    }
}

export function replaceSource(updatedSource, metadata = { resetInputs: true }) {
    state.sources = state.sources.map((source) => (
        source.id === updatedSource.id ? updatedSource : source
    ));
    notify(metadata);
}

export function setSelectedSource(selectedSourceId, metadata = {}) {
    state.selectedSourceId = selectedSourceId;
    notify(metadata);
}

export function setSettingsCache(settings) {
    state.settingsCache = settings;
}

export function invalidateSettingsCache() {
    state.settingsCache = null;
}

export function setCurrentStatus(currentStatus) {
    state.currentStatus = currentStatus;
    notify({ overviewOnly: true });
}

export function setDetailVideos(detailVideos, sourceId) {
    state.detailVideos = detailVideos;
    state.detailVideosSourceId = sourceId;
}
