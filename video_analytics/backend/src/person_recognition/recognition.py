from sqlalchemy import text
from src.db.session import SessionLocal
import os
from dotenv import load_dotenv
import numpy as np

load_dotenv()

MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", 0.50))


def match_embedding(query_embedding):
    db = SessionLocal()

    query_vec = np.array(query_embedding)
    query_vec = query_vec / np.linalg.norm(query_vec)

    # ==================================================
    # 1️⃣ MATCH KNOWN PERSONS
    # ==================================================
    known_results = db.execute(
        text("""
            SELECT id, name, average_embedding
            FROM persons
            WHERE average_embedding IS NOT NULL
        """)
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

            if best_score >= MATCH_THRESHOLD:
                db.close()
                return {
                    "type": "known",
                    "identity": {
                        "type": "known",
                        "identity_id": person_ids[best_index],
                        "label": names[best_index]
                    },
                    "score": best_score
                }

    # ==================================================
    # 2️⃣ MATCH UNKNOWN (AVERAGE EMBEDDING)
    # ==================================================
    unknown_results = db.execute(
        text("""
            SELECT id, label, average_embedding
            FROM unknown_identities
            WHERE average_embedding IS NOT NULL
        """)
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

            if best_unknown_score >= MATCH_THRESHOLD:

                # 🔥 Improve unknown embedding (self-learning)
                old_embedding = np.array(embeddings[best_index])
                new_avg = (old_embedding + query_vec) / 2

                db.execute(
                    text("""
                        UPDATE unknown_identities
                        SET average_embedding=:emb
                        WHERE id=:id
                    """),
                    {
                        "emb": new_avg.tolist(),
                        "id": unknown_ids[best_index]
                    }
                )

                db.commit()
                db.close()

                return {
                    "type": "unknown",
                    "identity": {
                        "type": "unknown",
                        "identity_id": unknown_ids[best_index],
                        "label": labels[best_index]
                    },
                    "score": best_unknown_score
                }

    # ==================================================
    # 3️⃣ CREATE NEW UNKNOWN
    # ==================================================
    result = db.execute(
        text("""
            INSERT INTO unknown_identities (label, average_embedding)
            VALUES ('temp', :emb)
            RETURNING id
        """),
        {"emb": query_vec.tolist()}
    )

    new_unknown_id = result.scalar()
    new_label = f"U-{new_unknown_id}"

    db.execute(
        text("""
            UPDATE unknown_identities
            SET label=:label
            WHERE id=:id
        """),
        {"label": new_label, "id": new_unknown_id}
    )

    db.commit()
    db.close()

    return {
        "type": "unknown",
        "identity": {
            "type": "unknown",
            "identity_id": new_unknown_id,
            "label": new_label
        },
        "score": 0.0
    }