import { api } from "../api.js";
import { state } from "../store.js";
import { toast } from "../ui/toast.js";
import { loadDetailVideos, loadSources } from "../poll.js";

export async function skipVideo(sourceId, videoId) {
    try {
        await api("DELETE", `/api/sources/${sourceId}/videos/${videoId}`);
        toast("Episode skipped");
        await loadDetailVideos(sourceId);
        await loadSources();
    } catch (error) {
        toast(error.message, "error");
    }
}

export async function deleteVideoFile(sourceId, videoId) {
    if (!confirm("Delete the downloaded file? It will not be re-downloaded automatically.")) {
        return;
    }

    try {
        await api("DELETE", `/api/sources/${sourceId}/videos/${videoId}/file`);
        toast("Downloaded file removed");
        await loadDetailVideos(sourceId);
        await loadSources();
    } catch (error) {
        toast(error.message, "error");
    }
}

export async function requeueVideo(sourceId, videoId) {
    try {
        await api("POST", `/api/sources/${sourceId}/videos/${videoId}/requeue`);
        toast("Episode queued for download");
        await loadDetailVideos(sourceId);
        await loadSources();
    } catch (error) {
        toast(error.message, "error");
    }
}
