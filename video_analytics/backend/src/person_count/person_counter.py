from dataclasses import dataclass
import os
import subprocess
import time
from time import monotonic
from typing import Any

import cv2
from ultralytics import YOLO


@dataclass
class TrackState:
    first_seen: float
    last_seen: float
    hits: int = 1


@dataclass
class PersonDetection:
    bbox: list[int]
    conf: float


class PersonCounter:
    """
    Stateful unique-person counter based on tracker IDs.

    Expected flow for live streams:
    1) detect persons (YOLO)
    2) track persons (ByteTrack/other tracker)
    3) count unique IDs here
    4) draw tracked boxes every frame
    """

    def __init__(self, min_hits: int = 3, max_idle_seconds: float = 2.0):
        self.min_hits = min_hits
        self.max_idle_seconds = max_idle_seconds

        self.track_states: dict[int, TrackState] = {}
        self.confirmed_ids: set[int] = set()
        self.total_entered = 0

    def reset(self):
        self.track_states.clear()
        self.confirmed_ids.clear()
        self.total_entered = 0

    def update(self, tracks: list[Any]):
        now = monotonic()
        visible_ids: list[int] = []
        visible_id_set: set[int] = set()

        for track in tracks:
            track_id = getattr(track, "track_id", None)
            if track_id is None:
                continue

            track_id = int(track_id)
            if track_id not in visible_id_set:
                visible_ids.append(track_id)
                visible_id_set.add(track_id)

            if track_id not in self.track_states:
                self.track_states[track_id] = TrackState(
                    first_seen=now,
                    last_seen=now,
                    hits=1,
                )
            else:
                state = self.track_states[track_id]
                state.last_seen = now
                state.hits += 1

            state = self.track_states[track_id]
            if state.hits >= self.min_hits and track_id not in self.confirmed_ids:
                self.confirmed_ids.add(track_id)
                self.total_entered += 1

        self.cleanup(now)

        return {
            "current": len(visible_ids),
            "total": len(self.confirmed_ids),
            "entered": self.total_entered,
            "ids": visible_ids,
        }

    def cleanup(self, now: float | None = None):
        now = monotonic() if now is None else now
        stale_ids: list[int] = []

        for track_id, state in self.track_states.items():
            if now - state.last_seen > self.max_idle_seconds:
                stale_ids.append(track_id)

        for track_id in stale_ids:
            del self.track_states[track_id]


# Load YOLO11n model once from backend/models.
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "models",
    "yolo11n.pt",
)
model = YOLO(MODEL_PATH)


def detect_persons(frame, confidence_threshold: float = 0.35) -> tuple[list[PersonDetection], list[float]]:
    """Run YOLO person detection and return normalized detections + scores."""
    results = model(frame, verbose=False)
    detections: list[PersonDetection] = []
    scores: list[float] = []

    for result in results:
        for box in result.boxes:
            cls = int(box.cls[0])
            if cls != 0:
                continue

            conf = float(box.conf[0])
            if conf < confidence_threshold:
                continue

            x1, y1, x2, y2 = map(int, box.xyxy[0])
            detections.append(PersonDetection(bbox=[x1, y1, x2, y2], conf=conf))
            scores.append(conf)

    return detections, scores


