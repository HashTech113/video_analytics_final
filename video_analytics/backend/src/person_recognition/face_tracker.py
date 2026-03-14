class Track:
    def __init__(self, bbox, track_id):
        self.track_id = track_id
        self.bbox = bbox
        self.missed = 0


class FaceTracker:
    def __init__(self, max_missing=10, iou_threshold=0.3):
        self.tracks = []
        self.next_id = 1
        self.max_missing = max_missing
        self.iou_threshold = iou_threshold

    def update(self, detections):
        updated_tracks = []

        for det in detections:
            best_track = None
            best_iou = 0

            for track in self.tracks:
                iou = self.compute_iou(det, track.bbox)
                if iou > best_iou and iou > self.iou_threshold:
                    best_iou = iou
                    best_track = track

            if best_track is not None:
                best_track.bbox = det
                best_track.missed = 0
                updated_tracks.append(best_track)
            else:
                new_track = Track(det, self.next_id)
                self.next_id += 1
                updated_tracks.append(new_track)

        for track in self.tracks:
            if track not in updated_tracks:
                track.missed += 1
                if track.missed < self.max_missing:
                    updated_tracks.append(track)

        self.tracks = updated_tracks
        return self.tracks

    def compute_iou(self, box_a, box_b):
        x_a = max(box_a[0], box_b[0])
        y_a = max(box_a[1], box_b[1])
        x_b = min(box_a[2], box_b[2])
        y_b = min(box_a[3], box_b[3])

        inter = max(0, x_b - x_a) * max(0, y_b - y_a)

        area_a = max(0, box_a[2] - box_a[0]) * max(0, box_a[3] - box_a[1])
        area_b = max(0, box_b[2] - box_b[0]) * max(0, box_b[3] - box_b[1])
        union = area_a + area_b - inter

        if union == 0:
            return 0

        return inter / union
