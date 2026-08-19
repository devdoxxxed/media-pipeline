import imagehash
from PIL import Image
from sqlalchemy.orm import Session

from app.config import DUPLICATE_HASH_DISTANCE
from app.models import ImageJob, JobStatus


def compute_phash(image_path: str) -> str:
    return str(imagehash.phash(Image.open(image_path)))


def check_duplicate(image_path: str, current_job_id: str, db: Session) -> dict:
    """
    Compares perceptual hash of this image against hashes of all previously
    completed jobs. O(n) scan - fine at take-home scale, flagged as a
    scalability concern in decision.md (would move to a vector/hash index
    in production).
    """
    new_hash = compute_phash(image_path)
    new_hash_obj = imagehash.hex_to_hash(new_hash)

    prior_jobs = (
        db.query(ImageJob)
        .filter(ImageJob.status == JobStatus.completed, ImageJob.perceptual_hash.isnot(None))
        .filter(ImageJob.id != current_job_id)
        .all()
    )

    best_match_id = None
    best_distance = None
    for job in prior_jobs:
        try:
            other_hash = imagehash.hex_to_hash(job.perceptual_hash)
        except ValueError:
            continue
        distance = new_hash_obj - other_hash
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_match_id = job.id

    is_duplicate = best_distance is not None and best_distance <= DUPLICATE_HASH_DISTANCE

    return {
        "check": "duplicate",
        "hash": new_hash,
        "closest_match_id": best_match_id if is_duplicate else None,
        "hamming_distance": best_distance,
        "is_duplicate": bool(is_duplicate),
    }
