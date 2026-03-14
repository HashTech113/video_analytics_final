import asyncio
from datetime import datetime
from fractions import Fraction
import importlib
import os
from threading import Event, Lock, Thread
from time import monotonic, sleep
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

import cv2
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import SUPPORTED_USE_CASES
from app.services.store import (
    delete_connected_camera,
    get_connected_camera,
    get_unsupported_use_cases,
    list_connected_cameras,
    normalize_use_cases,
    set_connected_camera,
)
from src.person_count import PersonCounter, run_tracked_count_step
from src.person_recognition.bytetrack_tracker import ByteTrackFaceTracker


router = APIRouter(prefix="/api")

CAMERA_PEER_CONNECTIONS: dict[str, set] = {}
CAMERA_STREAMS: dict[str, "CameraStream"] = {}
CAMERA_STREAMS_LOCK = Lock()

RECOGNITION_SERVICE = None
RECOGNITION_SERVICE_INIT_FAILED = False
RECOGNITION_SERVICE_LOCK = Lock()


class CameraConnectRequest(BaseModel):
    rtsp_url: str = Field(min_length=8)
    camera_name: str | None = None
    use_cases: list[str] = Field(default_factory=lambda: ["person_count"])


class CameraUpdateRequest(BaseModel):
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

        self.processor = CameraFrameProcessor(camera_id=camera_id)

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


class CameraFrameProcessor:
    """
    Keeps stable state for each camera:
    - runs detection only at intervals
    - updates tracker with detections
    - draws tracked boxes on every frame
    """

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.lock = Lock()

        self.frame_index = 0
        self.detection_frame_stride = 2
        self.max_track_stale_seconds = 0.8
        self.max_missing_detection_cycles = 5
        self.missing_detection_cycles = 0
        self.last_tracks_at = 0.0
        self.person_tracks = []
        self.last_person_count = 0
        self.total_person_count = 0
        self.last_known_count = 0
        self.last_unknown_count = 0
        self.face_tracks = []
        self.last_face_tracks_at = 0.0
        self.max_face_track_stale_seconds = 0.8
        self.started_at = datetime.utcnow()
        self.tracker = ByteTrackFaceTracker(
            track_thresh=0.25,
            track_buffer=30,
            match_thresh=0.8,
            frame_rate=30,
            fallback_iou_threshold=0.3,
            fallback_center_distance_threshold=120,
            smoothing_alpha=0.6,
        )
        self.counter = PersonCounter(min_hits=3, max_idle_seconds=2.0)

    def process(self, frame, enable_person_count: bool, enable_person_recognition: bool):
        with self.lock:
            self.frame_index += 1
            now = monotonic()

            if enable_person_count:
                if self._should_run_detection():
                    self._update_person_tracks(frame, now)
                else:
                    self._predict_person_tracks(now)

            if enable_person_recognition and self.frame_index % 4 == 0:
                known_count, unknown_count, face_results = _run_person_recognition(frame)
                self.last_known_count = known_count
                self.last_unknown_count = unknown_count
                self.face_tracks = face_results
                self.last_face_tracks_at = now

            if not enable_person_recognition:
                self.face_tracks = []

            self._prune_stale_tracks(now)
            self.counter.cleanup(now)

            annotated = frame.copy()
            self._draw_person_tracks(annotated)
            self._draw_face_tracks(annotated, now)

            metrics: list[tuple[str, int]] = []
            if enable_person_count:
                metrics.append(("Count", self.last_person_count))
            if enable_person_recognition:
                metrics.append(("Known", self.last_known_count))
                metrics.append(("Unknown", self.last_unknown_count))
            _draw_top_right_metrics(annotated, metrics)

            elapsed_seconds = int((datetime.utcnow() - self.started_at).total_seconds())
            if enable_person_count and self.frame_index % 5 == 0:
                set_connected_camera(
                    self.camera_id,
                    allow_create=False,
                    current_person_count=self.last_person_count,
                    total_person_count=self.total_person_count,
                    total_frames=self.frame_index,
                    processing_time_seconds=max(elapsed_seconds, 0),
                )

            return annotated

    def _should_run_detection(self) -> bool:
        return self.frame_index == 1 or (self.frame_index % self.detection_frame_stride) == 0

    def _update_person_tracks(self, frame, now: float):
        try:
            step = run_tracked_count_step(
                frame=frame,
                tracker=self.tracker,
                counter=self.counter,
                confidence_threshold=0.25,
            )
            tracks = step["tracks"]
            counts = step["counts"]
            detection_count = int(step.get("detection_count", 0))
        except Exception:
            tracks = []
            counts = {"current": 0, "entered": self.total_person_count}
            detection_count = 0

        if detection_count > 0:
            self.missing_detection_cycles = 0
        else:
            self.missing_detection_cycles += 1
            if self.missing_detection_cycles >= self.max_missing_detection_cycles:
                tracks = []
                counts = self.counter.update([])

        self.person_tracks = tracks
        self.last_tracks_at = now
        self.last_person_count = int(counts.get("current", len(tracks)))
        self.total_person_count = int(counts.get("entered", self.total_person_count))

    def _predict_person_tracks(self, now: float):
        if self.missing_detection_cycles >= self.max_missing_detection_cycles:
            self.person_tracks = []
            self.last_person_count = 0
            self.counter.update([])
            return

        try:
            tracks = self.tracker.update([], scores=[])
            counts = self.counter.update(tracks)
        except Exception:
            tracks = self.person_tracks
            counts = {"current": len(tracks), "entered": self.total_person_count}

        self.person_tracks = tracks
        self.last_tracks_at = now
        self.last_person_count = int(counts.get("current", len(tracks)))
        self.total_person_count = int(counts.get("entered", self.total_person_count))

    def _prune_stale_tracks(self, now: float):
        if (now - self.last_tracks_at) > self.max_track_stale_seconds:
            self.person_tracks = []
            self.last_person_count = 0
            return
        self.last_person_count = len(self.person_tracks)

    def _draw_person_tracks(self, frame):
        seen_ids: set[int] = set()
        for track in self.person_tracks:
            bbox = getattr(track, "bbox", None)
            track_id = getattr(track, "track_id", None)
            if bbox is None or len(bbox) != 4:
                continue
            if track_id is not None:
                track_id = int(track_id)
                if track_id in seen_ids:
                    continue
                seen_ids.add(track_id)
            x1, y1, x2, y2 = map(int, bbox)
            label = f"Person ID:{track_id}" if track_id is not None else "Person"

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                frame,
                label,
                (x1, max(y1 - 8, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 0),
                2,
            )

    def _draw_face_tracks(self, frame, now: float):
        if (now - self.last_face_tracks_at) > self.max_face_track_stale_seconds:
            self.face_tracks = []
            return

        for result in self.face_tracks:
            bbox = result.get("bbox")
            if not bbox or len(bbox) != 4:
                continue

            x1, y1, x2, y2 = map(int, bbox)
            identity = str(result.get("name", "Unknown")).strip() or "Unknown"
            track_id = result.get("id")
            label = f"{identity} ID:{track_id}" if track_id is not None else identity

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 255), 2)
            cv2.putText(
                frame,
                label,
                (x1, max(y1 - 8, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 200, 255),
                2,
            )


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
        tcp_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, tcp_query, parsed.fragment))
        candidates.append(tcp_url)
    return candidates


