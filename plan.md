# Plan

## Goal
Backend service that accepts vehicle image uploads, processes them asynchronously
for quality/authenticity issues, and exposes status + results APIs.

## Scope for this pass (core requirements only, bonus skipped)
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
