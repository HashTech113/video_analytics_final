import asyncio
from datetime import datetime
from fractions import Fraction
import importlib
import logging
import os
from threading import Event, Lock, Thread
from time import monotonic, sleep
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
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
logger = logging.getLogger(__name__)

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
    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        enable_person_count: bool,
        enable_person_recognition: bool,
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.enable_person_count = enable_person_count
        self.enable_person_recognition = enable_person_recognition
        self.stop_event = Event()
        self.frame_lock = Lock()
        # Separate lock for the raw (unprocessed) frame slot so the
        # capture thread never waits on YOLO/annotation work.
        self.raw_frame_lock = Lock()

        self.frame = None
        self.processed_frame = None
        self.last_frame_at = 0.0
        self.source_fps = 0.0
        # Single-slot buffer: capture thread always overwrites with the
        # latest frame; process thread consumes it and sets it back to None.
        self._raw_frame = None

        try:
            self.processor = (
                CameraFrameProcessor(camera_id=camera_id)
                if (enable_person_count or enable_person_recognition)
                else None
            )
        except Exception:
            logger.exception("Camera processor init failed for camera_id=%s; continuing with raw frames", camera_id)
            self.processor = None

        # Two threads:
        #  • capture_thread — drains the RTSP buffer continuously, always
        #    keeping only the newest raw frame so nothing accumulates.
        #  • process_thread — picks up the latest raw frame, runs YOLO /
        #    ByteTrack / annotation, and stores the result.  When YOLO is
        #    slow (100 ms+), the capture thread keeps running so the next
        #    processed frame is always the most recent one available.
        self.capture_thread = Thread(
            target=self._capture_run,
            daemon=True,
            name=f"camera-capture-{camera_id}",
        )
        self.process_thread = Thread(
            target=self._process_run,
            daemon=True,
            name=f"camera-process-{camera_id}",
        )
        self.capture_thread.start()
        self.process_thread.start()

    def _capture_run(self):
        """Continuously reads RTSP at full speed, keeping only the latest frame."""
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
                sleep(0.01)
                continue

            failures = 0
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            with self.raw_frame_lock:
                # Always overwrite — the process thread will pick up the
                # newest frame the next time it is ready.
                self._raw_frame = frame
                if fps > 0:
                    self.source_fps = fps

        capture.release()

    def _process_run(self):
        """Grabs the latest raw frame, annotates it, and stores the result."""
        while not self.stop_event.is_set():
            with self.raw_frame_lock:
                frame = self._raw_frame
                self._raw_frame = None  # mark consumed

            if frame is None:
                sleep(0.01)
                continue

            processed_frame = frame
            if self.processor is not None:
                try:
                    processed_frame = self.processor.process(
                        frame=frame,
                        enable_person_count=self.enable_person_count,
                        enable_person_recognition=self.enable_person_recognition,
                    )
                except Exception:
                    logger.exception("Camera frame processing failed for camera_id=%s; serving raw frame", self.camera_id)
                    processed_frame = frame

            frame_copy = frame.copy()
            processed_copy = processed_frame.copy() if processed_frame is not frame else frame_copy.copy()

            with self.frame_lock:
                self.frame = frame_copy
                self.processed_frame = processed_copy
                self.last_frame_at = datetime.utcnow().timestamp()

    def get_frame_copy(self):
        with self.frame_lock:
            if self.frame is None:
                return None
            return self.frame.copy()

    def get_processed_frame_copy(self):
        with self.frame_lock:
            if self.processed_frame is None:
                return None
            return self.processed_frame.copy()

    def get_source_fps(self) -> float:
        with self.frame_lock:
            return self.source_fps

    def seconds_since_last_frame(self) -> float:
        with self.frame_lock:
            last_frame_at = self.last_frame_at
        if last_frame_at <= 0:
            return float("inf")
        return max(0.0, datetime.utcnow().timestamp() - last_frame_at)

    def is_stale(self, max_age_seconds: float = 8.0) -> bool:
        return self.seconds_since_last_frame() > max_age_seconds

    def stop(self):
        self.stop_event.set()
        if self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2.0)
        if self.process_thread.is_alive():
            self.process_thread.join(timeout=2.0)


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
        self.detection_frame_stride = 3
        self.face_recognition_stride = 12
        self.max_track_stale_seconds = 3.0
        self.max_missing_detection_cycles = 8
        self.missing_detection_cycles = 0
        self.last_tracks_at = 0.0
        self.person_tracks = []
        self.last_person_count = 0
        self.total_person_count = 0
        self.last_known_count = 0
        self.last_unknown_count = 0
        self.face_tracks = []
        self.last_face_tracks_at = 0.0
        self.max_face_track_stale_seconds = 2.0
        self.started_at = datetime.utcnow()
        self.last_store_update_at = 0.0
        self.tracker = ByteTrackFaceTracker(
            track_thresh=0.25,
            track_buffer=30,
            match_thresh=0.8,
            frame_rate=30,
            fallback_iou_threshold=0.3,
            fallback_center_distance_threshold=120,
            smoothing_alpha=0.75,
        )
        self.counter = PersonCounter(min_hits=3, max_idle_seconds=2.0)

        # Face recognition runs in a dedicated daemon thread so it never blocks
        # the main frame-processing loop (ArcFace on CPU can take 500 ms – 2 s).
        self._recog_lock = Lock()
        self._recog_running = False
        self._recog_result: tuple | None = None  # (known, unknown, face_results)

    def _recognition_worker(self, frame_copy) -> None:
        """Run face recognition in a background daemon thread."""
        try:
            result = _run_person_recognition(frame_copy)
        except Exception:
            result = (0, 0, [])
        with self._recog_lock:
            self._recog_result = result
            self._recog_running = False

    def process(self, frame, enable_person_count: bool, enable_person_recognition: bool):
        with self.lock:
            self.frame_index += 1
            now = monotonic()

            if enable_person_count:
                if self._should_run_detection():
                    self._update_person_tracks(frame, now)
                else:
                    self._predict_person_tracks(now)

            if enable_person_recognition:
                # Collect result from the background thread if it finished.
                # Extract new_face_results outside the lock so the activity
                # tracker's DB writes never hold _recog_lock.
                new_face_results = None
                with self._recog_lock:
                    if self._recog_result is not None:
                        known_count, unknown_count, face_results = self._recog_result
                        self.last_known_count = known_count
                        self.last_unknown_count = unknown_count
                        self.face_tracks = face_results
                        self.last_face_tracks_at = now
                        self._recog_result = None
                        new_face_results = face_results

                    # Fire a new recognition job if none is running and it is time
                    if not self._recog_running and self.frame_index % self.face_recognition_stride == 0:
                        self._recog_running = True
                        Thread(
                            target=self._recognition_worker,
                            args=(frame.copy(),),
                            daemon=True,
                        ).start()

                # Update presence tracking whenever a fresh recognition result arrived.
                if new_face_results is not None:
                    try:
                        from app.services.activity_tracker import update_presence
                        _cam = get_connected_camera(self.camera_id)
                        _cam_name = (_cam or {}).get("camera_name") or self.camera_id
                        update_presence(self.camera_id, _cam_name, new_face_results)
                    except Exception:
                        pass  # tracking errors must never affect frame processing
            else:
                self.face_tracks = []

            self._prune_stale_tracks(now)
            self.counter.cleanup(now)

            annotated = frame.copy()
            self._draw_person_tracks(annotated, now, enable_person_recognition)
            self._clear_stale_face_tracks(now)

            metrics: list[tuple[str, int]] = []
            if enable_person_count:
                metrics.append(("Count", self.last_person_count))
            if enable_person_recognition:
                metrics.append(("Known", self.last_known_count))
                metrics.append(("Unknown", self.last_unknown_count))
            _draw_top_right_metrics(annotated, metrics)

            elapsed_seconds = int((datetime.utcnow() - self.started_at).total_seconds())
            if enable_person_count and (now - self.last_store_update_at) >= 1.0:
                set_connected_camera(
                    self.camera_id,
                    allow_create=False,
                    current_person_count=self.last_person_count,
                    total_person_count=self.total_person_count,
                    total_frames=self.frame_index,
                    processing_time_seconds=max(elapsed_seconds, 0),
                )
                self.last_store_update_at = now

            return annotated

    def _should_run_detection(self) -> bool:
        return self.frame_index == 1 or (self.frame_index % self.detection_frame_stride) == 0

    def _update_person_tracks(self, frame, now: float):
        # Resize to 640 wide for detection — YOLO internally resizes anyway but
        # doing it explicitly cuts Python-level preprocessing time by ~4-8× on
        # high-resolution camera feeds (1080p → 640p = ~9× fewer pixels).
        h, w = frame.shape[:2]
        scale = 1.0
        det_frame = frame
        if w > 640:
            scale = 640.0 / w
            det_frame = cv2.resize(frame, (640, max(1, int(h * scale))), interpolation=cv2.INTER_LINEAR)

        try:
            step = run_tracked_count_step(
                frame=det_frame,
                tracker=self.tracker,
                counter=self.counter,
                confidence_threshold=0.25,
            )
            tracks = step["tracks"]
            counts = step["counts"]
            detection_count = int(step.get("detection_count", 0))

            # Scale bboxes back to original-frame coordinates so annotations
            # are drawn at the correct position on the full-resolution frame.
            if scale != 1.0:
                inv = 1.0 / scale
                for track in tracks:
                    if track.bbox and len(track.bbox) == 4:
                        track.bbox = [int(v * inv) for v in track.bbox]
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

        # Preserve last known tracks without feeding empty detections to
        # ByteTrack — calling tracker.update([], []) would age out / drop
        # tracks between detection frames, which is what was causing the
        # bounding-box blinking effect.  Boxes stay at their last detected
        # position until the next detection frame updates them.
        self.last_tracks_at = now
        self.last_person_count = len(self.person_tracks)

    def _prune_stale_tracks(self, now: float):
        if (now - self.last_tracks_at) > self.max_track_stale_seconds:
            self.person_tracks = []
            self.last_person_count = 0
            return
        self.last_person_count = len(self.person_tracks)

    def _face_label_for_person(self, person_bbox: list) -> str | None:
        """
        Find a face recognition result whose face centre lies inside the
        person bounding box.  Returns the label to show, or None if no
        face match is found.

        Label rules:
          - Known person  →  name as recognised  (e.g. "Akash")
          - Unknown face  →  "Unknown_<face_track_id>"
        """
        if not self.face_tracks:
            return None

        px1, py1, px2, py2 = map(int, person_bbox)

        for face in self.face_tracks:
            fbbox = face.get("bbox")
            if not fbbox or len(fbbox) != 4:
                continue
            fx1, fy1, fx2, fy2 = map(int, fbbox)
            face_cx = (fx1 + fx2) // 2
            face_cy = (fy1 + fy2) // 2

            if px1 <= face_cx <= px2 and py1 <= face_cy <= py2:
                name = str(face.get("name", "")).strip()
                face_id = face.get("id")
                if name and name.lower() != "unknown":
                    return name
                return f"Unknown_{face_id}" if face_id is not None else "Unknown"

        return None

    def _draw_person_tracks(self, frame, now: float, enable_person_recognition: bool = False):
        """
        Draw green bounding boxes for every tracked person.

        When face recognition is active:
          - Known person  → name (e.g. "Akash")
          - Unknown face  → "Unknown_<face_track_id>"
          - No face match → "Person <track_id>"

        When only person_recognition is enabled (no YOLO person tracks),
        face detection boxes are drawn directly so detections are still visible.
        """
        face_tracks_fresh = (
            enable_person_recognition
            and (now - self.last_face_tracks_at) <= self.max_face_track_stale_seconds
        )

        # --- Case: person_count tracks available (normal path) ---
        if self.person_tracks:
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

                if face_tracks_fresh:
                    label = self._face_label_for_person(bbox) or f"Person {track_id}"
                else:
                    label = f"Person {track_id}" if track_id is not None else "Person"

                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 230, 0), 2)
                _draw_label(frame, label, x1, max(y1 - 2, 18))
            return

        # --- Case: no YOLO person tracks but face recognition is active ---
        # Draw face bboxes directly so the user still sees detections.
        if face_tracks_fresh and self.face_tracks:
            for face in self.face_tracks:
                fbbox = face.get("bbox")
                if not fbbox or len(fbbox) != 4:
                    continue
                name = str(face.get("name", "")).strip()
                face_id = face.get("id")
                if name and name.lower() != "unknown":
                    label = name
                else:
                    label = f"Unknown_{face_id}" if face_id is not None else "Unknown"

                x1, y1, x2, y2 = map(int, fbbox)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 230, 0), 2)
                _draw_label(frame, label, x1, max(y1 - 2, 18))

    def _clear_stale_face_tracks(self, now: float):
        """Clear face_tracks when they have gone stale (replaces _draw_face_tracks)."""
        if (now - self.last_face_tracks_at) > self.max_face_track_stale_seconds:
            self.face_tracks = []


