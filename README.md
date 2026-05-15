# AegisNotes

A fully self-hosted intelligent note ingestion and knowledge structuring
system designed to run on a Raspberry Pi 5 (8 GB). Snap a photo of your
notes from your phone, upload them to the Pi over your local network, and
let the system OCR, structure, tag, summarise, and link them — all
locally, with zero external APIs and no cloud calls.

## Highlights

- **Local-first.** Every piece of the runtime is on the Pi. The dashboard
  works on an air-gapped network.
- **Deterministic intelligence.** TF-IDF tagging, cosine-similarity
  categorisation, extractive summarisation, and rule-based flashcard
  generation. No model downloads, no GPUs.
- **Modular by layer.** Upload, OCR, intelligence, database, API,
  watcher, and frontend are independent and individually testable.
- **Secure by default.** Argon2id-hashed passwords, `SameSite=Strict`
  session cookies, magic-byte MIME sniffing, path-traversal guards,
  rotating logs, and a systemd hardening profile.
- **Pi-aware.** WAL-mode SQLite, bounded queues, sized worker pools,
  memory caps in the systemd unit.

## Quick Start (Raspberry Pi)

```bash
# 1. Clone the repo to the Pi
git clone <your-fork-url> AegisNotes
cd AegisNotes

# 2. One-shot setup: installs apt deps, builds venv, writes .env, creates DB,
#    and prompts for the first admin account.
bash scripts/setup_pi.sh

# 3. Start the dev server (port 8000 by default)
bash scripts/run_dev.sh

# 4. Open from another device on your LAN
#    http://raspberrypi.local:8000   (or use the Pi's IP)
```

To run as a service:

```bash
sudo cp scripts/aegisnotes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aegisnotes
journalctl -u aegisnotes -f
```

## Manual / Cross-platform Install

If you'd rather not use `setup_pi.sh` (e.g. for development on a Mac):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# paste the result as AEGIS_SECRET_KEY in .env

python scripts/init_db.py
python scripts/create_user.py admin --admin

uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

System packages you'll want on Debian/Raspberry Pi OS:

```
sudo apt-get install libmagic1 tesseract-ocr poppler-utils
```

`libmagic` and `tesseract` are referenced by future phases but `setup_pi.sh`
installs them up front so the Phase 1 image is ready to grow.

## Phase 1 Smoke Test

After `bash scripts/run_dev.sh` succeeds:

1. Open `http://<pi-ip>:8000/`. You should see the login page.
2. Sign in with the admin account created during setup.
3. The dashboard loads with three sections: **Upload**, **Recent
   uploads**, and **Notes**.
4. Drop a JPEG/PNG/PDF into the dropzone and click **Upload**.
5. The file should appear in **Recent uploads** with status `pending`,
   then move to `processed` once Phase 2 lands.
6. The status pill in the footer should read something like
   `v0.1.0 · 0 pending · 0 processing · last processed —`.

Behind the scenes you can confirm:

```bash
# File landed safely
ls -la data/uploads/pending/

# DB row recorded
sqlite3 data/db/aegisnotes.db "SELECT id, original_name, status, file_sha256 FROM uploads;"

# Logs are flowing
tail -n 20 data/logs/aegisnotes.log
```

Re-uploading the same file returns `duplicated: true` and the existing
record — SHA-256 dedupe works without involving the OCR pipeline.

## Project Layout

```
aegisnotes/
├── config/                   # pydantic-validated settings + logging
├── data/                     # uploads/, db/, logs/ — runtime data
├── docs/                     # ARCHITECTURE.md, DATABASE.md
├── frontend/                 # static HTML/CSS/JS dashboard
├── scripts/                  # setup, init_db, create_user, systemd unit
├── src/
│   ├── api/                  # FastAPI routes + dependencies + security
│   ├── database/             # schema.sql, connection, models, repositories
│   ├── intelligence/         # Phase 3-5 (cleaner, parser, TF-IDF, summariser, flashcards)
│   ├── ocr/                  # Phase 2 (tesseract wrapper, preprocessing)
│   ├── tasks/                # Phase 6 (background queue + processor)
│   ├── upload/               # validator + handler (Phase 1)
│   ├── utils/                # logging, hashing, paths, time
│   ├── watcher/              # Phase 6 (watchdog file observer)
│   └── main.py               # FastAPI entrypoint
└── tests/
```

The authoritative architecture lives in `docs/ARCHITECTURE.md`. The
authoritative schema lives in `src/database/schema.sql`.

## Configuration

All settings come from environment variables (or the `.env` file). See
`.env.example` for the complete list. Highlights:

