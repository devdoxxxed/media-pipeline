# Intelligent Media Processing Pipeline

A FastAPI backend that accepts vehicle image uploads, processes them
asynchronously against 4 quality checks, and exposes APIs to poll for
results.

**Checks:** blur detection · low light detection · duplicate image
detection · number-plate format validation (OCR)

---

## Architecture

### Service flow

```
Client
  |
  v
POST /upload
  - saves uploaded file to disk
  - inserts a DB row (status=pending)
  - pushes the job ID onto an in-process queue.Queue
  - returns 202 Accepted immediately (does not wait for processing)

GET /status/{id}           -> current status (pending/processing/completed/failed)
GET /results/{id}          -> results + verdict (409 if not yet completed)
GET /results/{id}/failure  -> failure reason (409 if not failed)
```

### Processing flow

A single background daemon thread (`app/worker.py`) continuously pulls job
IDs off the queue:

```
status = processing
  -> run blur check
  -> run brightness check
  -> run duplicate check
  -> run plate check
  (each check wrapped independently in try/except - one check failing
   does not fail the whole job or block the others)
status = completed (or failed, if something outside the checks broke -
  e.g. the image file itself is corrupt/unreadable)
```

Analysis modules live in `app/analysis/`:
- `blur.py` - Laplacian variance (OpenCV)
- `brightness.py` - mean grayscale intensity
- `duplicate.py` - perceptual hash (imagehash) compared against all prior
  completed jobs
- `plate.py` - HSV color + contour-based region detection, pytesseract OCR,
  regex validation against Indian plate format (with fuzzy correction for
  common OCR character confusions)

Each check returns a numeric score + threshold + boolean, not just a
pass/fail, so results are explainable rather than opaque.

### Queue strategy

In-process `queue.Queue` + a single worker thread, instead of
Celery/Redis/RabbitMQ.

**Why:** the assignment scope prioritizes reasoning over infrastructure
choice. This gets the same *architecture* (decoupled async processing,
explicit state machine, non-blocking upload endpoint) without external
services to run/debug in the time available.

