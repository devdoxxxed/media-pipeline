# Intelligent Media Processing Pipeline

A FastAPI backend that accepts vehicle image uploads, processes them asynchronously, and checks them for common image and vehicle-related issues.

## Features

- Async image upload & processing
- SQLite job metadata + results
- Blur detection
- Low-light detection
- Duplicate image detection (perceptual hashing)
- Number plate OCR + Indian plate-format validation
- Status tracking & structured results
- Isolated failure handling per check

## Architecture

```
Client → POST /upload → Save image → Create DB job → Queue job → Return Job ID

Queue → Background Worker → Analysis (Blur / Brightness / Duplicate / Plate OCR) → Store Results → completed / failed
```

Each analysis check runs independently — a failure in one doesn't block the others.

## Queue Strategy

Uses Python's `queue.Queue` with a background worker thread instead of Redis/Celery, keeping the project simple to run without external infra. Trade-off: jobs aren't durable across restarts, and there's a single worker. Production would swap this for Redis/RQ, Celery, or SQS.

## Analysis Checks

| Check | Method |
|---|---|
| Blur | OpenCV Laplacian variance |
| Brightness | Average grayscale intensity |
| Duplicate | Perceptual hashing (pHash) vs. past jobs |
| Number Plate | OpenCV region detection + Tesseract OCR + format validation |

OCR is best-effort — uncertain results return `null`/`false` rather than a guessed plate number.

## API

| Endpoint | Description |
|---|---|
| `POST /upload` | Upload an image, get a job ID |
| `GET /status/{id}` | `pending` / `processing` / `completed` / `failed` |
| `GET /results/{id}` | Analysis results once complete |
| `GET /results/{id}/failure` | Failure reason if job failed |

Interactive docs: `http://localhost:8000/docs`

## Project Structure

```
media-pipeline/
├── app/
│   ├── main.py, config.py, database.py, models.py, schemas.py
│   ├── storage.py, worker.py, logging_config.py
│   ├── routes/       # upload.py, results.py
│   └── analysis/     # blur.py, brightness.py, duplicate.py, plate.py
├── scripts/seed.py
├── tests/
├── plan.md / workflow.md / decision.md / curl_examples.md
└── requirements.txt
```

## Running Locally

```bash
# 1. Install Tesseract
brew install tesseract          # macOS
sudo apt-get install -y tesseract-ocr   # Ubuntu/Debian

# 2. Set up environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional

# 3. Run
uvicorn app.main:app --reload
```

Docs at `http://localhost:8000/docs`

## Sample Data

Sample images are in `tests/fixtures/`. Run:

```bash
python scripts/seed.py
```

This seeds jobs through the pipeline and prints job IDs you can query via `/status/{id}` and `/results/{id}`.

## Testing

```bash
PYTHONPATH=. pytest -v          # unit tests
python tests/test_api.py        # end-to-end smoke test (API must be running)
```

See `curl_examples.md` for sample requests.

## Trade-offs

- **In-process queue** — simple, but not durable across restarts, no horizontal scaling
- **SQLite** — easy locally; PostgreSQL better for production
- **Local storage** — simple; object storage (S3) better for production
- **Duplicate detection** — pHash comparison slows as job volume grows
- **Plate OCR** — heuristic-based, not a dedicated ANPR model; accuracy depends on image quality/lighting

## Not Implemented (by design, to focus on core assignment)

Redis/Celery, Docker, retry/backoff, auth, rate limiting, screenshot/photo-of-photo detection, advanced tamper detection, advanced confidence scoring.

## Future Improvements

- Redis/RQ or Celery for the queue
- PostgreSQL, object storage
- Retry/backoff, dedicated ANPR model, confidence scoring
- More tests, tamper detection, Docker Compose

## AI Usage Disclosure

AI tools assisted with FastAPI/SQLAlchemy scaffolding, the background worker, image-analysis approaches, OCR debugging, tests, and docs. All AI-generated code was reviewed and tested. The plate-detection logic in particular went through several iterations to reduce false positives, tested against the supplied sample images.

## Docs

- `plan.md` — scope & checklist
- `workflow.md` — processing workflow
- `decision.md` — technical decisions
- `curl_examples.md` — API examples