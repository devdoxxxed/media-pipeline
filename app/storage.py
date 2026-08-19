import os
import uuid
from fastapi import UploadFile, HTTPException

from app.config import UPLOAD_DIR, ALLOWED_EXTENSIONS, MAX_UPLOAD_MB


def save_upload(file: UploadFile, job_id: str) -> str:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    dest_path = os.path.join(UPLOAD_DIR, f"{job_id}{ext}")

    size = 0
    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    with open(dest_path, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                out.close()
                os.remove(dest_path)
                raise HTTPException(413, f"File exceeds {MAX_UPLOAD_MB}MB limit")
            out.write(chunk)

    if size == 0:
        os.remove(dest_path)
        raise HTTPException(400, "Empty file")

    return dest_path
