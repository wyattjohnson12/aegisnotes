import { endpoints } from "/static/js/api.js";

const userPill    = document.getElementById("user-pill");
const logoutBtn   = document.getElementById("logout-btn");
const fileInput   = document.getElementById("file-input");
const dropzone    = document.getElementById("dropzone");
const dropLabel   = document.getElementById("dropzone-label");
const uploadBtn   = document.getElementById("upload-btn");
const uploadForm  = document.getElementById("upload-form");
const feedback    = document.getElementById("upload-feedback");
const tbody       = document.getElementById("uploads-tbody");
const statusSel   = document.getElementById("status-filter");
const refreshBtn  = document.getElementById("refresh-btn");
const footer      = document.getElementById("footer-status");
const searchForm  = document.getElementById("search-form");
const searchInput = document.getElementById("search-input");
const searchOut   = document.getElementById("search-results");
const tagsCloud   = document.getElementById("tags-cloud");
const tagsRefresh = document.getElementById("tags-refresh-btn");
const fcCount     = document.getElementById("flashcards-count");
const studyBtn    = document.getElementById("study-start-btn");
const studyModal  = document.getElementById("study-modal");
const studyClose  = document.getElementById("study-close");
const studyCard   = document.getElementById("study-card");
const studyFront  = studyCard.querySelector(".study-front");
const studyBack   = studyCard.querySelector(".study-back");
const studyProg   = document.getElementById("study-progress");
const studySrc    = document.getElementById("study-source");
const studyPrev   = document.getElementById("study-prev");
const studyNext   = document.getElementById("study-next");
const studyFlip   = document.getElementById("study-flip");

