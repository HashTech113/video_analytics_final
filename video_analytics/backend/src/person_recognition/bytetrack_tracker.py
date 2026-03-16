from dataclasses import dataclass
import inspect
import numpy as np

from .face_tracker import FaceTracker


@dataclass
class Track:
    track_id: int
    bbox: list[int]


class ByteTrackFaceTracker:
    def __init__(
        self,
        track_thresh: float = 0.5,
        track_buffer: int = 30,
        match_thresh: float = 0.8,
        frame_rate: int = 30,
        fallback_iou_threshold: float = 0.3,
        fallback_center_distance_threshold: int = 80,
        smoothing_alpha: float = 0.65,
    ):
        self._sv = None
        self._tracker = None
        self._fallback = FaceTracker(
            max_missing=track_buffer,
            iou_threshold=fallback_iou_threshold,
            center_distance_threshold=fallback_center_distance_threshold,
        )
        self._smoothing_alpha = smoothing_alpha
        self._smoothed_boxes: dict[int, list[int]] = {}
        self._try_init(track_thresh, track_buffer, match_thresh, frame_rate)

    def _try_init(self, track_thresh: float, track_buffer: int, match_thresh: float, frame_rate: int):
        try:
            import supervision as sv
        except Exception as e:
            print(f"ByteTrack unavailable, falling back to FaceTracker: {e}")
            return

        self._sv = sv
        try:
            # Handle supervision ByteTrack constructor changes across versions.
            signature = inspect.signature(sv.ByteTrack.__init__)
            params = signature.parameters
            kwargs = {}
            if "track_activation_threshold" in params:
                kwargs["track_activation_threshold"] = track_thresh
            elif "track_thresh" in params:
                kwargs["track_thresh"] = track_thresh

            if "lost_track_buffer" in params:
                kwargs["lost_track_buffer"] = track_buffer
            elif "track_buffer" in params:
                kwargs["track_buffer"] = track_buffer

            if "minimum_matching_threshold" in params:
                kwargs["minimum_matching_threshold"] = match_thresh
            elif "match_thresh" in params:
                kwargs["match_thresh"] = match_thresh

            if "frame_rate" in params:
                kwargs["frame_rate"] = frame_rate

            self._tracker = sv.ByteTrack(**kwargs)
            print("ByteTrack initialized successfully")
        except Exception as e:
            self._tracker = None
            print(f"ByteTrack init failed, falling back to FaceTracker: {e}")

    def update(self, detections, scores=None):
        if self._tracker is None or self._sv is None:
            tracks = self._fallback.update(detections)
            return [
                Track(track_id=int(track.track_id), bbox=self._smooth(int(track.track_id), track.bbox))
                for track in tracks
            ]

        xyxy = np.array(detections, dtype=np.float32) if detections else np.empty((0, 4), dtype=np.float32)
        if scores is None or not detections:
            confidence = np.ones((xyxy.shape[0],), dtype=np.float32)
        else:
            confidence = np.array(scores, dtype=np.float32)
            if confidence.shape[0] != xyxy.shape[0]:
                confidence = np.ones((xyxy.shape[0],), dtype=np.float32)

        detections_sv = self._sv.Detections(
            xyxy=xyxy,
            confidence=confidence,
            class_id=np.zeros((xyxy.shape[0],), dtype=int),
        )
        tracked = self._tracker.update_with_detections(detections_sv)

        deduped: dict[int, tuple[list[int], float]] = {}
        tracked_conf = (
            tracked.confidence
            if hasattr(tracked, "confidence") and tracked.confidence is not None
            else np.ones((len(tracked.xyxy),), dtype=np.float32)
        )

        for bbox, tracker_id, conf in zip(tracked.xyxy, tracked.tracker_id, tracked_conf):
            if tracker_id is None:
                continue
            tid = int(tracker_id)
            box = [int(v) for v in bbox.tolist()]
            score = float(conf)
            previous = deduped.get(tid)
            if previous is None or score > previous[1]:
                deduped[tid] = (box, score)

        active_ids = set(deduped.keys())
        self._smoothed_boxes = {
            tid: box for tid, box in self._smoothed_boxes.items() if tid in active_ids
        }

        return [
            Track(track_id=tid, bbox=self._smooth(tid, box))
            for tid, (box, _) in deduped.items()
        ]

    def _smooth(self, track_id: int, bbox: list[int]) -> list[int]:
        previous = self._smoothed_boxes.get(track_id)
        if previous is None:
            smoothed = list(map(int, bbox))
        else:
            alpha = self._smoothing_alpha
            smoothed = [
                int(round(alpha * cur + (1.0 - alpha) * prev))
                for prev, cur in zip(previous, bbox)
            ]
        self._smoothed_boxes[track_id] = smoothed
        return smoothed
