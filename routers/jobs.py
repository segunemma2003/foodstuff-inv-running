"""
Job status & file download for background tasks.

Flow:
  1. Client calls an endpoint that dispatches heavy work (PDF, report, bulk upload).
     The endpoint returns immediately with {"task_id": "...", "status": "queued"}.
  2. Client polls  GET /api/v1/jobs/{task_id}  until status == "SUCCESS" | "FAILURE".
  3. For file-producing tasks, client calls  GET /api/v1/jobs/{task_id}/download
     which redirects to a short-lived S3 presigned URL (valid 1 hour).
"""
from fastapi import APIRouter, Depends

from dependencies import get_current_user
import models
import schemas
from services import job_service

router = APIRouter(prefix="/jobs", tags=["Background Jobs"])


@router.get("/{task_id}", response_model=schemas.JobStatusResponse)
def job_status(task_id: str, _: models.User = Depends(get_current_user)):
    """Poll the status of any background task."""
    return job_service.job_status(task_id)


@router.get("/{task_id}/download")
def job_download(task_id: str, _: models.User = Depends(get_current_user)):
    """
    Redirect to a presigned S3 URL for the file produced by a completed background task.
    The URL is valid for 1 hour.
    """
    return job_service.job_download(task_id)