function fmtBytes(n) {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(2)} MB`;
}
function fmtTime(iso) {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
}
function escapeHtml(s) {
    return (s ?? "").replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}
function chip(label, cls = "chip") {
    return `<span class="${cls}">${escapeHtml(label)}</span>`;
}

// ---------------- Uploads table ----------------
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
    if (!row.hidden) { row.hidden = true; return; }
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
        await renderNoteDetail(cell, res.note);
    } catch (err) {
        cell.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    }
}

async function renderNoteDetail(cell, note) {
    cell.innerHTML = `
        <div class="note-title">
            <strong>${escapeHtml(note.title)}</strong>
            <span class="muted">· ${note.cleaned_text.length} chars · ${escapeHtml(note.language)}</span>
            <button class="link-btn reanalyze-btn" data-note-id="${note.id}">Re-analyze</button>
        </div>
        <div class="intel-grid">
            <div class="intel-block" id="summary-${note.id}">
                <h4>Summary</h4><p class="muted">loading…</p>
            </div>
            <div class="intel-block" id="tags-${note.id}">
                <h4>Tags</h4><p class="muted">loading…</p>
            </div>
            <div class="intel-block" id="topics-${note.id}">
                <h4>Topics</h4><p class="muted">loading…</p>
            </div>
            <div class="intel-block" id="links-${note.id}">
                <h4>Related notes</h4><p class="muted">loading…</p>
            </div>
            <div class="intel-block" id="flashcards-${note.id}">
                <h4>Flashcards</h4><p class="muted">loading…</p>
            </div>
        </div>
        <details class="ocr-toggle">
            <summary>Raw OCR text</summary>
            <pre class="ocr-text">${escapeHtml(note.cleaned_text)}</pre>
        </details>
    `;

    cell.querySelector(".reanalyze-btn").addEventListener("click", async (e) => {
        e.stopPropagation();
        const btn = e.currentTarget;
        btn.disabled = true; btn.textContent = "re-analyzing…";
        try {
            await endpoints.reanalyze(note.id);
            await loadIntelligence(note.id);
        } catch (err) {
            alert("Re-analyze failed: " + err.message);
        } finally {
            btn.disabled = false; btn.textContent = "Re-analyze";
        }
    });

    await loadIntelligence(note.id);
}

async function loadIntelligence(noteId) {
    const [sumRes, tagRes, topRes, linkRes, fcRes] = await Promise.allSettled([
        endpoints.noteSummary(noteId),
        endpoints.noteTags(noteId),
        endpoints.noteTopics(noteId),
        endpoints.noteLinks(noteId),
        endpoints.noteFlashcards(noteId),
    ]);
    renderSummary(noteId, sumRes);
    renderTagsBlock(noteId, tagRes);
    renderTopicsBlock(noteId, topRes);
    renderLinksBlock(noteId, linkRes);
    renderFlashcardsBlock(noteId, fcRes);
}

function renderFlashcardsBlock(noteId, res) {
    const el = document.getElementById(`flashcards-${noteId}`);
    if (!el) return;
    const cards = res.status === "fulfilled" ? (res.value.flashcards || []) : [];
    if (!cards.length) {
        el.innerHTML = `
            <h4>Flashcards</h4>
            <p class="muted">No cards generated.</p>
            <button class="link-btn fc-study" data-note-id="${noteId}" disabled>Study</button>
        `;
        return;
    }
    const preview = cards.slice(0, 3).map((c) => `
        <li>
            <strong>${escapeHtml(c.question)}</strong>
            <span class="muted small">· ${(c.confidence * 100).toFixed(0)}%</span>
        </li>
    `).join("");
    el.innerHTML = `
        <h4>Flashcards <span class="muted small">· ${cards.length}</span></h4>
        <ul class="flashcard-preview">${preview}</ul>
        <button class="link-btn fc-study" data-note-id="${noteId}">Study these</button>
    `;
    el.querySelector(".fc-study").addEventListener("click", (e) => {
        e.stopPropagation();
        startStudy({ noteId, cards });
    });
}

function renderSummary(noteId, res) {
    const el = document.getElementById(`summary-${noteId}`);
    if (!el) return;
    if (res.status !== "fulfilled" || !res.value.summary) {
        el.innerHTML = `<h4>Summary</h4><p class="muted">No summary available.</p>`;
        return;
    }
    el.innerHTML = `<h4>Summary</h4><p>${escapeHtml(res.value.summary.text)}</p>` +
        `<p class="muted small">${escapeHtml(res.value.summary.algorithm)}</p>`;
}

function renderTagsBlock(noteId, res) {
    const el = document.getElementById(`tags-${noteId}`);
    if (!el) return;
    if (res.status !== "fulfilled" || !res.value.tags?.length) {
        el.innerHTML = `<h4>Tags</h4><p class="muted">No tags.</p>`;
        return;
    }
    const chips = res.value.tags.map((t) =>
        `<button class="chip tag-chip" data-tag="${escapeHtml(t.normalized)}">${escapeHtml(t.name)}</button>`
    ).join(" ");
    el.innerHTML = `<h4>Tags</h4><div class="chip-row">${chips}</div>`;
    el.querySelectorAll(".tag-chip").forEach((b) => {
        b.addEventListener("click", (e) => {
            e.stopPropagation();
            runSearch(b.dataset.tag);
        });
    });
}

function renderTopicsBlock(noteId, res) {
    const el = document.getElementById(`topics-${noteId}`);
    if (!el) return;
    if (res.status !== "fulfilled" || !res.value.topics?.length) {
        el.innerHTML = `<h4>Topics</h4><p class="muted">No topics detected.</p>`;
        return;
    }
    const renderNode = (node) => `
        <li>
            <details ${node.level <= 2 ? "open" : ""}>
                <summary>${escapeHtml(node.title)}</summary>
                ${node.content ? `<p>${escapeHtml(node.content)}</p>` : ""}
                ${node.children?.length ? `<ul>${node.children.map(renderNode).join("")}</ul>` : ""}
            </details>
        </li>
    `;
    el.innerHTML = `<h4>Topics</h4><ul class="topic-tree">${res.value.topics.map(renderNode).join("")}</ul>`;
}

function renderLinksBlock(noteId, res) {
    const el = document.getElementById(`links-${noteId}`);
    if (!el) return;
    if (res.status !== "fulfilled" || !res.value.links?.length) {
        el.innerHTML = `<h4>Related notes</h4><p class="muted">No related notes yet.</p>`;
        return;
    }
    const items = res.value.links.map((l) => `
        <li>
            <strong>${escapeHtml(l.title)}</strong>
            <span class="muted small">· ${(l.strength * 100).toFixed(0)}%</span>
            ${l.shared_tags?.length ? `<div class="chip-row tiny">${l.shared_tags.map((t) => chip(t)).join(" ")}</div>` : ""}
        </li>
    `).join("");
    el.innerHTML = `<h4>Related notes</h4><ul class="related-list">${items}</ul>`;
}

// ---------------- Uploads + status polling ----------------
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

// ---------------- Tag cloud ----------------
async function refreshTags() {
    tagsCloud.textContent = "loading…";
    try {
        const res = await endpoints.tags(200);
        if (!res.tags?.length) {
            tagsCloud.textContent = "No tags yet.";
            return;
        }
        tagsCloud.innerHTML = res.tags.map((t) =>
            `<button class="chip tag-chip" data-tag="${escapeHtml(t.normalized)}" title="${t.note_count} notes">
                ${escapeHtml(t.name)} <span class="muted">${t.note_count}</span>
            </button>`
        ).join(" ");
        tagsCloud.querySelectorAll(".tag-chip").forEach((b) => {
            b.addEventListener("click", () => runSearch(b.dataset.tag));
        });
    } catch (err) {
        tagsCloud.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    }
}

// ---------------- Search ----------------
async function runSearch(q) {
    searchInput.value = q;
    searchOut.innerHTML = `<p class="muted">searching…</p>`;
    try {
        const res = await endpoints.search(q);
        if (!res.results?.length) {
            searchOut.innerHTML = `<p class="muted">No matches for "${escapeHtml(q)}".</p>`;
            return;
        }
        searchOut.innerHTML = `<ul class="search-list">${res.results.map((r) => `
            <li>
                <strong>${escapeHtml(r.title)}</strong>
                <span class="muted small">· note #${r.note_id}</span>
                <p>${(r.snippet || "").replace(/\[/g, "<mark>").replace(/\]/g, "</mark>")}</p>
                ${r.tags?.length ? `<div class="chip-row tiny">${r.tags.map((t) => chip(t)).join(" ")}</div>` : ""}
            </li>
        `).join("")}</ul>`;
    } catch (err) {
        searchOut.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
    }
}

// ---------------- Bootstrap ----------------
endpoints.me().then((res) => {
    if (!res?.user) { window.location.replace("/login"); return; }
    userPill.textContent = `${res.user.username} · ${res.user.role}`;
    refreshUploads();
    refreshStatus();
    refreshTags();
    setInterval(refreshUploads, 5000);
    setInterval(refreshStatus, 10000);
}).catch(() => window.location.replace("/login"));

logoutBtn.addEventListener("click", async () => {
    try { await endpoints.logout(); } finally { window.location.replace("/login"); }
});

// ---------------- Dropzone / upload ----------------
function setDropLabel(file) {
    if (!file) { dropLabel.textContent = "Choose file or drop here"; uploadBtn.disabled = true; }
    else { dropLabel.textContent = `${file.name} · ${fmtBytes(file.size)}`; uploadBtn.disabled = false; }
}
fileInput.addEventListener("change", () => setDropLabel(fileInput.files[0]));
["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.add("drag"); })
);
["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); })
);
dropzone.addEventListener("drop", (e) => {
    const f = e.dataTransfer?.files?.[0];
    if (f) {
        const dt = new DataTransfer(); dt.items.add(f); fileInput.files = dt.files; setDropLabel(f);
    }
});
uploadForm.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const f = fileInput.files[0]; if (!f) return;
    uploadBtn.disabled = true; feedback.textContent = "uploading…";
    try {
        const res = await endpoints.uploadFile(f, {
            onProgress: (p) => { feedback.textContent = `uploading… ${(p * 100).toFixed(0)}%`; },
        });
        const up = res.upload;
        feedback.innerHTML = up.duplicated
            ? `Already uploaded earlier — using existing record #${up.id}.`
            : `Uploaded. Queued for processing (id ${up.id}).`;
        fileInput.value = ""; setDropLabel(null); refreshUploads();
    } catch (err) {
        feedback.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
        uploadBtn.disabled = false;
    }
});

