import os

import cv2
import numpy as np

from .bytetrack_tracker import ByteTrackFaceTracker
from .face_embedding import ArcFaceRecognizer
from .face_matcher import FaceMatcher


class RecognitionService:
    """
    Canonical real-time face recognition pipeline:
    detect -> track -> match -> draw.
    """

    def __init__(self):
        self.recognizer = ArcFaceRecognizer()
        self.matcher = FaceMatcher(self.recognizer)
        self.tracker = ByteTrackFaceTracker(
            track_thresh=0.25,
            track_buffer=30,
            match_thresh=0.8,
            frame_rate=30,
            fallback_iou_threshold=0.3,
            fallback_center_distance_threshold=120,
            smoothing_alpha=0.6,
        )
        self.track_names: dict[int, str] = {}

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

    def extract_faces(self, frame):
        faces = self.recognizer.get_embeddings(frame)
        detections = []
        embeddings = []
        scores = []

        for face in faces:
            bbox = list(map(int, face["bbox"]))
            detections.append(bbox)
            embeddings.append(face["embedding"])
            scores.append(float(face.get("score", 1.0)))

        return detections, embeddings, scores

    def track_faces(self, detections, scores):
        return self.tracker.update(detections, scores=scores)

    def resolve_track_identities(self, tracks, detections, embeddings):
        results = []
        active_track_ids = set()

        for track in tracks:
            bbox = list(map(int, track.bbox))
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

            results.append(
                {
                    "id": track.track_id,
                    "name": name,
                    "bbox": bbox,
                }
            )

        # Drop labels for disappeared tracks to avoid unbounded cache growth.
        self.track_names = {
            track_id: name
            for track_id, name in self.track_names.items()
            if track_id in active_track_ids
        }

        return results

    @staticmethod
    def draw_results(frame, results):
        for result in results:
            x1, y1, x2, y2 = result["bbox"]
            label = f"{result['name']} ID:{result['id']}"
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

    def recognize(self, frame):
        detections, embeddings, scores = self.extract_faces(frame)
        tracks = self.track_faces(detections, scores)
        results = self.resolve_track_identities(tracks, detections, embeddings)
        self.draw_results(frame, results)
        return frame, results


def match_embedding(query_embedding, match_threshold: float | None = None):
    """
    Compatibility DB matcher moved from recognition.py.
    """
    from sqlalchemy import text
    from src.db.session import SessionLocal

    threshold = match_threshold
    if threshold is None:
        threshold = float(os.getenv("MATCH_THRESHOLD", 0.50))

    db = SessionLocal()

    query_vec = np.array(query_embedding)
    query_vec = query_vec / np.linalg.norm(query_vec)

    known_results = db.execute(
        text(
            """
            SELECT id, name, average_embedding
            FROM persons
            WHERE average_embedding IS NOT NULL
            """
        )
    ).fetchall()

    if known_results:
        person_ids = []
        names = []
        embeddings = []

        for row in known_results:
            person_ids.append(row[0])
            names.append(row[1])
            embeddings.append(row[2])

        embeddings_matrix = np.array(embeddings)

        if embeddings_matrix.shape[1] == len(query_vec):
            embeddings_matrix = embeddings_matrix / np.linalg.norm(
                embeddings_matrix, axis=1, keepdims=True
            )
            scores = np.dot(embeddings_matrix, query_vec)

            best_index = np.argmax(scores)
            best_score = float(scores[best_index])

            if best_score >= threshold:
                db.close()
                return {
                    "type": "known",
                    "identity": {
                        "type": "known",
                        "identity_id": person_ids[best_index],
                        "label": names[best_index],
                    },
                    "score": best_score,
                }

    unknown_results = db.execute(
        text(
            """
            SELECT id, label, average_embedding
            FROM unknown_identities
            WHERE average_embedding IS NOT NULL
            """
        )
    ).fetchall()

    if unknown_results:
        unknown_ids = []
        labels = []
        embeddings = []

        for row in unknown_results:
            unknown_ids.append(row[0])
            labels.append(row[1])
            embeddings.append(row[2])

        unknown_matrix = np.array(embeddings)

        if unknown_matrix.shape[1] == len(query_vec):
            unknown_matrix = unknown_matrix / np.linalg.norm(
                unknown_matrix, axis=1, keepdims=True
            )
            scores = np.dot(unknown_matrix, query_vec)

            best_index = np.argmax(scores)
            best_unknown_score = float(scores[best_index])

            if best_unknown_score >= threshold:
                old_embedding = np.array(embeddings[best_index])
                new_avg = (old_embedding + query_vec) / 2

                db.execute(
                    text(
                        """
                        UPDATE unknown_identities
                        SET average_embedding=:emb
                        WHERE id=:id
                        """
                    ),
                    {
                        "emb": new_avg.tolist(),
                        "id": unknown_ids[best_index],
                    },
                )

                db.commit()
                db.close()

                return {
                    "type": "unknown",
                    "identity": {
                        "type": "unknown",
                        "identity_id": unknown_ids[best_index],
                        "label": labels[best_index],
                    },
                    "score": best_unknown_score,
                }

    result = db.execute(
        text(
            """
            INSERT INTO unknown_identities (label, average_embedding)
            VALUES ('temp', :emb)
            RETURNING id
            """
        ),
        {"emb": query_vec.tolist()},
    )

    new_unknown_id = result.scalar()
    new_label = f"U-{new_unknown_id}"

    db.execute(
        text(
            """
            UPDATE unknown_identities
            SET label=:label
            WHERE id=:id
            """
        ),
        {"label": new_label, "id": new_unknown_id},
    )

    db.commit()
    db.close()

    return {
        "type": "unknown",
        "identity": {
            "type": "unknown",
            "identity_id": new_unknown_id,
            "label": new_label,
        },
        "score": 0.0,
    }
