import os
import numpy as np
import cv2

# Absolute path to the dataset, resolved relative to this file so the backend
# works correctly regardless of the working directory it is started from.
_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_DEFAULT_DATASET_PATH = os.path.join(_BACKEND_DIR, "dataset", "person_dataset")


class FaceMatcher:
    def __init__(self, recognizer, dataset_path=None):
        dataset_path = dataset_path or _DEFAULT_DATASET_PATH
        self.recognizer = recognizer
        self.dataset_path = dataset_path

        self.known_embeddings = {}
        self.load_dataset()

    def load_dataset(self):
        if not os.path.isdir(self.dataset_path):
            return

        for person_name in os.listdir(self.dataset_path):
            person_path = os.path.join(self.dataset_path, person_name)

            if not os.path.isdir(person_path):
                continue

            embeddings = []

            for img_name in os.listdir(person_path):
                img_path = os.path.join(person_path, img_name)
                img = cv2.imread(img_path)
                if img is None:
                    continue

                faces = self.recognizer.get_embeddings(img)

                if len(faces) == 0:
                    continue

                embeddings.append(faces[0]["embedding"])

            if embeddings:
                self.known_embeddings[person_name] = np.mean(
                    embeddings,
                    axis=0,
                )

    def match(self, embedding, threshold=0.45):
        embedding_norm = np.linalg.norm(embedding)
        if embedding_norm == 0:
            return "Unknown"
        embedding = embedding / embedding_norm

        best_match = None
        best_score = 1.0

        for name, known_emb in self.known_embeddings.items():
            known_norm = np.linalg.norm(known_emb)
            if known_norm == 0:
                continue
            known_emb = known_emb / known_norm
            dist = np.linalg.norm(embedding - known_emb)

            if dist < best_score:
                best_score = dist
                best_match = name

        if best_score < threshold:
            return best_match

        return "Unknown"
