import shutil
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import UPLOAD_DIR
from app.database import SessionLocal
from app.models import ImageJob
from app.worker import enqueue, start_worker


FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"

SAMPLE_IMAGES = [
    "image-1.jpeg",
    "image-2.jpeg",
    "image-3.jpeg",
]


def seed():
    # Start the same background worker used by the API.
    start_worker()

    db = SessionLocal()

    try:
        created_jobs = []

        for filename in SAMPLE_IMAGES:

            source = FIXTURE_DIR / filename

            if not source.exists():
                print(f"Skipping missing fixture: {source}")
                continue

            job_id = str(uuid.uuid4())

            destination = Path(UPLOAD_DIR) / f"{job_id}_{filename}"

            shutil.copy2(
                source,
                destination,
            )

            job = ImageJob(
                id=job_id,
                original_filename=filename,
                stored_path=str(destination),
            )

            db.add(job)
            db.commit()

            enqueue(job_id)

            created_jobs.append(job_id)

            print(f"Seeded: {filename}")
            print(f"Job ID: {job_id}")
            print()

        print(f"Created {len(created_jobs)} sample jobs.")
        print("\nWaiting for sample jobs to finish...")

        from app.worker import job_queue
        job_queue.join()

        print("All sample jobs completed.")
        print("\nUse these IDs with:")
        print("GET /status/{id}")
        print("GET /results/{id}")

    finally:
        db.close()


if __name__ == "__main__":
    seed()