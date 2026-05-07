"""Background job status and downloads."""

from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from celery.result import AsyncResult

from celery_app import celery_app
import schemas
from services.integrations.storage import presigned_url


def job_status(task_id: str) -> schemas.JobStatusResponse:
    result = AsyncResult(task_id, app=celery_app)
    state = result.state

    response = schemas.JobStatusResponse(task_id=task_id, status=state)

    if state == "SUCCESS":
        file_info = result.result or {}
        response.result = {k: v for k, v in file_info.items() if k != "s3_key"}
        if "s3_key" in file_info:
            response.download_url = f"/api/v1/jobs/{task_id}/download"

    elif state == "FAILURE":
        response.error = str(result.info)

    return response


def job_download(task_id: str) -> RedirectResponse:
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

    url = presigned_url(
        key=s3_key,
        filename=file_info.get("filename", "download"),
        content_type=file_info.get("content_type", "application/octet-stream"),
        expiry=3600,
    )
    return RedirectResponse(url=url, status_code=307)
