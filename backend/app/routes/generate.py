"""Generation endpoints — start pipeline jobs and poll status."""

from fastapi import APIRouter, File, Form, UploadFile

router = APIRouter(prefix="/api", tags=["generate"])


@router.post("/generate", status_code=202)
async def generate_from_username(username: str):
    """Start room generation from an Instagram username.

    Deduplication:
    - If a job is already in-progress for this username, returns 200 with existing job_id.
    - If a room is already completed for this username, returns 200 with job_id + room_id.
    """
    # TODO: check for existing job/room by username
    # TODO: enqueue pipeline job
    return {"job_id": "not_implemented", "existing": False}


@router.post("/generate/upload", status_code=202)
async def generate_from_upload(
    photos: list[UploadFile] = File(...),
    bio: str = Form(default=""),
):
    """Start room generation from uploaded photos + optional bio."""
    # TODO: enqueue pipeline job
    return {"job_id": "not_implemented", "existing": False}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Poll job status and progress."""
    # TODO: look up job state
    return {
        "job_id": job_id,
        "username": None,
        "status": "not_implemented",
        "stage": None,
        "progress": None,
        "result": None,
        "error": None,
    }
