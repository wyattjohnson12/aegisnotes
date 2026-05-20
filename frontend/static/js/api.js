// AegisNotes — same-origin API client.
//
// All requests carry `X-Requested-With: fetch` which the server requires
// for state-changing endpoints (CSRF defence). Responses are parsed as
// JSON unless explicitly multipart.

const JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Requested-With": "fetch",
};

async function parse(response) {
    const text = await response.text();
    let payload = null;
    if (text) {
        try {
            payload = JSON.parse(text);
        } catch (_) {
            payload = { raw: text };
        }
    }
    if (!response.ok) {
        const message = payload?.error?.message
            || payload?.error?.detail
            || payload?.detail
            || `HTTP ${response.status}`;
        const err = new Error(message);
        err.status = response.status;
        err.payload = payload;
        throw err;
    }
    return payload;
}

export const api = {
    async getJson(path) {
        const res = await fetch(path, {
            method: "GET",
            credentials: "same-origin",
            headers: { "Accept": "application/json", "X-Requested-With": "fetch" },
        });
        return parse(res);
    },

    async postJson(path, body) {
        const res = await fetch(path, {
            method: "POST",
            credentials: "same-origin",
            headers: JSON_HEADERS,
            body: JSON.stringify(body ?? {}),
        });
        return parse(res);
    },

    async postForm(path, formData, { onProgress } = {}) {
        // We use XHR rather than fetch so we can surface progress.
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open("POST", path, true);
            xhr.withCredentials = true;
            xhr.setRequestHeader("X-Requested-With", "fetch");
            xhr.setRequestHeader("Accept", "application/json");

            xhr.upload.onprogress = (evt) => {
                if (onProgress && evt.lengthComputable) {
                    onProgress(evt.loaded / evt.total);
                }
            };
            xhr.onerror = () => reject(new Error("network error"));
            xhr.onload = () => {
                let payload = null;
                try { payload = JSON.parse(xhr.responseText || "null"); }
                catch (_) { payload = { raw: xhr.responseText }; }
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(payload);
                } else {
                    const message = payload?.error?.message
                        || payload?.error?.detail
                        || `HTTP ${xhr.status}`;
                    const err = new Error(message);
                    err.status = xhr.status;
                    err.payload = payload;
                    reject(err);
                }
            };
            xhr.send(formData);
        });
    },
};

export const endpoints = {
    me:           () => api.getJson("/api/auth/me"),
    login:        (username, password) =>
                    api.postJson("/api/auth/login", { username, password }),
    logout:       () => api.postJson("/api/auth/logout", {}),
    uploadFile:   (file, opts) => {
                    const fd = new FormData();
                    fd.append("file", file, file.name);
                    return api.postForm("/api/uploads", fd, opts);
                  },
    listUploads:  (status) => {
                    const qs = status ? `?status_filter=${encodeURIComponent(status)}` : "";
                    return api.getJson(`/api/uploads${qs}`);
                  },
    status:       () => api.getJson("/api/system/status"),
    notes:        () => api.getJson("/api/notes"),
    note:         (id) => api.getJson(`/api/notes/${id}`),
    noteByUpload: (uploadId) => api.getJson(`/api/notes/by-upload/${uploadId}`),
    noteTopics:   (id) => api.getJson(`/api/notes/${id}/topics`),
    noteSummary:  (id) => api.getJson(`/api/notes/${id}/summary`),
    noteTags:     (id) => api.getJson(`/api/notes/${id}/tags`),
    noteLinks:    (id) => api.getJson(`/api/notes/${id}/links`),
    noteFlashcards: (id) => api.getJson(`/api/notes/${id}/flashcards`),
    reanalyze:    (id) => api.postJson(`/api/notes/${id}/reanalyze`, {}),
    regenerateFlashcards:
                  (id) => api.postJson(`/api/notes/${id}/regenerate-flashcards`, {}),
    tags:         (limit = 200) => api.getJson(`/api/tags?limit=${limit}`),
    notesForTag:  (name) => api.getJson(`/api/tags/${encodeURIComponent(name)}/notes`),
    search:       (q, limit = 50) =>
                    api.getJson(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
    review:       ({ limit = 20, noteId, course } = {}) => {
                    const params = new URLSearchParams({ limit });
                    if (noteId)  params.set("note_id", noteId);
                    if (course)  params.set("course", course);
                    return api.getJson(`/api/flashcards/review?${params}`);
                  },
    flashcardStats: () => api.getJson("/api/flashcards/stats"),
    categories:   (limit = 200) => api.getJson(`/api/categories?limit=${limit}`),
    notesForCategory:
                  (name) => api.getJson(`/api/categories/${encodeURIComponent(name)}/notes`),
    noteCategories:
                  (id) => api.getJson(`/api/notes/${id}/categories`),
    recomputeCategories:
                  () => api.postJson("/api/categories/recompute", {}),
};
