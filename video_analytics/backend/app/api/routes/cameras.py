import asyncio
from datetime import datetime
from fractions import Fraction
import importlib
import os
import subprocess
from threading import Event, Lock, Thread
from time import sleep
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

import cv2
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import OUTPUT_DIR, SUPPORTED_USE_CASES
from src.person_count.count import model as person_count_model
from app.services.store import (
    append_video_record,
    delete_connected_camera,
    get_unsupported_use_cases,
    get_connected_camera,
    load_analytics_records,
    list_connected_cameras,
    normalize_use_cases,
    records_lock,
    save_analytics_records,
    set_connected_camera,
    update_video_record,
)


router = APIRouter(prefix="/api")
CAMERA_PEER_CONNECTIONS: dict[str, set] = {}
LIVE_CAMERA_RECORDERS: dict[str, dict] = {}
LIVE_CAMERA_RECORDERS_LOCK = Lock()
CAMERA_STREAMS: dict[str, "CameraStream"] = {}
CAMERA_STREAMS_LOCK = Lock()
SHUTDOWN_IN_PROGRESS = Event()


class CameraConnectRequest(BaseModel):
    rtsp_url: str = Field(min_length=8)
    camera_name: str | None = None
    use_cases: list[str] = Field(default_factory=lambda: ["person_count"])


class WebRTCOfferRequest(BaseModel):
    sdp: str
    type: str


class CameraStream:
    def __init__(self, camera_id: str, rtsp_url: str):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.stop_event = Event()
        self.frame_lock = Lock()
        self.frame = None
        self.last_frame_at = 0.0
        self.source_fps = 0.0
        self.thread = Thread(
            target=self._run,
            daemon=True,
            name=f"camera-stream-{camera_id}",
        )
        self.thread.start()

    def _run(self):
        capture = _create_rtsp_capture(self.rtsp_url)
        failures = 0
        while not self.stop_event.is_set():
            if not capture.isOpened():
                capture.release()
                sleep(0.2)
                capture = _create_rtsp_capture(self.rtsp_url)
                continue

            ok, frame = capture.read()
            if not ok or frame is None:
                failures += 1
                if failures >= 30:
                    capture.release()
                    sleep(0.15)
                    capture = _create_rtsp_capture(self.rtsp_url)
                    failures = 0
                sleep(0.02)
                continue

            failures = 0
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            with self.frame_lock:
                self.frame = frame.copy()
                self.last_frame_at = datetime.utcnow().timestamp()
                if fps > 0:
                    self.source_fps = fps

        capture.release()

    def get_frame_copy(self):
        with self.frame_lock:
            if self.frame is None:
                return None
            return self.frame.copy()

    def get_source_fps(self) -> float:
        with self.frame_lock:
            return self.source_fps

    def stop(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=2.0)


def _ensure_camera_stream(camera_id: str, rtsp_url: str) -> CameraStream:
    with CAMERA_STREAMS_LOCK:
        stream = CAMERA_STREAMS.get(camera_id)
        if stream and stream.rtsp_url == rtsp_url and stream.thread.is_alive():
            return stream
        if stream:
            stream.stop()
        stream = CameraStream(camera_id=camera_id, rtsp_url=rtsp_url)
        CAMERA_STREAMS[camera_id] = stream
        return stream


def _stop_camera_stream(camera_id: str):
    with CAMERA_STREAMS_LOCK:
        stream = CAMERA_STREAMS.pop(camera_id, None)
    if stream:
        stream.stop()


def stop_all_camera_streams():
    with CAMERA_STREAMS_LOCK:
        camera_ids = list(CAMERA_STREAMS.keys())
    for camera_id in camera_ids:
        _stop_camera_stream(camera_id)


def recover_interrupted_live_recordings():
    now = datetime.utcnow().isoformat()
    updated = False
    with records_lock:
        records = load_analytics_records()
        for record in records:
            details = (record.get("details") or {})
            source = (details.get("source") or "").strip().lower()
            status = (record.get("status") or "").strip().lower()
            if source != "live_cctv" or status not in {"processing", "recording"}:
                continue

            output_path = (record.get("output_path") or "").strip()
            has_video = output_path and os.path.exists(output_path) and os.path.getsize(output_path) > 0
            details["recovered_after_restart"] = True

            if has_video:
                record["status"] = "completed"
                details["recovery_note"] = "Recovered live recording after backend restart."
            else:
                record["status"] = "failed"
                details["error"] = "Recording interrupted before any frames were saved."
            record["details"] = details
            record["completed_at"] = now
            updated = True

        if updated:
            save_analytics_records(records)