def _ensure_camera_stream(
    camera_id: str,
    rtsp_url: str,
    enable_person_count: bool,
    enable_person_recognition: bool,
) -> CameraStream:
    with CAMERA_STREAMS_LOCK:
        stream = CAMERA_STREAMS.get(camera_id)
        if (
            stream
            and stream.rtsp_url == rtsp_url
            and stream.enable_person_count == enable_person_count
            and stream.enable_person_recognition == enable_person_recognition
            and stream.capture_thread.is_alive()
        ):
            return stream
        if stream:
            stream.stop()
        stream = CameraStream(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            enable_person_count=enable_person_count,
            enable_person_recognition=enable_person_recognition,
        )
        CAMERA_STREAMS[camera_id] = stream
        return stream


def _stop_camera_stream(camera_id: str):
    with CAMERA_STREAMS_LOCK:
        stream = CAMERA_STREAMS.pop(camera_id, None)
    if stream:
        stream.stop()
        try:
            from app.services.activity_tracker import flush_camera
            _cam = get_connected_camera(camera_id)
            _cam_name = (_cam or {}).get("camera_name") or camera_id
            flush_camera(camera_id, _cam_name)
        except Exception:
            pass


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
            "rtsp_transport;tcp|fflags;discardcorrupt|flags;low_delay|max_delay;200000|reorder_queue_size;0|stimeout;5000000",
        ),
    )

    capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    if not capture.isOpened():
        capture.release()
        # Some environments cannot open network streams with CAP_FFMPEG explicitly.
        # Retry with OpenCV's default backend selection.
        capture = cv2.VideoCapture(rtsp_url)
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