statusSel.addEventListener("change", refreshUploads);
refreshBtn.addEventListener("click", refreshUploads);
tagsRefresh.addEventListener("click", refreshTags);
searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = searchInput.value.trim();
    if (q) runSearch(q);
});

// ---------------- Study mode ----------------
let studyDeck = [];
let studyIdx  = 0;
let studyShowingBack = false;

async function refreshFlashcardStats() {
    try {
        const s = await endpoints.flashcardStats();
        fcCount.textContent = `${s.total} cards`;
        studyBtn.disabled = s.total === 0;
    } catch {
        fcCount.textContent = "stats unavailable";
    }
}

async function startStudy({ noteId = null, cards = null } = {}) {
    try {
        if (cards) {
            studyDeck = cards.map((c) => ({
                question: c.question, answer: c.answer,
                note_title: "this note", confidence: c.confidence,
            }));
        } else {
            const res = await endpoints.review({ limit: 25, noteId });
            studyDeck = res.cards || [];
        }
        if (!studyDeck.length) {
            alert("No flashcards available yet.");
            return;
        }
        studyIdx = 0; studyShowingBack = false;
        renderStudy();
        studyModal.hidden = false;
        document.body.classList.add("modal-open");
        studyCard.focus();
    } catch (err) {
        alert("Could not start study session: " + err.message);
    }
}

