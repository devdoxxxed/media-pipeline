import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, DateTime, Enum, JSON, Text
from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ImageJob(Base):
    __tablename__ = "image_jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    original_filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.pending, nullable=False, index=True)

    perceptual_hash = Column(String, nullable=True, index=True)  # set once analysis runs
    results = Column(JSON, nullable=True)
    verdict = Column(String, nullable=True)  # "clean" | "flagged"
    failure_reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