| Variable                  | Default                | Purpose                                   |
|---------------------------|------------------------|-------------------------------------------|
| `AEGIS_SECRET_KEY`        | (required)             | Signs session cookies. 32+ chars.         |
| `AEGIS_PORT`              | `8000`                 | HTTP listener port.                       |
| `AEGIS_MAX_UPLOAD_MB`     | `50`                   | Per-file size cap, enforced while writing.|
| `AEGIS_ALLOWED_MIME`      | jpeg, png, webp, tiff, pdf | Comma-separated MIME allow-list.      |
| `AEGIS_SESSION_TTL_HOURS` | `168` (7 days)         | Session cookie lifetime.                  |
| `AEGIS_COOKIE_SECURE`     | `false`                | Set `true` behind HTTPS / reverse proxy.  |
| `AEGIS_DATA_DIR`          | `./data`               | Override to mount an SSD.                 |
| `AEGIS_LOG_LEVEL`         | `INFO`                 | Standard Python logging levels.           |

## API Surface (Phases 1-2)

```
POST   /api/auth/login            { username, password }
POST   /api/auth/logout
GET    /api/auth/me
POST   /api/auth/change-password  { current_password, new_password }

POST   /api/uploads               multipart/form-data file=<...>
GET    /api/uploads?status_filter=&limit=&offset=
GET    /api/uploads/{id}

GET    /api/notes[?course=&limit=&offset=]    (Phase 2 — real)
GET    /api/notes/{id}                         (Phase 2 — real)
GET    /api/notes/by-upload/{upload_id}        (Phase 2 — status + note)

GET    /api/system/status
GET    /api/system/logs?level=&limit=&offset=  (admin only)
```

Future phases populate stubs already wired in:

```
GET    /api/notes/{id}/topics                  (Phase 3)
GET    /api/notes/{id}/summary                 (Phase 5)
GET    /api/notes/{id}/flashcards              (Phase 5)
GET    /api/notes/{id}/links                   (Phase 4)
GET    /api/tags, /api/tags/{name}/notes       (Phase 4)
GET    /api/search?q=                          (Phase 7)
```

All state-changing endpoints require the `X-Requested-With: fetch`
header — the JS client sets it automatically. The cookie is
`SameSite=Strict; HttpOnly`. Set `AEGIS_COOKIE_SECURE=true` once the Pi
is reachable only over HTTPS.

## Roadmap

The build proceeds in eight phases. Phase 1 is in this repo; each
subsequent phase ships as a contained PR.

| Phase | Goal                                | Status |
|-------|-------------------------------------|--------|
| **1** | Core app structure & secure upload  | ✅ shipped |
| **2** | OCR integration (Tesseract + preprocessing + background workers) | ✅ shipped |
| **3** | Text cleaning + structural parsing  | next |
| **4** | Category engine — TF-IDF + cosine similarity across notes | planned |
| **5** | Summary generator + flashcard generator | planned |
| **6** | Realtime: watchdog observer, background queue, SSE updates | planned |
| **7** | Search + filtering (FTS5 + tag/category facets) | planned |
| **8** | Pi optimisation: memory caps, batch sizing, encryption-at-rest prep | planned |

Phase boundaries deliberately follow the strategic advice: don't add a
React build, don't reach for heavy ML models, and don't try to be
"perfect AI" before the basic flow — **upload → OCR → categorise →
search → view** — works end-to-end and feels good.

## Testing

A `tests/` package is scaffolded for `pytest`. Phase 1 ships with the
foundations needed to start adding tests; the canonical first test is
upload dedupe:

```bash
pytest -q
```

## Security Notes

- **No public sign-up.** Accounts are created out-of-band with
  `scripts/create_user.py`. The first admin is created during
  `setup_pi.sh`.
- **No traversal.** Uploads are stored under `<sha256>__<safe_name>` in
  `data/uploads/pending/`. The validator strips path components and
  refuses leading dots; the handler `assert_within`s the configured
  root before any rename.
- **Magic-byte sniff.** When `libmagic` is present the on-disk payload
  is sniffed and required to be compatible with the declared
  `Content-Type`. Mismatches are rejected.
- **Argon2id passwords.** Tuned for the Pi (~120 ms per verify).
- **Constant-ish-time login.** Authentication runs a throwaway verify
  when the user does not exist to defeat trivial timing oracles.
- **CSRF.** `SameSite=Strict` cookie + `X-Requested-With` header.
- **systemd hardening.** `NoNewPrivileges`, `ProtectSystem=full`,
  `ProtectHome=read-only`, scoped `ReadWritePaths` — see
  `scripts/aegisnotes.service`.

## License

To be decided by the project owner. Until then: source-available, not
yet open-source. Don't redistribute without permission.
