# Workflow

## 1. Upload flow
```
Client -> POST /upload (multipart file)
       -> API generates UUID
       -> saves file to /uploads/{uuid}.{ext}
       -> inserts DB row: status=pending, results=null
       -> pushes job {id} onto in-process queue
       -> returns 202 { id, status: "pending" } immediately
```
The client never waits on analysis. This is the "async" requirement — upload
returns fast, processing happens off the request thread.

## 2. Processing flow (background worker)
```
Worker thread (single, loops forever):
  job = queue.get()               # blocks until a job arrives
  set DB status = "processing"
  try:
      img = load(job.path)
      run 4 checks -> collect results + per-check confidence
      aggregate overall verdict (e.g. any check "issue_detected" -> flagged)
      set DB status = "completed", results = json
  except Exception as e:
      set DB status = "failed", failure_reason = str(e)
      log full traceback
```

## 3. Status states
`pending -> processing -> completed`
`pending -> processing -> failed`

Only forward transitions. No retries in this pass (documented trade-off).

## 4. Read flow
```
GET /status/{id}   -> { id, status, created_at, updated_at }
GET /results/{id}  -> 409 if not completed, else { id, status, results, verdict }
GET /results/{id}/failure -> failure_reason if status == failed
```

## 5. Analysis checks (each independent, run in sequence, one failure doesn't
   block the others — each wrapped in its own try/except so a bad check
   degrades gracefully instead of failing the whole job)

| Check       | Method                                   | Output |
|-------------|-------------------------------------------|--------|
| Blur        | Laplacian variance (OpenCV)               | score, is_blurry |
| Brightness  | mean grayscale pixel intensity            | score, is_low_light |
| Duplicate   | perceptual hash (imagehash) vs prior hashes in DB | is_duplicate, matched_id |
| Plate format| pytesseract OCR -> regex match against Indian plate pattern | extracted_text, is_valid_format |

## 6. Duplicate detection note
Perceptual hashes of every *completed* image are stored in the DB row. New
uploads are compared (Hamming distance) against all prior hashes. O(n) scan —
fine at this scale, documented as a scalability concern in decision.md.
