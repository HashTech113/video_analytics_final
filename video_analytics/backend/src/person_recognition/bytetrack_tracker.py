from dataclasses import dataclass
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
    ):
        self._sv = None
        self._tracker = None
        self._fallback = FaceTracker(max_missing=track_buffer, iou_threshold=fallback_iou_threshold)
        self._try_init(track_thresh, track_buffer, match_thresh, frame_rate)

    def _try_init(self, track_thresh: float, track_buffer: int, match_thresh: float, frame_rate: int):
        try:
            import supervision as sv
        except Exception:
            return

        self._sv = sv
        self._tracker = sv.ByteTrack(
            track_activation_threshold=track_thresh,
            lost_track_buffer=track_buffer,
            minimum_matching_threshold=match_thresh,
            frame_rate=frame_rate,
        )
        print("ByteTrack initialized successfully")

    def update(self, detections, scores=None):
        if self._tracker is None or self._sv is None:
            return self._fallback.update(detections)

        if not detections:
            return []

        xyxy = np.array(detections, dtype=np.float32)
        if scores is None:
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

        tracks = []
        for bbox, tracker_id in zip(tracked.xyxy, tracked.tracker_id):
            if tracker_id is None:
                continue
            tracks.append(
                Track(
                    track_id=int(tracker_id),
                    bbox=[int(v) for v in bbox.tolist()],
                )
            )
        return tracks