def draw_detection_boxes(frame, detections: list[PersonDetection]):
    """Draw plain detector boxes (offline processing path)."""
    person_count = len(detections)
    for idx, det in enumerate(detections):
        x1, y1, x2, y2 = det.bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(
            frame,
            f"Person {idx+1}/{person_count} {det.conf:.2f}",
            (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            2,
        )
    # Show total count on frame
    cv2.putText(
        frame,
        f"Count: {person_count}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 0, 255),
        2,
    )


def draw_tracked_people(frame, tracks: list[Any]):
    """Draw tracker output with IDs (live path)."""
    for track in tracks:
        bbox = getattr(track, "bbox", None)
        track_id = getattr(track, "track_id", None)
        name = getattr(track, "name", None)
        if bbox is None:
            continue

        x1, y1, x2, y2 = map(int, bbox)
        if name:
            label = f"{name} ID:{track_id}"
        else:
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


def run_tracked_count_step(frame, tracker: Any, counter: PersonCounter, confidence_threshold: float = 0.35):
    """
    Correct live flow in one step:
    YOLO -> tracker.update(...) -> PersonCounter.update(...) -> draw tracked boxes
    """
    detections, scores = detect_persons(frame, confidence_threshold=confidence_threshold)
    raw_boxes = [det.bbox for det in detections]

    try:
        tracks = tracker.update(raw_boxes, scores=scores)
    except TypeError:
        # Fallback for trackers that only accept detections.
        tracks = tracker.update(raw_boxes)

    counts = counter.update(tracks)
    annotated = frame.copy()
    draw_tracked_people(annotated, tracks)

    return {
        "frame": annotated,
        "tracks": tracks,
        "counts": counts,
        "detection_count": len(detections),
    }


def process_video(input_path, output_dir, frame_stride=1, progress_callback=None):
    if frame_stride < 1:
        raise ValueError("frame_stride must be >= 1.")

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open input video: {input_path}")

    filename = os.path.basename(input_path)
    stem, _ = os.path.splitext(filename)
    ts = int(time.time())
    temp_output_path = os.path.join(output_dir, f"processed_{stem}_{ts}_raw.mp4")
    output_path = os.path.join(output_dir, f"processed_{stem}_{ts}.mp4")

    source_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    fps = source_fps if source_fps > 0 else 25.0
    source_total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    output_fps = max(fps / frame_stride, 1.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width <= 0 or height <= 0:
        cap.release()
        raise ValueError("Invalid video dimensions.")

    writer_candidates = [
        (temp_output_path, "mp4v"),
        (temp_output_path, "avc1"),
        (os.path.join(output_dir, f"processed_{stem}_{ts}_raw.avi"), "XVID"),
        (os.path.join(output_dir, f"processed_{stem}_{ts}_raw.avi"), "MJPG"),
    ]
    out = None
    actual_temp_output_path = temp_output_path
    for candidate_path, fourcc_name in writer_candidates:
        fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
        writer = cv2.VideoWriter(candidate_path, fourcc, output_fps, (width, height))
        if writer.isOpened():
            out = writer
            actual_temp_output_path = candidate_path
            break
        writer.release()

    if out is None:
        cap.release()
        raise ValueError("Could not initialize output video writer for any supported codec.")

    max_person_count = 0
    source_frame_index = 0
    sampled_frames = 0
    second_buckets = {}
    last_reported_progress = -1

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_stride > 1 and source_frame_index % frame_stride != 0:
            source_frame_index += 1
            continue

        detections, _scores = detect_persons(frame)
        person_count = len(detections)
        draw_detection_boxes(frame, detections)

        max_person_count = max(max_person_count, person_count)
        second_index = int(source_frame_index / fps) if fps else sampled_frames
        if second_index not in second_buckets:
            second_buckets[second_index] = {"sum": 0, "frames": 0}
        second_buckets[second_index]["sum"] += person_count
        second_buckets[second_index]["frames"] += 1

        sampled_frames += 1

        out.write(frame)
        source_frame_index += 1

        if progress_callback and source_total_frames > 0:
            progress = int((source_frame_index / source_total_frames) * 100)
            progress = min(100, max(0, progress))
            if progress != last_reported_progress:
                progress_callback(progress, source_frame_index, source_total_frames)
                last_reported_progress = progress

    cap.release()
    out.release()

    encoded_output_path = actual_temp_output_path
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        actual_temp_output_path,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        output_path,
    ]

    try:
        result = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            encoded_output_path = output_path
            if os.path.exists(actual_temp_output_path):
                os.remove(actual_temp_output_path)
        else:
            if os.path.exists(output_path):
                os.remove(output_path)
    except FileNotFoundError:
        # ffmpeg may not be available in all environments; keep the OpenCV output in that case.
        if os.path.exists(output_path):
            os.remove(output_path)

    counts_per_second = []
    for second in sorted(second_buckets.keys()):
        bucket = second_buckets[second]
        if bucket["frames"] <= 0:
            continue
        avg_count = round(bucket["sum"] / bucket["frames"])
        counts_per_second.append({"second": second, "count": avg_count})

    processed_source_frames = source_total_frames or source_frame_index
    details = {
        "fps": fps,
        "total_frames": processed_source_frames,
        "sampled_frames": sampled_frames,
        "frame_stride": frame_stride,
        "duration_seconds": round(processed_source_frames / fps, 2) if fps else 0,
        "counts_per_second": counts_per_second,
        "peak_count": max_person_count,
    }

    if progress_callback:
        progress_callback(100, processed_source_frames, processed_source_frames)

    return encoded_output_path, max_person_count, details
