# Intelligent Media Processing Pipeline

Backend service that accepts vehicle image uploads, analyzes them
asynchronously for common field-upload issues (blur, low light, duplicates,
invalid plate format), and exposes status/results APIs to poll for outcomes.

See also: [`plan.md`](plan.md) (scope/checklist), [`workflow.md`](workflow.md)
(request/processing flow), [`decision.md`](decision.md) (tech choices + why).

## Architecture

```
Client
  |
  v
FastAPI app (app/main.py)
  |
  |-- POST /upload -----------> saves file to disk, inserts DB row
  |                              (status=pending), pushes job onto an
  |                              in-process queue.Queue, returns 202 fast
  |
  |-- GET /status/{id} --------> reads current status from DB
  |-- GET /results/{id} -------> reads results/verdict from DB (409 if not
  |                              completed yet)
  |-- GET /results/{id}/failure -> reads failure_reason (409 if not failed)
  |
  v
Background worker thread (app/worker.py)
  - single daemon thread, consumes job IDs from the queue
  - sets status=processing -> runs 4 analysis checks -> status=completed/failed
  - each check is independently wrapped in try/except so one bad check
    doesn't fail the whole job

Analysis checks (app/analysis/):
  - blur.py        Laplacian variance (OpenCV)
  - brightness.py  mean grayscale intensity
  - duplicate.py   perceptual hash (imagehash) vs all prior completed jobs
  - plate.py       pytesseract OCR + regex against Indian plate format

Persistence: SQLite via SQLAlchemy (app/models.py) - one table, `image_jobs`,
storing status, results (JSON), verdict, failure_reason, timestamps.
```

Full request/processing sequence: see [`workflow.md`](workflow.md).

## Why these choices (short version, full reasoning in decision.md)

- **FastAPI + SQLite + SQLAlchemy**: fast to run locally, zero external
  services, auto-generated `/docs`, ORM makes a future Postgres swap a
  connection-string change.
- **In-process queue (`queue.Queue` + a worker thread)** instead of
  Celery/Redis/RabbitMQ: the assignment says the choice matters less than the
  reasoning. This gets the same architecture (decoupled async processing,
  explicit state machine) without extra infrastructure to run/debug in the
  time available. Documented trade-off: doesn't survive a process restart and
  doesn't scale beyond one instance - noted as the first thing to change for
  production.
- **Heuristics, not ML models**, for the 4 checks: the brief explicitly says
  accuracy isn't the target, structuring uncertainty is. Every check returns
  a numeric score + threshold, not just a boolean, so results are explainable.

## Running locally

Requires Python 3.10+ and the `tesseract-ocr` system package for the plate
check (OCR degrades gracefully and reports `"ocr_available": false` if
missing, rather than failing the job).

```bash
# 1. System dependency for OCR (skip if already installed)
sudo apt-get install -y tesseract-ocr

# 2. Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Config (optional - sane defaults are baked in)
cp .env.example .env

# 4. Run
uvicorn app.main:app --reload

# Interactive API docs: http://localhost:8000/docs
```

## Trying it out

See [`curl_examples.md`](curl_examples.md) for real captured request/response
pairs, or run the end-to-end smoke test against a running server:

```bash
python tests/test_api.py
```

## AI Usage Disclosure

I used Claude throughout this build. Concretely:

- **Scaffolding & boilerplate**: FastAPI app structure, SQLAlchemy models,
  Pydantic schemas, the worker thread pattern - AI-generated first draft,
  then I read through each file to confirm the DB session lifecycle
  (`get_db` dependency, session-per-job in the worker) was correct, since
  that's an easy place to introduce connection leaks.
- **Analysis heuristics**: AI proposed the specific techniques (Laplacian
  variance for blur, mean grayscale intensity for brightness, perceptual
  hashing for duplicates, OCR+regex for plate format) and default thresholds.
  I validated these by actually running the pipeline against synthetic
  sharp/blurry and bright/dark test images and checking the scores landed on
  the correct side of the threshold (see `tests/test_api.py` and the manual
  runs recorded in `curl_examples.md`) rather than trusting the numbers
  blindly.
- **Where AI output was wrong / needed correction**: the first version of the
  background-server test setup used a plain `&`-backgrounded process, which
  died as soon as the shell session ended - had to fix by using `setsid` to
  properly detach it. This is an infra/testing detail, not application code,
  but it's a real example of validating rather than trusting AI-run commands.
  Also, the initial plate regex assumed OCR would cleanly return uppercase
  alphanumerics; real Tesseract output on the test image included stray
  spaces and mis-read `0` as `O`, which is expected OCR noise, not a bug -
  documented under Trade-offs below rather than "fixed" with over-fitted
  regex hacks.
- **Docs (plan/workflow/decision.md, this README)**: drafted with AI,
  reviewed and kept in sync with what was actually built, not written
  aspirationally before the code existed.
- **What I did NOT let AI decide**: which requirements to cut for time (I set
  that scope), and the final call on queue architecture (in-process vs
  Celery) - AI laid out the trade-off, I made the call given the 48h/time
  constraint.

## Trade-offs (what I intentionally simplified)

- **No retries**: a failed job stays failed. Production version would add a
  retry count + exponential backoff before marking failed.
- **In-process queue**: single point of failure, no horizontal scaling. See
  decision.md for the swap-to-Redis/Celery path.
- **SQLite**: fine for this scale; would move to Postgres for concurrent
  writes and JSONB indexing on `results` at real scale.
- **OCR accuracy**: pytesseract on a synthetic/photographed plate is noisy
  (confuses `0`/`O`, sensitive to angle/lighting). A production system would
  use a cloud OCR API or a plate-specific detection model; documented as the
  clearest accuracy upgrade path.
- **No screenshot / photo-of-photo / tamper detection**: these need stronger
  signals (EXIF presence, moire pattern detection, recompression artifacts)
  to be meaningfully better than a coin flip. Skipped rather than shipped as
  a fake check - listed under "what I'd improve" below.
- **Duplicate detection is O(n)** per upload (scans all prior completed
  jobs' hashes). Fine at hundreds/thousands of rows; would need an indexed
  hash-bucket or vector search structure at real scale.
- **No auth, no rate limiting**: explicitly bonus-tier per the brief, cut to
  protect time for core requirements + documentation.

## What I'd improve with more time

1. Screenshot/tamper heuristics (EXIF check, moire detection via FFT,
   recompression artifact analysis)
2. Swap in-process queue for Redis+RQ (interface barely changes - see
   decision.md) for restart-safety and multi-instance scaling
3. Docker Compose for one-command spin-up
4. Retry policy with backoff and a `retry_count` column
5. Confidence scoring that combines all 4 check scores into a single
   weighted "issue confidence" rather than a boolean verdict
6. Real unit tests per analysis module (currently one end-to-end smoke test)

## Scalability concerns (honest assessment)

- Single worker thread processes jobs strictly one at a time - no
  concurrency. Fine for a take-home; a real system would run N worker
  processes/pods pulling from a shared broker.
- Duplicate-hash scan is linear in total completed jobs.
- SQLite write-locks the whole file per transaction - a real concurrent-write
  workload needs Postgres.

## Failure handling concerns (honest assessment)

- If the worker thread itself crashes (not just a per-job exception), no
  jobs currently in `pending`/`processing` will ever complete - there's no
  supervisor to restart it. A production version would run the worker as a
  separate supervised process (systemd/Docker restart policy) rather than a
  thread inside the API process.
- Corrupt/unreadable images are caught (`cv2.imread` returning `None`) and
  correctly marked `failed` with a reason - verified in testing.
