# Sample API Requests / Responses

Captured against a locally running instance (`uvicorn app.main:app --reload`).

## 1. Upload

```bash
curl -X POST -F "file=@vehicle.jpg" http://localhost:8000/upload
```

```json
{
  "id": "553bcfc5-b30c-4557-a792-79ae39aedfa9",
  "status": "pending",
  "message": "Upload accepted. Processing started asynchronously."
}
```

## 2. Poll status

```bash
curl http://localhost:8000/status/553bcfc5-b30c-4557-a792-79ae39aedfa9
```

```json
{
  "id": "553bcfc5-b30c-4557-a792-79ae39aedfa9",
  "status": "completed",
  "original_filename": "vehicle.jpg",
  "created_at": "2026-08-19T09:59:20.595320",
  "updated_at": "2026-08-19T09:59:21.732800"
}
```

## 3. Fetch results

```bash
curl http://localhost:8000/results/553bcfc5-b30c-4557-a792-79ae39aedfa9
```

```json
{
  "id": "553bcfc5-b30c-4557-a792-79ae39aedfa9",
  "status": "completed",
  "verdict": "flagged",
  "results": {
    "blur": { "check": "blur", "score": 10667.35, "threshold": 100.0, "is_blurry": false },
    "brightness": { "check": "brightness", "score": 158.54, "threshold": 60.0, "is_low_light": false },
    "duplicate": { "check": "duplicate", "hash": "9595726a6a6a863d", "closest_match_id": null, "hamming_distance": null, "is_duplicate": false },
    "plate_format": { "check": "plate_format", "ocr_available": true, "raw_text": "KAO 1AB1234", "extracted_text": null, "is_valid_format": false }
  }
}
```

## 4. Results requested before processing finishes -> 409

```bash
curl -i http://localhost:8000/results/<pending-job-id>
```

```
HTTP/1.1 409 Conflict
{"detail":"Job '<id>' is not completed yet (current status: 'processing'). Poll GET /status/<id> until status is 'completed'."}
```

## 5. Failure reason (only valid once status == failed)

```bash
curl http://localhost:8000/results/<job-id>/failure
```

```json
{ "id": "<job-id>", "status": "failed", "failure_reason": "Could not decode image at ... (corrupt or unsupported format)" }
```

## 6. Unknown job -> 404

```bash
curl -i http://localhost:8000/status/does-not-exist
```

```
HTTP/1.1 404 Not Found
{"detail":"No job found with id 'does-not-exist'"}
```

## 7. Duplicate detection (re-upload the same image)

Uploading the same file (or a blurred/darkened variant) a second time
returns `"is_duplicate": true` with `closest_match_id` pointing at the
original job and a low `hamming_distance` (0 for an exact copy, tested up
to distance 4 for a heavily blurred+darkened variant of the same photo).
