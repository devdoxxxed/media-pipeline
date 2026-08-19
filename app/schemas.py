from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class UploadResponse(BaseModel):
    id: str
    status: str
    message: str = "Upload accepted. Processing started asynchronously."


class StatusResponse(BaseModel):
    id: str
    status: str
    original_filename: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ResultsResponse(BaseModel):
    id: str
    status: str
    verdict: Optional[str] = None
    results: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class FailureResponse(BaseModel):
    id: str
    status: str
    failure_reason: Optional[str] = None

    class Config:
        from_attributes = True