def _draw_label(frame, text: str, x: int, y: int,
                font_scale: float = 0.55, thickness: int = 1,
                text_color=(255, 255, 255), bg_color=(0, 0, 0)):
    """Draw text with a solid filled background for maximum readability."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    pad = 3
    # Clamp so the box never goes above the frame top
    top = max(0, y - th - pad)
    cv2.rectangle(frame, (x, top), (x + tw + pad * 2, y + baseline), bg_color, -1)
    cv2.putText(frame, text, (x + pad, y), font, font_scale, text_color, thickness,
                cv2.LINE_AA)


def _draw_top_right_metrics(frame, metrics: list[tuple[str, int]]):
    if not metrics:
        return

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.65
    thickness = 1
    pad = 6          # inner horizontal padding for each pill
    row_gap = 6      # vertical gap between rows
    width = frame.shape[1]

    # Pre-measure all rows so we can right-align the pills consistently
    rows = []
    for label, value in metrics:
        text = f"{label}  {max(int(value), 0)}"
        (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
        rows.append((text, tw, th, baseline))

    y = 10
    for text, tw, th, baseline in rows:
        pill_w = tw + pad * 2
        pill_h = th + baseline + pad * 2
        x = width - pill_w - 8          # 8 px from right edge
        # Dark background pill
        cv2.rectangle(frame, (x, y), (x + pill_w, y + pill_h), (20, 20, 20), -1)
        cv2.rectangle(frame, (x, y), (x + pill_w, y + pill_h), (0, 200, 0), 1)
        # Bright green text
        cv2.putText(frame, text, (x + pad, y + th + pad - 1),
                    font, font_scale, (0, 230, 0), thickness, cv2.LINE_AA)
        y += pill_h + row_gap


def _annotate_frame_for_camera(
    camera_id: str,
    rtsp_url: str,
    enable_person_count: bool,
    enable_person_recognition: bool,
    retries: int = 20,
):
    shared_stream = _ensure_camera_stream(
        camera_id,
        rtsp_url,
        enable_person_count=enable_person_count,
        enable_person_recognition=enable_person_recognition,
    )

    frame = None
    for _ in range(retries):
        frame = shared_stream.get_processed_frame_copy()
        if frame is not None:
            break
        sleep(0.02)

    if frame is None:
        return None
    return frame


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
                # Send a black placeholder instead of terminating the stream.
                # This keeps the WebRTC session alive while the camera warms up
                # or recovers from a momentary read failure.
                frame = np.zeros((480, 640, 3), dtype=np.uint8)

            video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
            video_frame.pts = pts
            video_frame.time_base = time_base if time_base is not None else Fraction(1, 90000)
            return video_frame

        def stop(self):
            self.closed = True
            super().stop()

    return CameraVideoTrack()


def _generate_mjpeg_frames(
    camera_id: str,
    rtsp_url: str,
    enable_person_count: bool,
    enable_person_recognition: bool,
    target_fps: float = 25.0,
    jpeg_quality: int = 82,
    max_width: int | None = None,
):
    # Obtain (or create) the shared stream once — subsequent calls in the loop
    # are just a fast dict lookup so the per-frame overhead is negligible.
    stream = _ensure_camera_stream(camera_id, rtsp_url, enable_person_count, enable_person_recognition)

    consecutive_failures = 0
    min_frame_interval = 1.0 / max(target_fps, 1.0)
    next_emit_at = monotonic()

    while True:
        try:
            # Read the latest already-processed frame directly — no retry
            # loop, no blocking.  The process thread keeps this updated at
            # camera speed so we always get a fresh result.
            if not stream.capture_thread.is_alive():
                stream = _ensure_camera_stream(camera_id, rtsp_url, enable_person_count, enable_person_recognition)

            frame = stream.get_processed_frame_copy()
        except GeneratorExit:
            break
        except Exception:
            consecutive_failures += 1
            if consecutive_failures == 1 or consecutive_failures % 25 == 0:
                logger.exception(
                    "Live preview frame generation failed for camera_id=%s (failures=%s)",
                    camera_id,
                    consecutive_failures,
                )
            sleep(0.05)
            continue

        if frame is None:
            consecutive_failures += 1
            sleep(0.05)
            continue

        if max_width and max_width > 0:
            try:
                height, width = frame.shape[:2]
                if width > max_width:
                    resized_height = int((height * max_width) / width)
                    frame = cv2.resize(frame, (max_width, max(1, resized_height)), interpolation=cv2.INTER_AREA)
            except Exception:
                pass

        consecutive_failures = 0
        try:
            ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)])
        except Exception:
            sleep(0.05)
            continue
        if not ok:
            continue

        frame_bytes = buffer.tobytes()
        yield b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        next_emit_at += min_frame_interval
        sleep_for = next_emit_at - monotonic()
        if sleep_for > 0:
            sleep(sleep_for)
        else:
            next_emit_at = monotonic()


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

    _ensure_camera_stream(
        camera_id=camera_id,
        rtsp_url=verified_rtsp_url,
        enable_person_count="person_count" in normalized_use_cases,
        enable_person_recognition="person_recognition" in normalized_use_cases,
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

    _ensure_camera_stream(
        camera_id=camera_id,
        rtsp_url=verified_rtsp_url,
        enable_person_count="person_count" in normalized_use_cases,
        enable_person_recognition="person_recognition" in normalized_use_cases,
    )
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
async def get_camera_stream(
    camera_id: str,
    preview: bool = Query(default=False),
):
    camera = get_connected_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found.")

    rtsp_url = (camera.get("rtsp_url") or "").strip()
    if not rtsp_url:
        raise HTTPException(status_code=400, detail="Camera stream URL not available.")

    enable_person_count = "person_count" in normalize_use_cases(camera.get("use_cases"))
    enable_person_recognition = "person_recognition" in normalize_use_cases(camera.get("use_cases"))

    target_fps = 25.0
    jpeg_quality = 82
    max_width = None
    if preview:
        target_fps = 25.0
        jpeg_quality = 82
        max_width = 1280

    return StreamingResponse(
        _generate_mjpeg_frames(
            camera_id,
            rtsp_url,
            enable_person_count=enable_person_count,
            enable_person_recognition=enable_person_recognition,
            target_fps=target_fps,
            jpeg_quality=jpeg_quality,
            max_width=max_width,
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


@router.get("/cameras/{camera_id}/snapshot")
async def get_camera_snapshot(camera_id: str):
    """Return a single annotated JPEG frame for the camera (used by the frontend polling loop).

    This endpoint is designed to be called at ~15 FPS per camera.  It NEVER
    blocks waiting for a frame — it reads whatever the background CameraStream
    thread has already processed and returns it immediately.  Heavy work (YOLO,
    ByteTrack, face recognition) happens exclusively in the background thread.
    """
    camera = get_connected_camera(camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found.")

    rtsp_url = (camera.get("rtsp_url") or "").strip()
    if not rtsp_url:
        raise HTTPException(status_code=400, detail="Camera stream URL not available.")

    enable_person_count = "person_count" in normalize_use_cases(camera.get("use_cases"))
    enable_person_recognition = "person_recognition" in normalize_use_cases(camera.get("use_cases"))

    # Ensure the background stream thread is running, then grab the latest
    # already-processed frame.  _ensure_camera_stream holds the lock for only
    # a dict-lookup's worth of time so this never meaningfully blocks the loop.
    stream = _ensure_camera_stream(camera_id, rtsp_url, enable_person_count, enable_person_recognition)
    frame = stream.get_processed_frame_copy()
    if frame is None:
        raise HTTPException(status_code=503, detail="No frame available yet.")

    # JPEG encode in a thread so we don't block the event loop.
    frame_for_encode = frame  # capture for lambda closure
    ok, buffer = await asyncio.to_thread(
        lambda: cv2.imencode(".jpg", frame_for_encode, [cv2.IMWRITE_JPEG_QUALITY, 80])
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode frame.")

    return Response(
        content=bytes(buffer),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, no-cache", "Pragma": "no-cache"},
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