def _create_rtsp_capture(rtsp_url: str):
    # Reduce noisy decoder warnings and force more resilient RTSP/FFmpeg behavior
    # for cameras that intermittently send broken H.264 packets.
    os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", os.getenv("RTSP_FFMPEG_LOGLEVEL", "8"))
    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        os.getenv(
            "RTSP_FFMPEG_CAPTURE_OPTIONS",
            "rtsp_transport;tcp|fflags;discardcorrupt|flags;low_delay|max_delay;500000|stimeout;5000000",
        ),
    )

    capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
        capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
    if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
        capture.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
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


def _get_recognition_service():
    global RECOGNITION_SERVICE
    global RECOGNITION_SERVICE_INIT_FAILED

    with RECOGNITION_SERVICE_LOCK:
        if RECOGNITION_SERVICE is not None:
            return RECOGNITION_SERVICE
        if RECOGNITION_SERVICE_INIT_FAILED:
            return None

        try:
            recognition_module = importlib.import_module("src.person_recognition")
            recognition_service_class = getattr(recognition_module, "RecognitionService")
            RECOGNITION_SERVICE = recognition_service_class()
            return RECOGNITION_SERVICE
        except Exception:
            RECOGNITION_SERVICE_INIT_FAILED = True
            return None


def _run_person_recognition(frame):
    recognition_service = _get_recognition_service()
    if recognition_service is None:
        return 0, 0, []

    try:
        _, results = recognition_service.recognize(frame)
    except Exception:
        return 0, 0, []

    known = 0
    unknown = 0
    for result in results:
        name = str(result.get("name", "")).strip().lower()
        if name == "unknown":
            unknown += 1
        else:
            known += 1
    return known, unknown, results


def _draw_top_right_metrics(frame, metrics: list[tuple[str, int]]):
    if not metrics:
        return

    margin_right = 8
    start_y = 22
    line_gap = 26
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.7
    thickness = 2
    color = (0, 255, 0)
    width = frame.shape[1]

    for index, (label, value) in enumerate(metrics):
        text = f"{label} - {max(int(value), 0)}"
        (text_width, _), _ = cv2.getTextSize(text, font, font_scale, thickness)
        x = max(10, width - text_width - margin_right)
        y = start_y + (index * line_gap)
        cv2.putText(frame, text, (x, y), font, font_scale, color, thickness)


