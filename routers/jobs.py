"""
Job status & file download for background tasks.

Flow:
  1. Client calls an endpoint that dispatches heavy work (PDF, report, bulk upload).
     The endpoint returns immediately with {"task_id": "...", "status": "queued"}.
  2. Client polls  GET /api/v1/jobs/{task_id}  until status == "SUCCESS" | "FAILURE".
  3. For file-producing tasks, client calls  GET /api/v1/jobs/{task_id}/download
     which redirects to a short-lived S3 presigned URL (valid 1 hour).
"""
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from celery_app import celery_app
from dependencies import get_current_user
import models
import schemas

router = APIRouter(prefix="/jobs", tags=["Background Jobs"])


@router.get("/{task_id}", response_model=schemas.JobStatusResponse)
def job_status(task_id: str, _: models.User = Depends(get_current_user)):
    """Poll the status of any background task."""
    result = AsyncResult(task_id, app=celery_app)
    state = result.state  # PENDING | STARTED | SUCCESS | FAILURE | RETRY

    response = schemas.JobStatusResponse(task_id=task_id, status=state)

    if state == "SUCCESS":
        file_info = result.result or {}
        # Expose filename/content_type but not the internal S3 key
        response.result = {
            k: v for k, v in file_info.items() if k != "s3_key"
        }
        if "s3_key" in file_info:
            response.download_url = f"/api/v1/jobs/{task_id}/download"

    elif state == "FAILURE":
        response.error = str(result.info)

    return response


@router.get("/{task_id}/download")
def job_download(task_id: str, _: models.User = Depends(get_current_user)):
    """
    Redirect to a presigned S3 URL for the file produced by a completed background task.
    The URL is valid for 1 hour.
    """
    result = AsyncResult(task_id, app=celery_app)

    if result.state != "SUCCESS":
        raise HTTPException(
            status_code=409,
            detail=f"Job not complete (status: {result.state}). Poll /jobs/{task_id} first.",
        )

    file_info = result.result or {}
    s3_key = file_info.get("s3_key")

    if not s3_key:
        raise HTTPException(
            status_code=404,
            detail="No downloadable file for this job.",
        )

    from utils.s3 import presigned_url
    url = presigned_url(
        key=s3_key,
        filename=file_info.get("filename", "download"),
        content_type=file_info.get("content_type", "application/octet-stream"),
        expiry=3600,
    )
    return RedirectResponse(url=url, status_code=307)
