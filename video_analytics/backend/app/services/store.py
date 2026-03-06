from datetime import datetime, timedelta
from glob import glob
from pathlib import Path
from threading import RLock
from uuid import uuid4
import json
import os

from fastapi import UploadFile

from app.core.config import ANALYTICS_STORE, OUTPUT_DIR, SUPPORTED_USE_CASES, SUPPORTED_VIDEO_EXTENSIONS


records_lock = RLock()
jobs_lock = RLock()
camera_lock = RLock()
JOBS: dict[str, dict] = {}
CONNECTED_CAMERAS: dict[str, dict] = {}


OUTPUT_DIR_STR = str(OUTPUT_DIR)
ANALYTICS_STORE_STR = str(ANALYTICS_STORE)
CONNECTED_CAMERAS_STORE_STR = os.path.join(OUTPUT_DIR_STR, "connected_cameras.json")


def ensure_storage_dirs() -> None:
    Path(OUTPUT_DIR_STR).mkdir(parents=True, exist_ok=True)
    _load_connected_cameras_from_disk()


def _load_connected_cameras_from_disk() -> None:
    with camera_lock:
        if not os.path.exists(CONNECTED_CAMERAS_STORE_STR):
            CONNECTED_CAMERAS.clear()
            return

        try:
            with open(CONNECTED_CAMERAS_STORE_STR, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            CONNECTED_CAMERAS.clear()
            return

        if isinstance(data, dict):
            CONNECTED_CAMERAS.clear()
            for camera_id, camera in data.items():
                if isinstance(camera, dict):
                    camera_copy = dict(camera)
                    camera_copy["camera_id"] = camera_copy.get("camera_id") or camera_id
                    CONNECTED_CAMERAS[camera_copy["camera_id"]] = camera_copy
            return

        CONNECTED_CAMERAS.clear()


def _save_connected_cameras_to_disk() -> None:
    with open(CONNECTED_CAMERAS_STORE_STR, "w", encoding="utf-8") as f:
        json.dump(CONNECTED_CAMERAS, f, ensure_ascii=True, indent=2)


def load_analytics_records():
    with records_lock:
        if not os.path.exists(ANALYTICS_STORE_STR):
            return []

        try:
            with open(ANALYTICS_STORE_STR, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except json.JSONDecodeError:
            pass

        return []


def save_analytics_records(records):
    with records_lock:
        with open(ANALYTICS_STORE_STR, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=True, indent=2)


def append_video_record(video_name, person_count, status, input_path="", output_path="", details=None, record_id=""):
    record_id = record_id or str(uuid4())
    with records_lock:
        records = load_analytics_records()
        records.append({
            "id": record_id,
            "video_name": video_name,
            "person_count": int(person_count),
            "status": status,
            "created_at": datetime.utcnow().isoformat(),
            "input_path": input_path,
            "output_path": output_path,
            "details": details or {},
        })
        save_analytics_records(records)
    return record_id


def update_video_record(record_id, **updates):
    with records_lock:
        records = load_analytics_records()
        updated = False
        for record in records:
            if record.get("id") == record_id:
                record.update(updates)
                updated = True
                break

        if updated:
            save_analytics_records(records)

        return updated


def set_job_state(job_id, **updates):
    with jobs_lock:
        current = JOBS.get(job_id, {"job_id": job_id})
        current.update(updates)
        current["updated_at"] = datetime.utcnow().isoformat()
        JOBS[job_id] = current


def get_job_state(job_id):
    with jobs_lock:
        state = JOBS.get(job_id)
        return dict(state) if state else None


def pop_job_state(job_id):
    with jobs_lock:
        JOBS.pop(job_id, None)


def set_connected_camera(camera_id: str, **camera_data):
    with camera_lock:
        current = CONNECTED_CAMERAS.get(camera_id, {"camera_id": camera_id})
        current.update(camera_data)
        current["updated_at"] = datetime.utcnow().isoformat()
        CONNECTED_CAMERAS[camera_id] = current
        _save_connected_cameras_to_disk()
        return dict(current)


def list_connected_cameras():
    with camera_lock:
        return [dict(camera) for camera in CONNECTED_CAMERAS.values()]


def get_connected_camera(camera_id: str):
    with camera_lock:
        camera = CONNECTED_CAMERAS.get(camera_id)
        return dict(camera) if camera else None


def delete_connected_camera(camera_id: str):
    with camera_lock:
        deleted = CONNECTED_CAMERAS.pop(camera_id, None) is not None
        if deleted:
            _save_connected_cameras_to_disk()
        return deleted


def normalize_use_cases(use_cases):
    if not use_cases:
        return []

    normalized = []
    for raw in use_cases:
        value = (raw or "").strip().lower().replace(" ", "_")
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def get_unsupported_use_cases(use_cases):
    return [use_case for use_case in use_cases if use_case not in SUPPORTED_USE_CASES]


def is_supported_video_upload(file: UploadFile):
    filename = os.path.basename(file.filename or "")
    extension = os.path.splitext(filename)[1].lower()
    content_type = (file.content_type or "").lower()
    return content_type.startswith("video/") or extension in SUPPORTED_VIDEO_EXTENSIONS


def resolve_processed_video_path(record):
    output_path = record.get("output_path", "")
    if output_path and os.path.exists(output_path):
        return f"/outputs/{os.path.basename(output_path)}"

    # Best effort fallback for legacy records without output_path metadata.
    video_name = record.get("video_name", "")
    video_stem = os.path.splitext(os.path.basename(video_name))[0]
    if not video_stem:
        return ""

    pattern = os.path.join(OUTPUT_DIR_STR, f"processed_*{video_stem}*.mp4")
    candidates = sorted(glob(pattern), key=os.path.getmtime, reverse=True)
    if not candidates:
        return ""

    return f"/outputs/{os.path.basename(candidates[0])}"


def build_analytics_payload():
    records = load_analytics_records()

    completed_records = [r for r in records if r.get("status") == "completed"]
    total_videos = len(completed_records)
    total_persons = sum(int(r.get("person_count", 0)) for r in completed_records)
    total_processing_time_seconds = sum(
        float((r.get("details", {}) or {}).get("duration_seconds") or 0)
        for r in completed_records
    )

    today = datetime.utcnow().date()
    todays_detections = 0
    for r in completed_records:
        try:
            created_day = datetime.fromisoformat(r.get("created_at", "")).date()
        except ValueError:
            continue
        if created_day == today:
            todays_detections += int(r.get("person_count", 0))

    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    hourly_analytics = []
    for hours_ago in range(11, -1, -1):
        hour_start = now - timedelta(hours=hours_ago)
        hour_end = hour_start + timedelta(hours=1)
        hour_uploads = 0
        hour_detections = 0

        for r in completed_records:
            try:
                created_at = datetime.fromisoformat(r.get("created_at", ""))
            except ValueError:
                continue
            if hour_start <= created_at < hour_end:
                hour_uploads += 1
                hour_detections += int(r.get("person_count", 0))

        hourly_analytics.append({
            "hour": hour_start.strftime("%H:00"),
            "detections": hour_detections,
            "uploads": hour_uploads,
        })

    person_count_per_video = [
        {
            "video": r.get("video_name", "unknown"),
            "count": int(r.get("person_count", 0)),
        }
        for r in completed_records[-10:]
    ]

    recent_uploads = []
    for r in reversed(records[-10:]):
        created_at = r.get("created_at", "")
        upload_date = created_at.split("T")[0] if "T" in created_at else created_at
        details = (r.get("details", {}) or {})
        requested_use_cases = details.get("requested_use_cases")
        normalized_use_cases = normalize_use_cases(requested_use_cases if isinstance(requested_use_cases, list) else [])
        recent_uploads.append({
            "id": r.get("id", ""),
            "videoName": r.get("video_name", "unknown"),
            "uploadDate": upload_date,
            "personCount": int(r.get("person_count", 0)),
            "status": r.get("status", "completed"),
            "processedVideo": resolve_processed_video_path(r),
            "processingTimeSeconds": float((r.get("details", {}) or {}).get("duration_seconds") or 0),
            "source": details.get("source", "upload_video"),
            "useCases": normalized_use_cases,
            "use_cases": normalized_use_cases,
        })

    return {
        "total_videos": total_videos,
        "total_persons": total_persons,
        "total_processing_time_seconds": total_processing_time_seconds,
        "active_cameras": len(list_connected_cameras()),
        "todays_detections": todays_detections,
        "hourly_analytics": hourly_analytics,
        "person_count_per_video": person_count_per_video,
        "recent_uploads": recent_uploads,
    }