def _validate_rtsp_url(rtsp_url: str) -> None:
    normalized = rtsp_url.strip()
    if not normalized.lower().startswith("rtsp://"):
        raise HTTPException(status_code=400, detail="RTSP URL must start with rtsp://")

    parsed = urlparse(normalized)
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="RTSP URL is missing camera host/IP.")


def _build_candidate_rtsp_urls(rtsp_url: str) -> list[str]:
    candidates = [rtsp_url]
    parsed = urlparse(rtsp_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if query.get("rtsp_transport", "").lower() != "tcp":
        query["rtsp_transport"] = "tcp"
        tcp_query = urlencode(query)
        tcp_url = urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.params, tcp_query, parsed.fragment)
        )
        candidates.append(tcp_url)
    return candidates


def _create_rtsp_capture(rtsp_url: str):
    capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def _verify_rtsp_stream(rtsp_url: str) -> str:
    candidate_urls = _build_candidate_rtsp_urls(rtsp_url)
    attempts = 25

    for candidate in candidate_urls:
        capture = _create_rtsp_capture(candidate)
        try:
            if not capture.isOpened():
                continue

            for _ in range(attempts):
                ok, frame = capture.read()
                if ok and frame is not None:
                    return candidate
                sleep(0.2)
        finally:
            capture.release()

    raise HTTPException(
        status_code=400,
        detail=(
            "Could not connect camera stream. "
            "Tried default RTSP and TCP transport fallback but no frames were received."
        ),
    )


def _build_live_recording_paths(camera_name: str, camera_id: str, segment_started_at: datetime):
    safe_camera_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in camera_name).strip("_")
    safe_camera_name = safe_camera_name or f"camera_{camera_id[:8]}"
    timestamp = segment_started_at.strftime("%Y%m%d_%H%M%S")
    output_stem = f"live_recording_{safe_camera_name}_{camera_id[:8]}_{timestamp}"
    raw_output_path = os.path.join(str(OUTPUT_DIR), f"{output_stem}_raw.mp4")
    final_output_path = os.path.join(str(OUTPUT_DIR), f"{output_stem}.mp4")
    return output_stem, raw_output_path, final_output_path


def _finalize_live_recording_segment(
    record_id: str | None,
    raw_output_path: str | None,
    final_output_path: str | None,
    started_at: datetime | None,
    frame_count: int,
    source_fps: float,
    peak_person_count: int,
    camera_id: str,
    camera_name: str,
    use_cases: list[str],
) -> None:
    if not record_id or not raw_output_path or not started_at:
        return

    elapsed_seconds = max(0.0, (datetime.utcnow() - started_at).total_seconds())
    if frame_count <= 0:
        if os.path.exists(raw_output_path):
            os.remove(raw_output_path)
        update_video_record(
            record_id,
            status="failed",
            details={
                "error": "No frames were captured from live CCTV stream.",
                "source": "live_cctv",
                "camera_id": camera_id,
                "camera_name": camera_name,
                "requested_use_cases": use_cases,
                "duration_seconds": round(elapsed_seconds, 2),
            },
            completed_at=datetime.utcnow().isoformat(),
        )
        return

    output_path = raw_output_path
    should_transcode = bool(final_output_path) and not SHUTDOWN_IN_PROGRESS.is_set()
    if should_transcode and final_output_path:
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            raw_output_path,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            final_output_path,
        ]
        ffmpeg_result = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ffmpeg_result.returncode == 0 and os.path.exists(final_output_path):
            output_path = final_output_path
            if os.path.exists(raw_output_path):
                os.remove(raw_output_path)

    fps = source_fps if source_fps > 0 else 20.0
    recording_ended_at = datetime.utcnow()
    update_video_record(
        record_id,
        person_count=max(peak_person_count, 0),
        status="completed",
        output_path=output_path,
        details={
            "source": "live_cctv",
            "camera_id": camera_id,
            "camera_name": camera_name,
            "requested_use_cases": use_cases,
            "recording_date": started_at.date().isoformat(),
            "recording_started_at": started_at.isoformat(),
            "recording_ended_at": recording_ended_at.isoformat(),
            "fps": fps,
            "total_frames": frame_count,
            "duration_seconds": round(elapsed_seconds, 2),
            "peak_count": max(peak_person_count, 0),
        },
        completed_at=recording_ended_at.isoformat(),
    )


