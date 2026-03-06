from datetime import datetime
from uuid import uuid4
import os
import shutil

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import FRAME_STRIDE, SUPPORTED_USE_CASES, UPLOAD_DIR
from app.services.jobs import process_video_job
from app.services.store import (
    append_video_record,
    get_unsupported_use_cases,
    is_supported_video_upload,
    normalize_use_cases,
    set_job_state,
)


router = APIRouter()


@router.post("/upload-video")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    use_cases: list[str] = Form(...),
):
    if not is_supported_video_upload(file):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload a common video format such as MP4, AVI, MOV, MKV, WEBM, FLV, WMV, or MPEG.",
        )

    normalized_use_cases = normalize_use_cases(use_cases)
    if not normalized_use_cases:
        raise HTTPException(status_code=400, detail="At least one use case must be selected.")

    unsupported_use_cases = get_unsupported_use_cases(normalized_use_cases)
    if unsupported_use_cases:
        supported_list = ", ".join(sorted(SUPPORTED_USE_CASES))
        invalid_list = ", ".join(unsupported_use_cases)
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported use case(s): {invalid_list}. Supported use cases: {supported_list}.",
        )

    safe_name = os.path.basename(file.filename or "upload_video.mp4")
    unique_input_name = f"{uuid4().hex}_{safe_name}"
    input_path = os.path.join(str(UPLOAD_DIR), unique_input_name)

    with open(input_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    job_id = str(uuid4())
    record_id = append_video_record(
        video_name=safe_name,
        person_count=0,
        status="processing",
        input_path=input_path,
        details={
            "requested_use_cases": normalized_use_cases,
            "source": "upload_video",
        },
        record_id=job_id,
    )

    set_job_state(
        job_id,
        record_id=record_id,
        video_name=safe_name,
        status="processing",
        progress=0,
        frame_stride=FRAME_STRIDE,
        requested_use_cases=normalized_use_cases,
        started_at=datetime.utcnow().isoformat(),
    )
    background_tasks.add_task(process_video_job, job_id, record_id, safe_name, input_path, normalized_use_cases)

    return JSONResponse(
        {
            "message": "Video accepted for processing",
            "job_id": job_id,
            "status": "processing",
            "frame_stride": FRAME_STRIDE,
            "use_cases": normalized_use_cases,
        }
    )
