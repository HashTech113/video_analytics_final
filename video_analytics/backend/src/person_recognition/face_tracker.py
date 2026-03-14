class Track:
    def __init__(self, bbox, track_id):
        self.track_id = track_id
        self.bbox = list(map(int, bbox))
        self.missed = 0


class FaceTracker:
    def __init__(self, max_missing=2, iou_threshold=0.3, center_distance_threshold=80):
        self.tracks = []
        self.next_id = 1
        self.max_missing = max_missing
        self.iou_threshold = iou_threshold
        self.center_distance_threshold = center_distance_threshold

    def update(self, detections):
        detections = [list(map(int, det)) for det in detections]
        updated_tracks = []
        used_track_indexes = set()

        for det in detections:
            best_track_index = None
            best_iou = 0.0
            best_distance = float("inf")

            for idx, track in enumerate(self.tracks):
                if idx in used_track_indexes:
                    continue

                iou = self.compute_iou(det, track.bbox)
                distance = self.compute_center_distance(det, track.bbox)

                # Prefer IoU matches; fall back to center-distance when motion is fast.
                if iou >= self.iou_threshold:
                    if iou > best_iou or (iou == best_iou and distance < best_distance):
                        best_iou = iou
                        best_distance = distance
                        best_track_index = idx
                elif best_iou < self.iou_threshold and distance < self.center_distance_threshold:
                    if distance < best_distance:
                        best_distance = distance
                        best_track_index = idx

            if best_track_index is not None:
                matched_track = self.tracks[best_track_index]
                matched_track.bbox = self._smooth_bbox(matched_track.bbox, det)
                matched_track.missed = 0
                updated_tracks.append(matched_track)
                used_track_indexes.add(best_track_index)
            else:
                new_track = Track(det, self.next_id)
                self.next_id += 1
                updated_tracks.append(new_track)

        # Increment missed count for unmatched tracks and remove aggressively
        for idx, track in enumerate(self.tracks):
            if idx in used_track_indexes:
                continue
            track.missed += 1
            if track.missed < self.max_missing:
                updated_tracks.append(track)
            # If missed >= max_missing, track is removed immediately

        self.tracks = updated_tracks
        return self.tracks
    @staticmethod
    def _smooth_bbox(previous, current, alpha=0.6):
        return [
            int(round(alpha * cur + (1.0 - alpha) * prev))
            for prev, cur in zip(previous, current)
        ]

    @staticmethod
    def compute_center_distance(box_a, box_b):
        ax = (box_a[0] + box_a[2]) / 2.0
        ay = (box_a[1] + box_a[3]) / 2.0
        bx = (box_b[0] + box_b[2]) / 2.0
        by = (box_b[1] + box_b[3]) / 2.0
        dx = ax - bx
        dy = ay - by
        return (dx * dx + dy * dy) ** 0.5

    @staticmethod
    def compute_iou(box_a, box_b):
        x_a = max(box_a[0], box_b[0])
        y_a = max(box_a[1], box_b[1])
        x_b = min(box_a[2], box_b[2])
        y_b = min(box_a[3], box_b[3])

        inter = max(0, x_b - x_a) * max(0, y_b - y_a)

        area_a = max(0, box_a[2] - box_a[0]) * max(0, box_a[3] - box_a[1])
        area_b = max(0, box_b[2] - box_b[0]) * max(0, box_b[3] - box_b[1])
        union = area_a + area_b - inter

        if union == 0:
            return 0.0

        return inter / union