def _record_live_camera_stream(
    camera_id: str,
    camera_name: str,
    rtsp_url: str,
    use_cases: list[str],
    stop_event: Event,
):
    shared_stream = _ensure_camera_stream(camera_id, rtsp_url)
    source_fps = 0.0
    current_segment_date = datetime.now().date()
    current_record_id: str | None = None
    raw_output_path: str | None = None
    final_output_path: str | None = None
    segment_started_at: datetime | None = None
    frame_count = 0
    frame_index = 0
    last_person_count = 0
    peak_person_count = 0
    writer = None
    consecutive_failures = 0

    try:
        while not stop_event.is_set():
            frame = shared_stream.get_frame_copy()
            if frame is None:
                consecutive_failures += 1
                if consecutive_failures >= 40:
                    consecutive_failures = 0
                sleep(0.03)
                continue

            consecutive_failures = 0
            now_local = datetime.now()
            frame_date = now_local.date()

            if frame_date != current_segment_date:
                if writer:
                    writer.release()
                    writer = None
                _finalize_live_recording_segment(
                    record_id=current_record_id,
                    raw_output_path=raw_output_path,
                    final_output_path=final_output_path,
                    started_at=segment_started_at,
                    frame_count=frame_count,
                    source_fps=source_fps,
                    peak_person_count=peak_person_count,
                    camera_id=camera_id,
                    camera_name=camera_name,
                    use_cases=use_cases,
                )
                current_segment_date = frame_date
                current_record_id = None
                raw_output_path = None
                final_output_path = None
                segment_started_at = None
                frame_count = 0
                frame_index = 0
                last_person_count = 0
                peak_person_count = 0
                source_fps = 0.0

            if current_record_id is None:
                segment_started_at = datetime.utcnow()
                output_stem, raw_output_path, final_output_path = _build_live_recording_paths(
                    camera_name,
                    camera_id,
                    now_local,
                )
                current_record_id = append_video_record(
                    video_name=f"{output_stem}.mp4",
                    person_count=0,
                    status="processing",
                    output_path=raw_output_path,
                    details={
                        "source": "live_cctv",
                        "camera_id": camera_id,
                        "camera_name": camera_name,
                        "requested_use_cases": use_cases,
                        "recording_started_at": segment_started_at.isoformat(),
                    },
                )
                with LIVE_CAMERA_RECORDERS_LOCK:
                    recorder = LIVE_CAMERA_RECORDERS.get(camera_id)
                    if recorder is not None:
                        recorder["record_id"] = current_record_id

            if writer is None and raw_output_path:
                source_fps = shared_stream.get_source_fps()
                fps = source_fps if source_fps > 0 else 20.0
                height, width = frame.shape[:2]
                writer = cv2.VideoWriter(
                    raw_output_path,
                    cv2.VideoWriter_fourcc(*"mp4v"),
                    max(fps, 1.0),
                    (width, height),
                )
                if not writer.isOpened():
                    update_video_record(
                        current_record_id,
                        status="failed",
                        details={
                            "error": "Live camera recording failed because output writer could not be initialized.",
                            "source": "live_cctv",
                            "camera_id": camera_id,
                            "camera_name": camera_name,
                            "requested_use_cases": use_cases,
                        },
                        completed_at=datetime.utcnow().isoformat(),
                    )
                    current_record_id = None
                    raw_output_path = None
                    final_output_path = None
                    segment_started_at = None
                    frame_count = 0
                    frame_index = 0
                    last_person_count = 0
                    peak_person_count = 0
                    writer.release()
                    writer = None
                    sleep(0.05)
                    continue

            if writer:
                frame_index += 1
                enable_person_count = "person_count" in normalize_use_cases(use_cases)
                if enable_person_count and frame_index % 2 == 0:
                    results = person_count_model(frame, verbose=False)
                    person_count = 0
                    for result in results:
                        boxes = result.boxes
                        for box in boxes:
                            cls = int(box.cls[0])
                            if cls == 0:
                                person_count += 1
                                x1, y1, x2, y2 = map(int, box.xyxy[0])
                                conf = float(box.conf[0])
                                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                                cv2.putText(
                                    frame,
                                    f"Person {conf:.2f}",
                                    (x1, max(y1 - 8, 0)),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.45,
                                    (0, 255, 0),
                                    2,
                                )
                    last_person_count = person_count
                    peak_person_count = max(peak_person_count, person_count)

                cv2.putText(
                    frame,
                    f"Count: {last_person_count}",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 0, 255),
                    2,
                )
                writer.write(frame)
                frame_count += 1
    finally:
        if writer:
            writer.release()
        _finalize_live_recording_segment(
            record_id=current_record_id,
            raw_output_path=raw_output_path,
            final_output_path=final_output_path,
            started_at=segment_started_at,
            frame_count=frame_count,
            source_fps=source_fps,
            peak_person_count=peak_person_count,
            camera_id=camera_id,
            camera_name=camera_name,
            use_cases=use_cases,
        )


