import logging
from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImageJob, JobStatus, gen_uuid
from app.storage import save_upload
from app.worker import enqueue
from app.schemas import UploadResponse

router = APIRouter()
logger = logging.getLogger("media_pipeline")


@router.post("/upload", response_model=UploadResponse, status_code=202)
def upload_image(file: UploadFile = File(...), db: Session = Depends(get_db)):
    job_id = gen_uuid()
    stored_path = save_upload(file, job_id)

    job = ImageJob(
        id=job_id,
        original_filename=file.filename,
        stored_path=stored_path,
        status=JobStatus.pending,
    )
    db.add(job)
    db.commit()

    enqueue(job_id)
    logger.info("Upload accepted: job_id=%s filename=%s", job_id, file.filename)

    return UploadResponse(id=job_id, status=JobStatus.pending.value)
