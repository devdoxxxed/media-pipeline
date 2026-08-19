# Decisions

Format: **Decision** — Options considered — Why this one — What we give up.

---

### Web framework: FastAPI
Options: FastAPI, Flask, Django REST Framework.
Why: async-native, Pydantic validation built in, auto docs (/docs) useful for
the "sample API requests/responses" deliverable, minimal boilerplate.
Give up: nothing significant for this scope. Flask would've needed extra
libraries (Flask-RESTful, marshmallow) to match validation/docs for free.

### Database: SQLite (via SQLAlchemy ORM)
Options: PostgreSQL, MySQL, MongoDB, SQLite.
Why: zero setup (no server/daemon to run), single file, and since we go
through SQLAlchemy the model layer is Postgres-compatible — swapping the
connection string is the only change needed to move to Postgres in prod.
Give up: no real concurrent-write performance, no JSONB indexing — acceptable
at take-home scale, called out as a scalability concern below.

### Async processing: in-process queue (Python `queue.Queue` + worker thread)
Options: Celery+Redis, RabbitMQ, AWS SQS, in-memory queue.
Why: the assignment explicitly says "choice matters less than reasoning."
A message broker (Redis/RabbitMQ) adds infra (a service to install/run) with
zero conceptual difference in the code's shape for a single-instance
take-home. Using `queue.Queue` + a daemon thread demonstrates the same async
architecture (producer/consumer, decoupled from request thread, status state
machine) without the setup overhead or extra moving parts to debug in 48h.
Give up: this does NOT survive a process restart (queue is in-memory) and
does NOT scale across multiple app instances (no shared broker). Documented
explicitly in README as "what I'd change for production": swap `queue.Queue`
for Redis+RQ or Celery, since the worker loop's interface (`get job -> update
DB -> ack`) barely changes.

### Analysis approach: OpenCV + heuristics, not ML models
Options: train/use CV models for blur/tamper detection, use cloud vision APIs
(AWS Rekognition/Google Vision), pure heuristics.
Why: problem statement explicitly says accuracy isn't the target, structuring
uncertainty is. Heuristics (Laplacian variance, mean brightness, perceptual
hash, regex on OCR) are transparent, fast, dependency-light, and each returns
an explainable score rather than an opaque model confidence.
Give up: heuristics are cruder than trained models (e.g. blur threshold is a
rule of thumb, not calibrated on a labelled dataset). Documented in README.

### OCR: pytesseract (local Tesseract) instead of a cloud OCR API
Why: no API key/network dependency needed to run the project locally; good
enough for large printed plate characters.
Give up: materially worse accuracy than Google Vision/AWS Textract on messy
real-world photos. If OCR proves unreliable in testing, we fall back to
validating a plate-number string passed alongside the upload and documenting
that OCR extraction is the enhancement path — this fallback will be noted
explicitly in the README if we take it.

### Screenshot / photo-of-photo / edited-image detection
Why not implemented as a 5th/6th check initially: these need much more
signal (moire patterns, EXIF absence, JPEG re-compression artifacts) to be
even heuristically meaningful, and the assignment requires "at least 4"
checks. We ship the 4 strongest, and list screenshot/tamper heuristics under
"what I'd improve with more time" in README rather than ship a check that's
just a coin flip.

### File storage: local disk (`/uploads`)
Options: local disk, S3/GCS.
Why: no cloud credentials needed to run locally; the storage layer is a thin
`storage.py` module with a `save(file) -> path` interface so swapping to S3
is a contained change.
Give up: not durable/scalable, single-instance only. Documented.

### No retries / no rate limiting / no auth
Why: explicitly bonus-tier per the assignment; cut to protect time for core
requirements + documentation quality, which are weighted more heavily.