def _start_live_camera_recording(camera_id: str, camera_name: str, rtsp_url: str, use_cases: list[str]) -> str:
    _ensure_camera_stream(camera_id, rtsp_url)
    stop_event = Event()
    worker = Thread(
        target=_record_live_camera_stream,
        kwargs={
            "camera_id": camera_id,
            "camera_name": camera_name,
            "rtsp_url": rtsp_url,
            "use_cases": use_cases,
            "stop_event": stop_event,
        },
        daemon=True,
        name=f"live-camera-recorder-{camera_id}",
    )
    worker.start()

    with LIVE_CAMERA_RECORDERS_LOCK:
        LIVE_CAMERA_RECORDERS[camera_id] = {
            "stop_event": stop_event,
            "thread": worker,
            "record_id": None,
        }

    return ""


def _stop_live_camera_recording(camera_id: str):
    with LIVE_CAMERA_RECORDERS_LOCK:
        recorder = LIVE_CAMERA_RECORDERS.pop(camera_id, None)

    if not recorder:
        _stop_camera_stream(camera_id)
        return

    stop_event = recorder.get("stop_event")
    worker = recorder.get("thread")
    if stop_event:
        stop_event.set()
    if worker and worker.is_alive():
        # Wait until recorder thread exits so current segment is finalized and saved.
        worker.join()
    _stop_camera_stream(camera_id)


def stop_all_live_camera_recordings():
    SHUTDOWN_IN_PROGRESS.set()
    with LIVE_CAMERA_RECORDERS_LOCK:
        camera_ids = list(LIVE_CAMERA_RECORDERS.keys())

    for camera_id in camera_ids:
        _stop_live_camera_recording(camera_id)
    stop_all_camera_streams()


def resume_live_camera_recordings():
    SHUTDOWN_IN_PROGRESS.clear()
    cameras = list_connected_cameras()
    for camera in cameras:
        camera_id = (camera.get("camera_id") or "").strip()
        rtsp_url = (camera.get("rtsp_url") or "").strip()
        status = (camera.get("status") or "").strip().lower()
        if not camera_id or not rtsp_url:
            continue
        if status and status != "connected":
            continue

        with LIVE_CAMERA_RECORDERS_LOCK:
            existing = LIVE_CAMERA_RECORDERS.get(camera_id)
            if existing and existing.get("thread") and existing["thread"].is_alive():
                continue

        camera_name = (camera.get("camera_name") or "").strip() or f"Camera-{camera_id[:8]}"
        normalized_use_cases = normalize_use_cases(camera.get("use_cases"))
        _start_live_camera_recording(
            camera_id=camera_id,
            camera_name=camera_name,
            rtsp_url=rtsp_url,
            use_cases=normalized_use_cases or ["person_count"],
        )
        set_connected_camera(camera_id, status="connected")


