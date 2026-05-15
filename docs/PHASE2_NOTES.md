# Phase 2 — OCR Integration

Phase 2 connects uploads to Tesseract. Once a file lands in
``data/uploads/pending/`` the background worker picks it up, OCRs it,
normalizes the whitespace, writes a ``notes`` row, and moves the file to
``data/uploads/processed/``. Failures land in ``data/uploads/failed/``
with a structured error payload on the upload row and a matching
``system_logs`` entry.

## Module layout (added in Phase 2)

```
src/
├── ocr/
│   ├── __init__.py          # public surface (OcrEngine, OcrProcessor)
│   ├── engine.py            # tesseract subprocess wrapper (pytesseract)
│   ├── preprocessing.py     # PIL load + EXIF + grayscale + downscale
│   └── processor.py         # claim → OCR → persist note → move file → log
│
├── tasks/
│   ├── __init__.py          # start_workers / stop_workers / signal_work
│   ├── queue.py             # thread-safe wake signal
│   └── processor.py         # WorkerPool: poll + signal, ThreadPoolExecutor
│
└── database/repositories/
    └── notes_repo.py        # NotesRepository (create/get/list/update_text)
```

The upload, auth, security, frontend shell, and DB connection layers
are **unchanged** apart from minor additive edits (new repo method,
optional ``relative_path`` kwarg on ``mark_processed``/``mark_failed``,
``signal_work()`` in the upload route).

## Required apt packages on the Pi

`scripts/setup_pi.sh` already installs them, but for reference:

```bash
sudo apt-get install --no-install-recommends \
    tesseract-ocr tesseract-ocr-eng \
    poppler-utils \
    libgl1 libglib2.0-0 \
    libmagic1
```

* **tesseract-ocr** — OCR binary.
* **tesseract-ocr-eng** — English language data. Add more language
  packs the same way (`tesseract-ocr-fra`, `tesseract-ocr-deu`, …) and
  set ``language="eng+fra"`` when constructing :class:`OcrEngine`.
* **poppler-utils** — provides ``pdftoppm`` / ``pdfinfo`` used by
  ``pdf2image`` for PDF rendering.
* **libgl1 / libglib2.0-0** — runtime deps for
  ``opencv-python-headless`` (used by future Phase 3 preprocessing).
* **libmagic1** — magic-byte MIME sniffing in the upload validator.

## Configuration

| Variable             | Default | Effect                                              |
|----------------------|---------|-----------------------------------------------------|
| ``AEGIS_OCR_WORKERS``| ``2``   | OS threads that run tesseract subprocesses in parallel. The Pi 5 has 4 cores — leave 2 free for uvicorn + the worker loop. |
| ``OMP_THREAD_LIMIT`` | ``1``   | Set automatically by ``src/ocr/engine.py`` at import time so each tesseract subprocess uses one core's worth of libgomp threads. |

To run a single OCR worker on a memory-constrained Pi:

```bash
AEGIS_OCR_WORKERS=1 bash scripts/run_dev.sh
```

## End-to-end smoke test on the Pi

```bash
# Start the service
bash scripts/run_dev.sh

# In another shell, log in and upload a real image
COOKIE_JAR=$(mktemp)
curl -c "$COOKIE_JAR" -X POST http://localhost:8000/api/auth/login \
     -H 'Content-Type: application/json' \
     -H 'X-Requested-With: fetch' \
     -d '{"username":"admin","password":"YOUR_PASSWORD"}'

curl -b "$COOKIE_JAR" -X POST http://localhost:8000/api/uploads \
     -H 'X-Requested-With: fetch' \
     -F 'file=@/path/to/my_notes.jpg'
# -> {"upload":{"id":1,"status":"pending",...}}

# Wait a couple of seconds, then fetch the note
curl -b "$COOKIE_JAR" http://localhost:8000/api/notes/by-upload/1 | jq
# -> {"upload_status":"processed", "note":{"id":1,"cleaned_text":"...",...}}
```

Or use the dashboard at `http://<pi-ip>:8000/` — uploads now expand
when clicked, revealing the cleaned OCR text inline.

