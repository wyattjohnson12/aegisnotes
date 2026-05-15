import { endpoints } from "/static/js/api.js";

const userPill   = document.getElementById("user-pill");
const logoutBtn  = document.getElementById("logout-btn");
const fileInput  = document.getElementById("file-input");
const dropzone   = document.getElementById("dropzone");
const dropLabel  = document.getElementById("dropzone-label");
const uploadBtn  = document.getElementById("upload-btn");
const uploadForm = document.getElementById("upload-form");
const feedback   = document.getElementById("upload-feedback");
const tbody      = document.getElementById("uploads-tbody");
const statusSel  = document.getElementById("status-filter");
const refreshBtn = document.getElementById("refresh-btn");
const footer     = document.getElementById("footer-status");

function fmtBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function fmtTime(iso) {
    if (!iso) return "—";
    try {
        const d = new Date(iso);
        return d.toLocaleString();
    } catch { return iso; }
}

function renderUploads(list) {
    if (!list.length) {
        tbody.innerHTML = `<tr><td colspan="5" class="muted">No uploads yet.</td></tr>`;
        return;
    }
    tbody.innerHTML = list.map((u) => `
        <tr data-upload-id="${u.id}" class="upload-row clickable">
            <td>${fmtTime(u.uploaded_at)}</td>
            <td>${escapeHtml(u.original_name)}</td>
            <td class="muted">${escapeHtml(u.mime_type)}</td>
            <td>${fmtBytes(u.size_bytes)}</td>
            <td class="status-${u.status}">${u.status}</td>
        </tr>
        <tr class="upload-detail" id="detail-${u.id}" hidden>
            <td colspan="5" class="detail-cell muted">click to load…</td>
        </tr>
    `).join("");

    tbody.querySelectorAll(".upload-row").forEach((row) => {
        row.addEventListener("click", () => toggleDetail(row.dataset.uploadId));
    });
}

async function toggleDetail(uploadId) {
    const row = document.getElementById(`detail-${uploadId}`);
    if (!row) return;
    if (!row.hidden) {
        row.hidden = true;
        return;
    }
    row.hidden = false;
    const cell = row.querySelector(".detail-cell");
    cell.textContent = "loading…";
    try {
        const res = await endpoints.noteByUpload(uploadId);
        if (res.upload_status === "failed") {
            cell.innerHTML = `<span class="error">processing failed:</span> ` +
                `<code>${escapeHtml(res.upload_error || "no error detail")}</code>`;
            return;
        }
        if (!res.note) {
            cell.innerHTML = `<span class="muted">status: ${escapeHtml(res.upload_status)} — OCR not finished yet.</span>`;
            return;
        }
        const n = res.note;
        cell.innerHTML = `
            <div class="note-title"><strong>${escapeHtml(n.title)}</strong>
                <span class="muted">· ${n.cleaned_text.length} chars · ${escapeHtml(n.language)}</span></div>
            <pre class="ocr-text">${escapeHtml(n.cleaned_text)}</pre>
        `;
    } catch (err) {
        cell.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    }
}

function escapeHtml(s) {
    return (s ?? "").replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

async function refreshUploads() {
    const status = statusSel.value || null;
    try {
        const res = await endpoints.listUploads(status);
        renderUploads(res.uploads || []);
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="5" class="error">${escapeHtml(err.message)}</td></tr>`;
    }
}

async function refreshStatus() {
    try {
        const s = await endpoints.status();
        footer.textContent = `v${s.version} · ${s.pending_uploads} pending · ` +
            `${s.processing_uploads} processing · last processed ${fmtTime(s.last_processed_at)}`;
    } catch (err) {
        footer.textContent = "status unavailable";
    }
}

// ---------------- Bootstrap ----------------
endpoints.me().then((res) => {
    if (!res?.user) {
        window.location.replace("/login");
        return;
    }
    userPill.textContent = `${res.user.username} · ${res.user.role}`;
    refreshUploads();
    refreshStatus();
    // Poll every 5s until Phase 6's SSE lands.
    setInterval(refreshUploads, 5000);
    setInterval(refreshStatus, 10000);
}).catch(() => window.location.replace("/login"));

logoutBtn.addEventListener("click", async () => {
    try { await endpoints.logout(); } finally { window.location.replace("/login"); }
});

// ---------------- Dropzone / upload ----------------
function setDropLabel(file) {
    if (!file) {
        dropLabel.textContent = "Choose file or drop here";
        uploadBtn.disabled = true;
    } else {
        dropLabel.textContent = `${file.name} · ${fmtBytes(file.size)}`;
        uploadBtn.disabled = false;
    }
}

fileInput.addEventListener("change", () => setDropLabel(fileInput.files[0]));

["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.add("drag");
    })
);
["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.remove("drag");
    })
);
dropzone.addEventListener("drop", (e) => {
    const f = e.dataTransfer?.files?.[0];
    if (f) {
        const dt = new DataTransfer();
        dt.items.add(f);
        fileInput.files = dt.files;
        setDropLabel(f);
    }
});

uploadForm.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const f = fileInput.files[0];
    if (!f) return;

    uploadBtn.disabled = true;
    feedback.textContent = "uploading…";
    try {
        const res = await endpoints.uploadFile(f, {
            onProgress: (p) => {
                feedback.textContent = `uploading… ${(p * 100).toFixed(0)}%`;
            },
        });
        const up = res.upload;
        feedback.innerHTML = up.duplicated
            ? `Already uploaded earlier — using existing record #${up.id}.`
            : `Uploaded. Queued for processing (id ${up.id}).`;
        fileInput.value = "";
        setDropLabel(null);
        refreshUploads();
    } catch (err) {
        feedback.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
        uploadBtn.disabled = false;
    }
});

statusSel.addEventListener("change", refreshUploads);
refreshBtn.addEventListener("click", refreshUploads);
