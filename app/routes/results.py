from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImageJob, JobStatus
from app.schemas import StatusResponse, ResultsResponse, FailureResponse

router = APIRouter()


def _get_job_or_404(job_id: str, db: Session) -> ImageJob:
    job = db.query(ImageJob).filter(ImageJob.id == job_id).first()
    if job is None:
        raise HTTPException(404, f"No job found with id '{job_id}'")
    return job


@router.get("/status/{job_id}", response_model=StatusResponse)
def get_status(job_id: str, db: Session = Depends(get_db)):
    job = _get_job_or_404(job_id, db)
    return job


@router.get("/results/{job_id}", response_model=ResultsResponse)
def get_results(job_id: str, db: Session = Depends(get_db)):
    job = _get_job_or_404(job_id, db)
    if job.status != JobStatus.completed:
        raise HTTPException(
            409,
            f"Job '{job_id}' is not completed yet (current status: '{job.status.value}'). "
            f"Poll GET /status/{job_id} until status is 'completed'.",
        )
    return job


@router.get("/results/{job_id}/failure", response_model=FailureResponse)
def get_failure(job_id: str, db: Session = Depends(get_db)):
    job = _get_job_or_404(job_id, db)
    if job.status != JobStatus.failed:
        raise HTTPException(409, f"Job '{job_id}' has not failed (current status: '{job.status.value}')")
    return job