## Watching it work

```bash
# Live log
tail -f data/logs/aegisnotes.log

# Live system_logs (operational mirror)
sqlite3 data/db/aegisnotes.db \
  "SELECT created_at, level, source, message FROM system_logs ORDER BY id DESC LIMIT 20;"

# Upload status timeline
sqlite3 data/db/aegisnotes.db \
  "SELECT id, original_name, status, uploaded_at, processed_at, error FROM uploads ORDER BY id DESC;"
```

## Forcing a failure

Drop a known-bad file in to confirm the failure path:

```bash
echo "not a real jpeg" > /tmp/bad.jpg
curl -b "$COOKIE_JAR" -X POST http://localhost:8000/api/uploads \
     -H 'X-Requested-With: fetch' \
     -F 'file=@/tmp/bad.jpg;type=image/jpeg'
```

If the file passes upload validation (header-only sniff without
libmagic), OCR will reject it as ``decode_error``: the row is moved to
``data/uploads/failed/``, ``uploads.status`` becomes ``failed``,
``uploads.error`` contains the JSON payload, and a row appears in
``system_logs`` with ``source='ocr.processor'``.

## Performance considerations for Raspberry Pi 5

| Concern                          | Mitigation                                                            |
|----------------------------------|------------------------------------------------------------------------|
| Tesseract is CPU-bound           | 2 thread-pool workers by default — `AEGIS_OCR_WORKERS=2`. Pi 5 has 4 cores; we leave 2 free for the API + worker loop. |
| Phone JPEGs are huge (12 MP)     | ``preprocessing.downscale`` caps the longest edge at 2400 px. Tesseract LSTM accuracy plateaus around 300 DPI; bigger isn't better. |
| PDFs balloon memory              | ``pdf2image.convert_from_path`` is called **per page** (`first_page=i, last_page=i`). Only one rendered page is in RAM at a time. |
| libgomp over-subscription        | ``OMP_THREAD_LIMIT=1`` is set in ``engine.py`` before pytesseract loads. Without this, each tesseract subprocess would spawn 4 libgomp threads and fight for the same cores. |
| SQLite write contention          | WAL mode + ``BEGIN``/``COMMIT`` around each repo call keeps the writer single-threaded; reads (dashboard) never block. |
| Crash mid-OCR leaves stuck rows  | ``WorkerPool._reconcile()`` reverts any ``processing`` rows to ``pending`` on startup. |
| Two workers grabbing same upload | ``UploadsRepository.try_claim`` is an atomic ``UPDATE … WHERE status='pending'`` whose ``rowcount`` decides ownership. |
| Long OCR job blocks shutdown     | ``WorkerPool.stop`` waits for in-flight jobs; ``cancel_futures=False`` is intentional — abandoning a job mid-flight would leave files in indeterminate locations. |
| Image decode OOM on tiny SD card | The processor only ever holds one PIL image in memory per worker; PDF rendering is per-page; raw OCR text is the only thing copied into the DB. |
| Hot temp dir slows SSD wear      | Set ``AEGIS_DATA_DIR=/mnt/ssd/aegis-data`` to move ``data/`` off the SD card. |

## Test ideas (Phase 2)

`tests/` is scaffolded but Phase 2 ships without yet checking in unit
tests — the engine integration is best validated with a real
``tesseract`` binary on the Pi. Candidate tests:

* **engine.run on a fixture JPEG** — assert text length > 0.
* **normalize_whitespace** — table-driven.
* **try_claim race** — spawn two threads, both call ``try_claim`` on
  the same row, exactly one returns True.
* **process recovers from missing file** — delete the on-disk file
  after upload but before OCR; expect status='failed'.
* **WorkerPool start/stop** — reaches idle within the poll interval.

## What Phase 2 deliberately does NOT do

* No structural parsing (headings, bullets) — Phase 3.
* No tags/categories/summaries/flashcards — Phases 4-5.
* No SSE updates — the dashboard still polls every 5 s. Phase 6
  swaps that out.
* No model downloads, no network calls, no Anthropic / OpenAI / Hugging
  Face — and never will at runtime.
