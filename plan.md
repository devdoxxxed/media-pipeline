# Plan

## Goal
Backend service that accepts vehicle image uploads, processes them asynchronously
for quality/authenticity issues, and exposes status + results APIs.

## Scope for this pass (core requirements)
- [x] Upload API (unique ID, local storage, metadata in DB, immediate response)
- [x] Async processing (in-process queue + worker thread, status states:
      pending / processing / completed / failed)
- [x] 4 analysis checks: blur, brightness (low light), duplicate (perceptual hash),
      plate format validation (regex on OCR text)
- [x] Status API, Results API, Failure-reason API
- [x] Persistence (SQLite via SQLAlchemy, Postgres-ready schema)
- [ ] Bonus: Docker, dashboard, retries, rate limiting, real cloud storage —
      explicitly out of scope, documented in decision.md

## Milestones
1. Docs (this file, workflow.md, decision.md) — do first, keep updated as we build
2. DB models + schemas
3. Storage layer (save file to disk, return path)
4. Queue + worker (background thread consumes jobs, updates DB)
5. Analysis heuristics (4 checks, each returns a structured result + confidence)
6. API routes: POST /upload, GET /status/{id}, GET /results/{id}
7. README with architecture, AI usage disclosure, trade-offs, run instructions
8. curl_examples.md + tests/test_api.py smoke test
9. .gitignore, requirements.txt, final pass

## Explicitly out of scope (documented, not forgotten)
- Redis/Celery/RabbitMQ (see decision.md)
- Cloud storage (S3 etc.)
- Real ML models for blur/tamper detection (heuristics only, by design — see problem
  statement: "goal is NOT perfect ML accuracy")
- Auth/rate limiting
- Docker (may add if time remains)



---------->>> ASSUMPTIONS <<<<<<------------
# Assumptions

Explicit assumptions made while building this, where the brief was silent
or ambiguous.

## Scope / requirements

- "At least 4 meaningful checks" was read as exactly 4 being sufficient -
  didn't add a 5th check, since the brief lists checks as examples to
  choose from, not a minimum-of-5 target.
- Persistence brief *recommends* Postgres/MySQL/MongoDB but doesn't
  mandate it - SQLite was used instead (see `decision.md` /
  README Trade-offs for reasoning). Schema design follows the same
  relational shape either way, so swapping to Postgres is a
  connection-string change (SQLAlchemy), not a redesign.
- Docker and seed scripts are explicitly "bonus points," not core - scoped
  time accordingly; seed script included, Docker intentionally skipped
  (documented in README).

## Image input

- Accepted formats: standard photo formats readable by OpenCV
  (`cv2.imread`) - JPEG/PNG primarily. No explicit format whitelist/
  rejection is enforced beyond "can OpenCV read it" - unreadable files
  are caught and marked `failed` with a reason, not silently accepted.
- No explicit file-size limit is enforced. Assumed reasonable client-side
  behavior (a phone/browser upload) rather than adversarial/huge-file
  input, given no rate-limiting/auth is in scope either.
- Images are vehicle photos taken for a real-world upload flow (e.g. a
  driver/rider submitting proof), not adversarially crafted to defeat the
  checks - the checks are quality heuristics, not a security boundary.

## Plate detection specifically

- Only Indian vehicle registration plate format is validated (state code
  + RTO code + series + number), since the brief specifically calls out
  "Indian number plate format validation."
- Plate detection assumes plates are yellow (commercial vehicles) or
  reasonably high-contrast against their background. Plates that are the
  same color as large portions of the vehicle body (observed on some
  auto-rickshaws, where the whole vehicle is painted the plate's yellow)
  are a known, documented failure case rather than a silently-broken one.
- Both single-line and two-line (stacked) plate layouts are supported,
  since both are common in the real test images used - initial
  single-line-only assumption was corrected after testing (see
  `decision.md`).
- OCR misreads are corrected only via a bounded set of known
  visually-confusable character substitutions (e.g. 0/O, 1/I, 2/Z, H/N) -
  not a general fuzzy-match, since a broader correction approach was
  found (through testing) to sometimes confidently produce a
  wrong-but-valid-format plate number, which is worse than reporting
  "not detected."

## Async processing

- Single-process, single-worker-thread deployment is assumed for this
  submission (explicitly documented as not production-scale). Queued jobs
  are not persisted outside the in-memory queue, so a restart loses
  in-flight jobs - acceptable for this scope, called out as the first
  production upgrade in the README.
- "Processing" is assumed to mean running all 4 checks - a job doesn't
  move to `completed` until all 4 have been attempted (each individually
  fault-tolerant via try/except), rather than stopping at the first
  check that returns an issue.

## Verdict / flagging

- `verdict: flagged` is used whenever *any* check indicates a problem
  (blurry, low light, duplicate, or plate not validated) - assumed a
  human reviewer wants to see all flagged uploads rather than only ones
  failing every check, since the brief frames this as quality flagging,
  not automatic rejection.
- A low-confidence/undetected plate is treated as "flag for review," not
  as a hard failure of the job itself - the job still completes
  successfully; the *content* is flagged, the *processing* didn't fail.