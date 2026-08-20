# Decisions

This document captures the technical decisions made in this project and the reasoning behind them, particularly where a simpler option was chosen over a "production-grade" one.

## In-process queue instead of Redis/Celery

**Decision:** Use Python's `queue.Queue` with a background worker thread.

**Why:** The assignment's core requirement is asynchronous processing, not durable job orchestration. An in-process queue needs no external infrastructure, so the project runs with a single `uvicorn` command.

**Trade-off:** Jobs are not durable across restarts, and there's a single worker — no horizontal scaling. Documented as a known limitation rather than something to be papered over.

**Production alternative:** Redis/RQ, Celery, or a managed queue (SQS).

## SQLite instead of PostgreSQL

**Decision:** Use SQLite for job metadata and results.

**Why:** Zero setup, works out of the box for local review and grading.

**Trade-off:** Not suited for concurrent writers or production load.

**Production alternative:** PostgreSQL.

## Local filesystem storage instead of object storage

**Decision:** Store uploaded images on local disk, keyed by a generated UUID.

**Why:** Simplicity — no cloud credentials or setup needed to run the project.

**Trade-off:** Doesn't scale past a single machine, no built-in redundancy.

**Production alternative:** S3 or equivalent object storage.

## Forward-only status transitions, no retry

**Decision:** Jobs move `pending → processing → completed` or `pending → processing → failed`, with no automatic retries.

**Why:** Keeps the state machine simple and predictable for a take-home scope. Retry logic (backoff, max attempts, idempotency) adds meaningful complexity that wasn't core to demonstrating the pipeline.

**Trade-off:** A transient failure (e.g. Tesseract briefly unavailable) permanently fails the job rather than recovering on its own.

**Production alternative:** Retry with exponential backoff, dead-letter handling for jobs that exceed max attempts.

## Per-check isolation instead of an all-or-nothing pipeline

**Decision:** Each analysis check (blur, brightness, duplicate, plate) runs independently and failures are captured per-check rather than aborting the whole job.

**Why:** A single check failing (e.g. OCR engine unavailable) shouldn't discard results from checks that succeeded. This gives partial, still-useful results instead of an opaque total failure.

**Trade-off:** None significant — the extra isolation logic is cheap and self-contained per check.

## Perceptual hashing for duplicate detection, O(n) scan

**Decision:** Generate a pHash per completed image and compare against all previously completed hashes via Hamming distance.

**Why:** Simple to implement and reason about, and correct at the scale of a take-home dataset.

**Trade-off:** O(n) comparison cost grows linearly with the number of processed images — fine here, not fine at scale.

**Production alternative:** Indexed similarity search (e.g. an LSH-based index or a vector/hash index) instead of a full scan.

## Plate detection via OpenCV + Tesseract instead of a dedicated ANPR model

**Decision:** Use OpenCV heuristics to find plate-candidate regions, run Tesseract OCR on those regions, then validate the extracted text against an Indian plate-format regex.

**Why:** No dedicated ANPR model or paid API was in scope. This pipeline is "good enough" to demonstrate the concept and was iterated against the supplied sample images to cut down false positives from unrelated text and similarly-colored vehicle parts.

**Trade-off:** Accuracy depends heavily on image quality, plate visibility, lighting, and background — it's a heuristic pipeline, not a trained detector.

**Uncertain-result policy:** When the system isn't confident in a plate read, it returns `plate_detected: false`, `extracted_text: null`, `is_valid_format: null` rather than guessing. A wrong plate number is worse than no plate number.

**Production alternative:** A dedicated ANPR/plate-detection model, plus a proper confidence score per check (not implemented here — checks currently return raw scores/thresholds, not a standardized confidence metric).

## Scope exclusions

The following were deliberately left out to keep focus on the core assignment: Redis/Celery, Docker, retry/backoff, authentication, rate limiting, screenshot/photo-of-photo detection, advanced tamper detection, and standardized per-check confidence scoring. Each is called out in `README.md` under "Not Implemented" and "Future Improvements."