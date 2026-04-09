"""
Job status & file download for background tasks.

Flow:
  1. Client calls an endpoint that dispatches heavy work (PDF, report, bulk upload).
     The endpoint returns immediately with {"task_id": "...", "status": "queued"}.
  2. Client polls  GET /api/v1/jobs/{task_id}  until status == "SUCCESS" | "FAILURE".
  3. For file-producing tasks, client calls  GET /api/v1/jobs/{task_id}/download.
"""
import os

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

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
        # Expose filename/content_type but not the internal file path
        response.result = {
            k: v for k, v in file_info.items() if k != "filepath"
        }
        if "filepath" in file_info:
            response.download_url = f"/api/v1/jobs/{task_id}/download"

    elif state == "FAILURE":
        response.error = str(result.info)

    return response


@router.get("/{task_id}/download")
def job_download(task_id: str, _: models.User = Depends(get_current_user)):
    """Download the file produced by a completed background task."""
    result = AsyncResult(task_id, app=celery_app)

    if result.state != "SUCCESS":
        raise HTTPException(
            status_code=409,
            detail=f"Job not complete (status: {result.state}). Poll /jobs/{task_id} first.",
        )

    file_info = result.result or {}
    filepath = file_info.get("filepath")

    if not filepath or not os.path.exists(filepath):
        raise HTTPException(
            status_code=404,
            detail="Result file not found. It may have expired (files are kept for 2 hours).",
        )

    return FileResponse(
        path=filepath,
        filename=file_info.get("filename", "download"),
        media_type=file_info.get("content_type", "application/octet-stream"),
    )