function renderStudy() {
    if (!studyDeck.length) return;
    const c = studyDeck[studyIdx];
    studyFront.textContent = c.question;
    studyBack.textContent  = c.answer;
    studyFront.hidden = studyShowingBack;
    studyBack.hidden  = !studyShowingBack;
    studyProg.textContent = `${studyIdx + 1} / ${studyDeck.length}`;
    studySrc.textContent = c.note_title
        ? `from "${c.note_title}" · confidence ${(c.confidence * 100).toFixed(0)}%`
        : "";
}

function studyAdvance(delta) {
    studyIdx = (studyIdx + delta + studyDeck.length) % studyDeck.length;
    studyShowingBack = false;
    renderStudy();
}

function closeStudy() {
    studyModal.hidden = true;
    document.body.classList.remove("modal-open");
}

studyBtn.addEventListener("click", () => startStudy());
studyClose.addEventListener("click", closeStudy);
studyNext.addEventListener("click", () => studyAdvance(1));
studyPrev.addEventListener("click", () => studyAdvance(-1));
studyFlip.addEventListener("click", () => { studyShowingBack = !studyShowingBack; renderStudy(); });
studyCard.addEventListener("click", () => { studyShowingBack = !studyShowingBack; renderStudy(); });

document.addEventListener("keydown", (e) => {
    if (studyModal.hidden) return;
    if (e.key === "Escape") { closeStudy(); }
    else if (e.key === " ") { e.preventDefault(); studyShowingBack = !studyShowingBack; renderStudy(); }
    else if (e.key === "ArrowRight") { studyAdvance(1); }
    else if (e.key === "ArrowLeft")  { studyAdvance(-1); }
});

refreshFlashcardStats();
setInterval(refreshFlashcardStats, 15000);
