from datetime import datetime
import os

from app.core.config import EXECUTABLE_VIDEO_USE_CASES, FRAME_STRIDE, OUTPUT_DIR
from app.services.store import normalize_use_cases, set_job_state, update_video_record
from src.person_count import process_video


def process_video_job(job_id, record_id, safe_name, input_path, use_cases=None):
    requested_use_cases = normalize_use_cases(use_cases)
    executable_use_cases = [use_case for use_case in requested_use_cases if use_case in EXECUTABLE_VIDEO_USE_CASES]
    skipped_use_cases = [use_case for use_case in requested_use_cases if use_case not in executable_use_cases]

    set_job_state(
        job_id,
        record_id=record_id,
        video_name=safe_name,
        status="processing",
        progress=0,
        frame_stride=FRAME_STRIDE,
        requested_use_cases=requested_use_cases,
        started_at=datetime.utcnow().isoformat(),
    )

    if not executable_use_cases:
        error_message = "Selected use case(s) are not executable for video processing yet."
        update_video_record(
            record_id,
            person_count=0,
            status="failed",
            details={
                "error": error_message,
                "requested_use_cases": requested_use_cases,
                "executed_use_cases": [],
                "skipped_use_cases": skipped_use_cases,
            },
            completed_at=datetime.utcnow().isoformat(),
        )
        set_job_state(
            job_id,
            status="failed",
            error=error_message,
            requested_use_cases=requested_use_cases,
            executed_use_cases=[],
            skipped_use_cases=skipped_use_cases,
            completed_at=datetime.utcnow().isoformat(),
        )
        return

    def on_progress(progress, processed_frames, total_frames):
        set_job_state(
            job_id,
            status="processing",
            progress=progress,
            processed_frames=processed_frames,
            total_frames=total_frames,
        )

    try:
        total_count = 0
        details = {
            "requested_use_cases": requested_use_cases,
            "executed_use_cases": executable_use_cases,
            "skipped_use_cases": skipped_use_cases,
        }
        output_path = ""

        if "person_count" in executable_use_cases:
            output_path, total_count, person_count_details = process_video(
                input_path,
                str(OUTPUT_DIR),
                frame_stride=FRAME_STRIDE,
                progress_callback=on_progress,
            )
            details = {
                **details,
                **person_count_details,
            }

        update_video_record(
            record_id,
            person_count=total_count,
            status="completed",
            output_path=output_path,
            details=details,
            completed_at=datetime.utcnow().isoformat(),
        )
        set_job_state(
            job_id,
            status="completed",
            progress=100,
            total_person_count=total_count,
            processed_video=f"/outputs/{os.path.basename(output_path)}",
            requested_use_cases=requested_use_cases,
            executed_use_cases=executable_use_cases,
            skipped_use_cases=skipped_use_cases,
            completed_at=datetime.utcnow().isoformat(),
        )
    except ValueError as exc:
        update_video_record(
            record_id,
            person_count=0,
            status="failed",
            details={
                "error": str(exc),
                "requested_use_cases": requested_use_cases,
                "executed_use_cases": executable_use_cases,
                "skipped_use_cases": skipped_use_cases,
            },
            completed_at=datetime.utcnow().isoformat(),
        )
        set_job_state(
            job_id,
            status="failed",
            error=str(exc),
            requested_use_cases=requested_use_cases,
            executed_use_cases=executable_use_cases,
            skipped_use_cases=skipped_use_cases,
            completed_at=datetime.utcnow().isoformat(),
        )
    except Exception:
        update_video_record(
            record_id,
            person_count=0,
            status="failed",
            details={
                "error": "Video processing failed.",
                "requested_use_cases": requested_use_cases,
                "executed_use_cases": executable_use_cases,
                "skipped_use_cases": skipped_use_cases,
            },
            completed_at=datetime.utcnow().isoformat(),
        )
        set_job_state(
            job_id,
            status="failed",
            error="Video processing failed.",
            requested_use_cases=requested_use_cases,
            executed_use_cases=executable_use_cases,
            skipped_use_cases=skipped_use_cases,
            completed_at=datetime.utcnow().isoformat(),
        )