def _create_webrtc_track(camera_id: str, rtsp_url: str, enable_person_count: bool):
    try:
        aiortc_module = importlib.import_module("aiortc")
        aiortc_media_module = importlib.import_module("aiortc.mediastreams")
        av_module = importlib.import_module("av")
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "WebRTC dependencies are not installed on backend environment. "
                "Install `aiortc` and `av` in backend venv."
            ),
        ) from exc

    VideoStreamTrack = getattr(aiortc_module, "VideoStreamTrack")
    MediaStreamError = getattr(aiortc_media_module, "MediaStreamError")
    VideoFrame = getattr(av_module, "VideoFrame")

    class CameraVideoTrack(VideoStreamTrack):
        def __init__(self):
            super().__init__()
            self.camera_id = camera_id
            self.enable_person_count = enable_person_count
            self.shared_stream = _ensure_camera_stream(camera_id, rtsp_url)
            self.frame_index = 0
            self.last_person_count = 0
            self.cumulative_person_count = 0
            self.started_at = datetime.utcnow()
            self.closed = False

        async def recv(self):
            if self.closed:
                raise MediaStreamError

            pts, time_base = await self.next_timestamp()

            for _ in range(20):
                frame = self.shared_stream.get_frame_copy()
                if frame is not None:
                    break
                await asyncio.sleep(0.02)
            else:
                raise MediaStreamError

            self.frame_index += 1
            if self.enable_person_count and self.frame_index % 2 == 0:
                results = person_count_model(frame, verbose=False)
                person_count = 0
                for result in results:
                    boxes = result.boxes
                    for box in boxes:
                        cls = int(box.cls[0])
                        if cls == 0:
                            person_count += 1
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            conf = float(box.conf[0])
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(
                                frame,
                                f"Person {conf:.2f}",
                                (x1, max(y1 - 8, 0)),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.45,
                                (0, 255, 0),
                                2,
                            )
                self.last_person_count = person_count

            self.cumulative_person_count += max(self.last_person_count, 0)
            elapsed_seconds = int((datetime.utcnow() - self.started_at).total_seconds())
            if self.frame_index % 5 == 0:
                set_connected_camera(
                    self.camera_id,
                    current_person_count=self.last_person_count,
                    total_person_count=self.cumulative_person_count,
                    total_frames=self.frame_index,
                    processing_time_seconds=max(elapsed_seconds, 0),
                )

            cv2.putText(
                frame,
                f"Count: {self.last_person_count}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                2,
            )

            video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
            video_frame.pts = pts
            video_frame.time_base = time_base if time_base is not None else Fraction(1, 90000)
            return video_frame

        def stop(self):
            self.closed = True
            super().stop()

    return CameraVideoTrack()


def _generate_mjpeg_frames(camera_id: str, rtsp_url: str, enable_person_count: bool):
    shared_stream = _ensure_camera_stream(camera_id, rtsp_url)

    frame_index = 0
    last_person_count = 0
    cumulative_person_count = 0
    stream_started_at = datetime.utcnow()

    while True:
        frame = shared_stream.get_frame_copy()
        if frame is None:
            sleep(0.1)
            continue

        frame_index += 1
        if enable_person_count and frame_index % 2 == 0:
            results = person_count_model(frame, verbose=False)
            person_count = 0
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    cls = int(box.cls[0])
                    if cls == 0:
                        person_count += 1
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        conf = float(box.conf[0])
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(
                            frame,
                            f"Person {conf:.2f}",
                            (x1, max(y1 - 8, 0)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.45,
                            (0, 255, 0),
                            2,
                        )
            last_person_count = person_count

        cumulative_person_count += max(last_person_count, 0)
        elapsed_seconds = int((datetime.utcnow() - stream_started_at).total_seconds())
        if frame_index % 5 == 0:
            set_connected_camera(
                camera_id,
                current_person_count=last_person_count,
                total_person_count=cumulative_person_count,
                total_frames=frame_index,
                processing_time_seconds=max(elapsed_seconds, 0),
            )

        cv2.putText(
            frame,
            f"Count: {last_person_count}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            2,
        )

        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            continue

        frame_bytes = buffer.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )


