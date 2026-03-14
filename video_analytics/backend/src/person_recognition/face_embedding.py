import insightface
import numpy as np


class ArcFaceRecognizer:
    def __init__(self):
        self.model = insightface.app.FaceAnalysis(name="buffalo_l")
        self.model.prepare(ctx_id=-1, det_size=(640, 640))

    def get_embeddings(self, frame):
        faces = self.model.get(frame)

        embeddings = []
        for face in faces:
            embeddings.append({
                "bbox": face.bbox.astype(int),
                "embedding": face.embedding,
                "score": float(getattr(face, "det_score", 1.0)),
            })

        return embeddings
