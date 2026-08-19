import queue
import threading
import logging

from app.database import SessionLocal
from app.models import ImageJob, JobStatus
from app.analysis import run_all_checks

logger = logging.getLogger("media_pipeline")

job_queue: "queue.Queue[str]" = queue.Queue()
_worker_thread = None


def enqueue(job_id: str):
    job_queue.put(job_id)
    logger.info("Enqueued job %s (queue depth=%d)", job_id, job_queue.qsize())


def _process_job(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(ImageJob).filter(ImageJob.id == job_id).first()
        if job is None:
            logger.error("Job %s not found in DB, skipping", job_id)
            return

        job.status = JobStatus.processing
        db.commit()
        logger.info("Processing job %s", job_id)

        analysis = run_all_checks(job.stored_path, job_id, db)

        job.status = JobStatus.completed
        job.results = analysis["checks"]
        job.verdict = analysis["verdict"]
        job.perceptual_hash = analysis["perceptual_hash"]
        db.commit()
        logger.info("Job %s completed, verdict=%s", job_id, analysis["verdict"])

    except Exception as e:
        logger.exception("Job %s failed", job_id)
        db.rollback()
        job = db.query(ImageJob).filter(ImageJob.id == job_id).first()
        if job:
            job.status = JobStatus.failed
            job.failure_reason = str(e)
            db.commit()
    finally:
        db.close()


def _worker_loop():
    logger.info("Worker thread started")

    while True:
        job_id = job_queue.get()

        try:
            _process_job(job_id)

        except Exception:
            logger.exception(
                "Unexpected worker error for job %s",
                job_id,
            )

        finally:
            job_queue.task_done()


def start_worker():
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="analysis-worker")
        _worker_thread.start()