@router.post("/cameras/connect")
async def connect_camera(payload: CameraConnectRequest):
    rtsp_url = payload.rtsp_url.strip()
    normalized_use_cases = normalize_use_cases(payload.use_cases)
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

    _validate_rtsp_url(rtsp_url)
    verified_rtsp_url = _verify_rtsp_stream(rtsp_url)

    parsed = urlparse(verified_rtsp_url)
    camera_id = str(uuid4())
    camera_name = (payload.camera_name or "").strip() or f"Camera-{camera_id[:8]}"
    safe_stream_url = f"rtsp://{parsed.hostname}:{parsed.port or 554}{parsed.path or ''}"
    _start_live_camera_recording(
        camera_id=camera_id,
        camera_name=camera_name,
        rtsp_url=verified_rtsp_url,
        use_cases=normalized_use_cases,
    )
    camera = set_connected_camera(
        camera_id,
        camera_name=camera_name,
        rtsp_url=verified_rtsp_url,
        host=parsed.hostname,
        port=parsed.port or 554,
        status="connected",
        use_cases=normalized_use_cases,
        connected_at=datetime.utcnow().isoformat(),
    )

    return JSONResponse(
        {
            "success": True,
            "message": f"{camera_name} connected successfully.",
            "camera_id": camera_id,
            "stream_url": safe_stream_url,
            "use_cases": normalized_use_cases,
            "data": camera,
        }
    )


@router.get("/cameras")
async def get_connected_cameras():
    cameras = list_connected_cameras()
    return JSONResponse(
        {
            "success": True,
            "message": "Connected cameras fetched successfully.",
            "data": cameras,
        }
    )


@router.get("/cameras/{camera_id}")
async def get_camera(camera_id: str):
    camera = get_connected_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found.")

    return JSONResponse(
        {
            "success": True,
            "message": "Camera fetched successfully.",
            "data": camera,
        }
    )


@router.get("/cameras/{camera_id}/stream")
async def get_camera_stream(camera_id: str):
    camera = get_connected_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found.")

    rtsp_url = (camera.get("rtsp_url") or "").strip()
    if not rtsp_url:
        raise HTTPException(status_code=400, detail="Camera stream URL not available.")

    return StreamingResponse(
        _generate_mjpeg_frames(
            camera_id,
            rtsp_url,
            enable_person_count="person_count" in normalize_use_cases(camera.get("use_cases")),
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


@router.post("/cameras/{camera_id}/webrtc-offer")
async def create_webrtc_offer(camera_id: str, payload: WebRTCOfferRequest):
    camera = get_connected_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found.")

    rtsp_url = (camera.get("rtsp_url") or "").strip()
    if not rtsp_url:
        raise HTTPException(status_code=400, detail="Camera stream URL not available.")

    try:
        aiortc_module = importlib.import_module("aiortc")
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "WebRTC dependencies are not installed on backend environment. "
                "Install `aiortc` and `av` in backend venv."
            ),
        ) from exc

    RTCPeerConnection = getattr(aiortc_module, "RTCPeerConnection")
    RTCSessionDescription = getattr(aiortc_module, "RTCSessionDescription")

    pc = RTCPeerConnection()
    track = _create_webrtc_track(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        enable_person_count="person_count" in normalize_use_cases(camera.get("use_cases")),
    )
    pc.addTrack(track)
    CAMERA_PEER_CONNECTIONS.setdefault(camera_id, set()).add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState in {"failed", "closed", "disconnected"}:
            track.stop()
            await pc.close()
            peers = CAMERA_PEER_CONNECTIONS.get(camera_id, set())
            peers.discard(pc)
            if not peers:
                CAMERA_PEER_CONNECTIONS.pop(camera_id, None)

    try:
        await pc.setRemoteDescription(RTCSessionDescription(sdp=payload.sdp, type=payload.type))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return JSONResponse(
            {
                "success": True,
                "message": "WebRTC answer created.",
                "data": {
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type,
                },
            }
        )
    except Exception as exc:
        track.stop()
        await pc.close()
        peers = CAMERA_PEER_CONNECTIONS.get(camera_id, set())
        peers.discard(pc)
        if not peers:
            CAMERA_PEER_CONNECTIONS.pop(camera_id, None)
        raise HTTPException(status_code=500, detail=f"Failed to setup WebRTC session: {exc}")


@router.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str):
    _stop_live_camera_recording(camera_id)
    deleted = delete_connected_camera(camera_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Camera not found.")

    return JSONResponse(
        {
            "success": True,
            "message": "Camera removed and current recording saved successfully.",
        }
    )