def _annotate_frame_for_camera(
    camera_id: str,
    rtsp_url: str,
    enable_person_count: bool,
    enable_person_recognition: bool,
    retries: int = 20,
):
    shared_stream = _ensure_camera_stream(camera_id, rtsp_url)

    frame = None
    for _ in range(retries):
        frame = shared_stream.get_frame_copy()
        if frame is not None:
            break
        sleep(0.02)

    if frame is None:
        return None

    return shared_stream.processor.process(
        frame=frame,
        enable_person_count=enable_person_count,
        enable_person_recognition=enable_person_recognition,
    )


def _create_webrtc_track(camera_id: str, rtsp_url: str, enable_person_count: bool, enable_person_recognition: bool):
    try:
        aiortc_module = importlib.import_module("aiortc")
        aiortc_media_module = importlib.import_module("aiortc.mediastreams")
        av_module = importlib.import_module("av")
    except ModuleNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="WebRTC dependencies are not installed on backend environment. Install `aiortc` and `av`.",
        ) from exc

    VideoStreamTrack = getattr(aiortc_module, "VideoStreamTrack")
    MediaStreamError = getattr(aiortc_media_module, "MediaStreamError")
    VideoFrame = getattr(av_module, "VideoFrame")

    class CameraVideoTrack(VideoStreamTrack):
        def __init__(self):
            super().__init__()
            self.camera_id = camera_id
            self.rtsp_url = rtsp_url
            self.enable_person_count = enable_person_count
            self.enable_person_recognition = enable_person_recognition
            self.closed = False

        async def recv(self):
            if self.closed:
                raise MediaStreamError

            pts, time_base = await self.next_timestamp()

            frame = await asyncio.to_thread(
                _annotate_frame_for_camera,
                self.camera_id,
                self.rtsp_url,
                self.enable_person_count,
                self.enable_person_recognition,
            )

            if frame is None:
                raise MediaStreamError

            video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
            video_frame.pts = pts
            video_frame.time_base = time_base if time_base is not None else Fraction(1, 90000)
            return video_frame

        def stop(self):
            self.closed = True
            super().stop()

    return CameraVideoTrack()


def _generate_mjpeg_frames(camera_id: str, rtsp_url: str, enable_person_count: bool, enable_person_recognition: bool):
    while True:
        frame = _annotate_frame_for_camera(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            enable_person_count=enable_person_count,
            enable_person_recognition=enable_person_recognition,
        )
        if frame is None:
            sleep(0.05)
            continue

        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            continue

        frame_bytes = buffer.tobytes()
        yield b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"


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

    _ensure_camera_stream(camera_id=camera_id, rtsp_url=verified_rtsp_url)
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


@router.put("/cameras/{camera_id}")
async def update_camera(camera_id: str, payload: CameraUpdateRequest):
    existing_camera = get_connected_camera(camera_id)
    if not existing_camera:
        raise HTTPException(status_code=404, detail="Camera not found.")

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

    camera_name = (payload.camera_name or "").strip() or (
        existing_camera.get("camera_name") or f"Camera-{camera_id[:8]}"
    )
    safe_stream_url = f"rtsp://{parsed.hostname}:{parsed.port or 554}{parsed.path or ''}"

    _ensure_camera_stream(camera_id=camera_id, rtsp_url=verified_rtsp_url)
    updated_camera = set_connected_camera(
        camera_id,
        camera_name=camera_name,
        rtsp_url=verified_rtsp_url,
        host=parsed.hostname,
        port=parsed.port or 554,
        status="connected",
        use_cases=normalized_use_cases,
        connected_at=existing_camera.get("connected_at") or datetime.utcnow().isoformat(),
    )

    return JSONResponse(
        {
            "success": True,
            "message": f"{camera_name} updated successfully.",
            "camera_id": camera_id,
            "stream_url": safe_stream_url,
            "use_cases": normalized_use_cases,
            "data": updated_camera,
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
            enable_person_recognition="person_recognition" in normalize_use_cases(camera.get("use_cases")),
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
            detail="WebRTC dependencies are not installed on backend environment. Install `aiortc` and `av`.",
        ) from exc

    RTCPeerConnection = getattr(aiortc_module, "RTCPeerConnection")
    RTCSessionDescription = getattr(aiortc_module, "RTCSessionDescription")

    pc = RTCPeerConnection()
    track = _create_webrtc_track(
        camera_id=camera_id,
        rtsp_url=rtsp_url,
        enable_person_count="person_count" in normalize_use_cases(camera.get("use_cases")),
        enable_person_recognition="person_recognition" in normalize_use_cases(camera.get("use_cases")),
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
    _stop_camera_stream(camera_id)
    deleted = delete_connected_camera(camera_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Camera not found.")

    return JSONResponse(
        {
            "success": True,
            "message": "Camera removed successfully.",
        }
    )