**Documented trade-off:** this does not survive a process restart (queued
jobs are lost if the app restarts) and does not scale beyond one process.
See [Trade-offs](#trade-offs) below for the production path.

### Major design decisions

| Decision | Reasoning |
|---|---|
| FastAPI + SQLite + SQLAlchemy | Fast to run locally, zero external services, auto-generated `/docs`, ORM makes a future Postgres swap a connection-string change |
| In-process queue over Celery/Redis | See Queue strategy above |
| Heuristics, not ML models, for all 4 checks | Brief explicitly deprioritizes accuracy in favor of structuring uncertainty well; every check is explainable (score + threshold) |
| Every check isolated in try/except | One check failing (e.g. OCR unavailable) shouldn't fail the whole job |
| Plate detection returns `plate_detected: false` rather than a guess when uncertain | A confident wrong plate number is worse than an honest "couldn't verify" for a system meant to flag issues |

---

## AI Usage Disclosure (Mandatory)

I used Claude throughout this build. Concretely:

**Where AI helped:**
- **Scaffolding & boilerplate**: FastAPI app structure, SQLAlchemy models,
  Pydantic schemas, the worker thread pattern - AI-generated first draft.
- **Analysis heuristics**: AI proposed the specific techniques (Laplacian
  variance for blur, mean grayscale intensity for brightness, perceptual
  hashing for duplicates, OCR+regex for plate format) and default
  thresholds.
- **Plate detection debugging**: this was the hardest part of the project.
  AI helped iteratively debug why plate OCR was failing on real test
  images - working through color-detection false positives (ad banners,
  vehicle trim matching the plate's yellow color), aspect-ratio
  assumptions that didn't account for two-line stacked plates, and OCR
  character-confusion correction.
- **Docs** (this README, `plan.md`, `workflow.md`, `decision.md`): drafted
  with AI, corrected to match what was actually built.

**How I validated AI-generated code (not just trusted it):**
- Read every generated file to confirm DB session lifecycle (`get_db`
  dependency, session-per-job in the worker) was correct - an easy place
  to introduce connection leaks.
- Ran the pipeline against real/synthetic sharp vs. blurry and bright vs.
  dark images and confirmed scores landed on the correct side of each
  threshold, rather than trusting the numbers blindly (see
  `curl_examples.md` for captured real runs).
- For plate detection specifically: added debug logging at every stage
  (candidate region coordinates, OCR output per candidate, rejection
  reasons) and manually cross-checked detected regions against the actual
  plate location in test images, rather than assuming a "no errors thrown"
  result meant it was working correctly.
- Manually located ground-truth plate pixel coordinates in test images and
  ran OCR against a known-correct crop to separate "is detection finding
  the right region" from "is OCR reading it correctly" as two distinct
  failure modes, instead of guessing which layer was broken.

**Where AI output was wrong or needed correction:**
- The first version of the background-server test setup used a plain
  `&`-backgrounded process, which died as soon as the shell session
  ended - fixed using `setsid` to properly detach it.
- An early plate-detection fuzzy-matching approach (correcting OCR
  character confusions) was too permissive: it tolerated enough
  insertions/deletions that it started confidently matching the *wrong*
  plate number out of noisy background text (valid format, wrong digits).
  I caught this by testing it against known noisy OCR output before
  deploying it, and scaled it back to a safer, substitution-only version
  that only corrects individually-confusable characters (e.g. 0/O, 1/I,
  2/Z) rather than tolerating extra/missing characters - a wrong confident
  answer is worse than no answer for this use case.
- Initial plate-region detection assumed single-line, elongated plates
  (aspect ratio ~4:1+). Real test images included two-line stacked plates
  (common on autos/two-wheelers in India, aspect ratio closer to ~2:1),
  which the original filters rejected outright. Caught by manually
  inspecting debug crops rather than trusting that "0 candidates found"
  meant no plate was present.
- Yellow-color-based plate detection assumed the plate would be visually
  distinct from its surroundings. On auto-rickshaws, the vehicle body
  itself is painted the same yellow as the plate, so color alone can't
  separate them - confirmed by visualizing the raw color mask, not by
  assumption. Documented as a known limitation rather than solved with
  increasingly fragile heuristics.

**What I did NOT let AI decide:** which requirements to cut for time, and
the final call on queue architecture (in-process vs. Celery) - AI laid out
the trade-off, I made the call given the time constraint.

---

## Trade-offs

### What I intentionally simplified

- **No retries**: a failed job stays failed. Production version would add
  a retry count + exponential backoff before marking failed.
- **In-process queue**: single point of failure, no horizontal scaling
  (see Queue strategy above).
- **SQLite**: fine for this scale; would move to Postgres for concurrent
  writes and JSONB indexing on `results` at real scale.
- **Plate OCR accuracy**: heuristic color/contour detection + pytesseract,
  not a trained plate-detection model. Reads plates reliably when
  reasonably visible; correctly reports low confidence rather than
  guessing on harder images (plate flush against same-colored vehicle
  trim, heavy glare, ad wraps covering most of the frame). See
  `decision.md` for the specific debugging process.
- **No screenshot / photo-of-photo / tamper detection**: needs stronger
  signals (EXIF presence, moire pattern detection, recompression
  artifacts) to be meaningfully better than a coin flip. Skipped rather
  than shipped as a fake check.
- **Duplicate detection is O(n)** per upload (scans all prior completed
  jobs' hashes). Fine at hundreds/thousands of rows; would need an
  indexed hash-bucket or vector search structure at real scale.
- **No auth, no rate limiting**: explicitly bonus-tier per the brief, cut
  to protect time for core requirements + documentation.
- **No Docker**: see Running Instructions below for the manual setup used
  instead.

### What I'd improve with more time

1. A trained plate-detection model (or a cloud OCR/ANPR API) in place of
   the color+contour heuristic - this is the clearest accuracy upgrade
   path for the plate check specifically.
2. Screenshot/tamper heuristics (EXIF check, moire detection via FFT,
   recompression artifact analysis).
3. Swap in-process queue for Redis+RQ (interface barely changes) for
   restart-safety and multi-instance scaling.
4. Docker Compose for one-command spin-up.
5. Retry policy with backoff and a `retry_count` column.
6. Confidence scoring that combines all 4 check scores into a single
   weighted "issue confidence" rather than a boolean verdict.
7. Real unit tests per analysis module (currently one end-to-end smoke
   test).

### Scalability concerns (honest assessment)

- Single worker thread processes jobs strictly one at a time - no
  concurrency. A real system would run N worker processes/pods pulling
  from a shared broker.
- Duplicate-hash scan is linear in total completed jobs.
- SQLite write-locks the whole file per transaction - a real
  concurrent-write workload needs Postgres.

### Failure handling concerns (honest assessment)

- If the worker thread itself crashes (not just a per-job exception), no
  jobs currently in `pending`/`processing` will ever complete - there's no
  supervisor to restart it. Production version would run the worker as a
  separate supervised process (systemd/Docker restart policy) rather than
  a thread inside the API process.
- Corrupt/unreadable images are caught (`cv2.imread` returning `None`) and
  correctly marked `failed` with a reason - verified in testing.
- Each of the 4 checks is independently try/except-wrapped, so e.g. OCR
  being unavailable on a host doesn't fail blur/brightness/duplicate
  results for that job - `plate_format.ocr_available` reports `false`
  instead.

---

## Running Instructions

Requires Python 3.10+ and the `tesseract-ocr` system package (OCR degrades
gracefully - reports `"ocr_available": false` rather than failing the job
if missing).

```bash
# 1. System dependency for OCR
sudo apt-get install -y tesseract-ocr    # macOS: brew install tesseract

# 2. Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Config (optional - sane defaults are baked in)
cp .env.example .env

# 4. Run
uvicorn app.main:app --reload

# Interactive API docs: http://localhost:8000/docs
```

### Test scripts

End-to-end smoke test against a running server:
```bash
python tests/test_api.py
```

Real captured request/response pairs: [`curl_examples.md`](curl_examples.md)

### Docker

Not included - see [Trade-offs](#trade-offs) for reasoning and the
documented upgrade path (Docker Compose for one-command spin-up).

---

## Further reading

- [`plan.md`](plan.md) - scope/checklist
- [`workflow.md`](workflow.md) - detailed request/processing sequence
- [`decision.md`](decision.md) - extended technical decision log,
  including the full plate-detection debugging process