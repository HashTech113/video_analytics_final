import cv2

from .face_embedding import ArcFaceRecognizer
from .face_matcher import FaceMatcher
from .bytetrack_tracker import ByteTrackFaceTracker


class RecognitionService:
    def __init__(self):
        self.recognizer = ArcFaceRecognizer()
        self.matcher = FaceMatcher(self.recognizer)
        self.tracker = ByteTrackFaceTracker(
            track_thresh=0.4,
            track_buffer=40,
            match_thresh=0.7,
            frame_rate=30,
        )
        self.track_names = {}

    @staticmethod
    def _compute_iou(box_a, box_b):
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

    def recognize(self, frame):
        faces = self.recognizer.get_embeddings(frame)
        detections = []
        embeddings = []
        scores = []

        for face in faces:
            bbox = list(map(int, face["bbox"]))
            detections.append(bbox)
            embeddings.append(face["embedding"])
            scores.append(float(face.get("score", 1.0)))

        tracks = self.tracker.update(detections, scores=scores)
        results = []
        active_track_ids = set()

        for track in tracks:
            bbox = list(map(int, track.bbox))
            x1, y1, x2, y2 = bbox
            active_track_ids.add(track.track_id)

            name = "Unknown"
            if track.track_id in self.track_names:
                name = self.track_names[track.track_id]
            else:
                best_index = -1
                best_iou = 0.0
                for i, det in enumerate(detections):
                    iou = self._compute_iou(bbox, det)
                    if iou > best_iou:
                        best_iou = iou
                        best_index = i

                if best_index >= 0 and best_iou >= 0.3:
                    name = self.matcher.match(embeddings[best_index])
                self.track_names[track.track_id] = name

            label = f"{name} ID:{track.track_id}"

            results.append({
                "id": track.track_id,
                "name": name,
                "bbox": bbox,
            })

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                frame,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )

        # Drop labels for disappeared tracks to avoid unbounded cache growth.
        self.track_names = {
            track_id: name
            for track_id, name in self.track_names.items()
            if track_id in active_track_ids
        }

        return frame, results
